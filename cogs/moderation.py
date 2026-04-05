import datetime
import json
import logging
from pathlib import Path

import discord
from discord.ext import commands, tasks

from utils import embeds

logger = logging.getLogger("discord_bot")

# File penyimpanan
WARNS_FILE  = Path("data/warns.json")
CONFIG_FILE = Path("data/guild_config.json")

# Konfigurasi DEFAULT — berlaku untuk semua guild yang belum punya custom config
DEFAULT_CONFIG = {
    # Threshold warn → tindakan otomatis
    # Format: {"jumlah_warn": "aksi"}   aksi: "timeout" | "kick" | "ban"
    "warn_thresholds": {
        "3": "timeout",
        "5": "kick",
        "7": "ban",
    },
    # Durasi auto-timeout (menit) saat threshold "timeout" tercapai
    "timeout_duration": 5,
    # Durasi decay warn (hari). Setiap poin butuh kelipatan ini tanpa pelanggaran.
    # Contoh: decay=30, 2 warn → poin 1 hilang di hari ke-30, poin 2 di hari ke-60
    # Set ke 0 untuk menonaktifkan decay (warn tidak pernah expire otomatis)
    "warn_decay_days": 30,
}

# Batas nilai
VALID_ACTIONS   = {"timeout", "kick", "ban", "none"}
MAX_WARN_COUNT  = 50
MAX_TIMEOUT_MIN = 40320    # 28 hari (batas Discord)
MAX_DECAY_DAYS  = 365


# Helper: guild config
def _load_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Gagal membaca guild_config.json: {e}")
    return {}


def _save_config(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"Gagal menyimpan guild_config.json: {e}")


def get_guild_config(guild_id: int) -> dict:
    """Kembalikan config guild dengan fallback ke DEFAULT_CONFIG."""
    raw       = _load_config()
    guild_cfg = raw.get(str(guild_id), {})
    return {
        "warn_thresholds": {
            **DEFAULT_CONFIG["warn_thresholds"],
            **guild_cfg.get("warn_thresholds", {}),
        },
        "timeout_duration": guild_cfg.get("timeout_duration", DEFAULT_CONFIG["timeout_duration"]),
        "warn_decay_days":  guild_cfg.get("warn_decay_days",  DEFAULT_CONFIG["warn_decay_days"]),
    }


def _set_guild_value(guild_id: int, key: str, value) -> None:
    raw = _load_config()
    raw.setdefault(str(guild_id), {})[key] = value
    _save_config(raw)


def _reset_guild_config(guild_id: int) -> None:
    raw = _load_config()
    raw.pop(str(guild_id), None)
    _save_config(raw)


# Helper: warn data
def _load_warns() -> dict:
    try:
        if WARNS_FILE.exists():
            with open(WARNS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Gagal membaca warns.json: {e}")
    return {}


def _save_warns(data: dict) -> None:
    WARNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(WARNS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"Gagal menyimpan warns.json: {e}")


def _get_member_warns(data: dict, guild_id: int, member_id: int) -> list:
    """Kembalikan seluruh warn entry milik member (semua status)."""
    return data.get(str(guild_id), {}).get(str(member_id), [])


def _add_warn_entry(data: dict, guild_id: int, member_id: int, entry: dict) -> None:
    data.setdefault(str(guild_id), {}).setdefault(str(member_id), []).append(entry)


def _get_active_warns(data: dict, guild_id: int, member_id: int) -> list:
    """Kembalikan warn yang masih aktif (belum di-clear/expired)."""
    return [
        w for w in _get_member_warns(data, guild_id, member_id)
        if w.get("status", "active") == "active"
    ]


def _soft_clear_warns(
    data: dict,
    guild_id: int,
    member_id: int,
    cleared_by_id: int,
    cleared_by_nama: str,
    alasan_clear: str = "Tidak ada alasan.",
) -> int:
    """Tandai semua warn aktif sebagai 'cleared'. Kembalikan jumlah yang di-clear."""
    warn_list   = data.get(str(guild_id), {}).get(str(member_id), [])
    waktu_clear = discord.utils.utcnow().isoformat()
    count = 0
    for w in warn_list:
        if w.get("status", "active") == "active":
            w["status"]          = "cleared"
            w["cleared_by_id"]   = cleared_by_id
            w["cleared_by_nama"] = cleared_by_nama
            w["cleared_alasan"]  = alasan_clear
            w["cleared_waktu"]   = waktu_clear
            count += 1
    return count


def _soft_clear_one_warn(
    data: dict,
    guild_id: int,
    member_id: int,
    warn_index: int,
    cleared_by_id: int,
    cleared_by_nama: str,
    alasan_clear: str = "Tidak ada alasan.",
) -> dict | None:
    """
    Tandai SATU warn aktif (warn_index 1-based, terlama=1) sebagai 'cleared'.
    Kembalikan warn entry yang di-clear, atau None jika index tidak valid.
    """
    active_sorted = sorted(
        _get_active_warns(data, guild_id, member_id),
        key=lambda w: w.get("waktu", "")
    )
    if warn_index < 1 or warn_index > len(active_sorted):
        return None

    target                    = active_sorted[warn_index - 1]
    waktu_clear               = discord.utils.utcnow().isoformat()
    target["status"]          = "cleared"
    target["cleared_by_id"]   = cleared_by_id
    target["cleared_by_nama"] = cleared_by_nama
    target["cleared_alasan"]  = alasan_clear
    target["cleared_waktu"]   = waktu_clear
    return target


# Sistem Decay — lazy check
def process_warn_decay(data: dict, guild_id: int, member_id: int, decay_days: int) -> int:
    """
    Hitung dan terapkan decay warn secara lazy.

    Algoritma:
    1. Ambil semua warn aktif, urutkan dari terlama ke terbaru.
    2. Cari tanggal warn TERAKHIR (most recent active warn) sebagai anchor.
    3. Poin ke-N expire jika: sekarang >= anchor + (N × decay_days).
       - Poin terlama (index 0) expire duluan di anchor + 1×decay_days
       - Poin berikutnya (index 1) expire di anchor + 2×decay_days, dst.
    4. Warn yang expire ditandai status "expired".

    Kembalikan jumlah warn yang baru saja di-expire.
    """
    if decay_days <= 0:
        return 0   # decay dinonaktifkan

    active = _get_active_warns(data, guild_id, member_id)
    if not active:
        return 0

    # Urutkan dari terlama ke terbaru berdasarkan waktu pemberian
    active_sorted = sorted(active, key=lambda w: w.get("waktu", ""))

    # Anchor: tanggal warn aktif PALING BARU
    try:
        anchor = datetime.datetime.fromisoformat(active_sorted[-1]["waktu"])
        # Pastikan timezone-aware
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=datetime.timezone.utc)
    except (KeyError, ValueError):
        return 0

    now    = discord.utils.utcnow()
    count  = 0
    expire_ts = now.isoformat()

    for i, w in enumerate(active_sorted):
        # Poin ke-(i+1) butuh (i+1) × decay_days hari bersih
        needed_days = (i + 1) * decay_days
        expire_at   = anchor + datetime.timedelta(days=needed_days)
        if now >= expire_at:
            w["status"]         = "expired"
            w["expired_waktu"]  = expire_ts
            count += 1

    return count


# Helper tampilan — sisa waktu decay untuk warn aktif
def _decay_info(active_sorted: list, decay_days: int) -> list[str]:
    """
    Untuk tiap warn aktif (urutan terlama→terbaru), kembalikan string
    berisi kapan warn itu akan expire.
    """
    if decay_days <= 0 or not active_sorted:
        return ["*(decay nonaktif)*"] * len(active_sorted)

    try:
        anchor = datetime.datetime.fromisoformat(active_sorted[-1]["waktu"])
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=datetime.timezone.utc)
    except (KeyError, ValueError):
        return ["?"] * len(active_sorted)

    result = []
    for i in range(len(active_sorted)):
        expire_at = anchor + datetime.timedelta(days=(i + 1) * decay_days)
        result.append(discord.utils.format_dt(expire_at, style="R"))   # "in 23 days"
    return result


# Cog Utama
class Moderation(commands.Cog, name="Moderasi"):
    """Perintah-perintah moderasi server."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._daily_decay_task.start()   # mulai background task saat cog di-load

    def cog_unload(self):
        self._daily_decay_task.cancel()  # hentikan task saat cog di-unload / bot restart

    # ── Daily sweep — background task ─────────────────────────────────────
    @tasks.loop(hours=24)
    async def _daily_decay_task(self):
        """
        Sweep decay warn untuk semua member di semua guild, sekali sehari.
        Dijalankan otomatis; tidak ada output ke channel kecuali ada yang expire.
        """
        await self.bot.wait_until_ready()

        data       = _load_warns()
        config_raw = _load_config()
        changed    = False
        total      = 0

        for guild_id_str, members in data.items():
            try:
                guild_id   = int(guild_id_str)
                guild_cfg  = config_raw.get(guild_id_str, {})
                decay_days = guild_cfg.get("warn_decay_days", DEFAULT_CONFIG["warn_decay_days"])
            except (ValueError, KeyError):
                continue

            if decay_days <= 0:
                continue   # decay nonaktif untuk guild ini

            for member_id_str in list(members.keys()):
                try:
                    member_id = int(member_id_str)
                except ValueError:
                    continue

                expired = process_warn_decay(data, guild_id, member_id, decay_days)
                if expired:
                    total   += expired
                    changed  = True
                    logger.info(
                        f"DAILY-SWEEP | {expired} warn expire "
                        f"[guild={guild_id} member={member_id}]"
                    )

        if changed:
            _save_warns(data)
            logger.info(f"DAILY-SWEEP selesai | Total warn di-expire: {total}")
        else:
            logger.debug("DAILY-SWEEP selesai | Tidak ada warn yang expire.")

    @_daily_decay_task.before_loop
    async def _before_daily_decay(self):
        """
        Tunda task pertama agar mulai mendekati 00:00 UTC berikutnya.
        Ini mencegah sweep terjadi di jam acak saat bot restart.
        """
        await self.bot.wait_until_ready()
        now        = discord.utils.utcnow()
        tomorrow   = (now + datetime.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        wait_secs  = (tomorrow - now).total_seconds()
        logger.info(
            f"DAILY-SWEEP dijadwalkan pertama kali dalam "
            f"{wait_secs / 3600:.1f} jam (00:00 UTC)."
        )
        await discord.utils.sleep_until(tomorrow)

    # ── Log channel ───────────────────────────────────────────────────────
    async def send_log(self, guild: discord.Guild, embed: discord.Embed):
        """Kirim log moderasi ke sistem logging terpusat (kategori 'moderation')."""
        from cogs.logging import send_log as central_send_log
        await central_send_log(guild, "moderation", embed)

    # ── Tindakan otomatis berdasarkan warn count ───────────────────────────
    async def _apply_threshold_action(
        self,
        ctx: commands.Context,
        member: discord.Member,
        warn_count: int,
    ) -> str | None:
        cfg         = get_guild_config(ctx.guild.id)
        thresholds  = cfg["warn_thresholds"]
        timeout_dur = cfg["timeout_duration"]

        action = thresholds.get(str(warn_count))
        if not action or action == "none":
            return None

        reason_auto = f"[Auto] Mencapai {warn_count} peringatan."

        if action == "timeout":
            until = discord.utils.utcnow() + datetime.timedelta(minutes=timeout_dur)
            try:
                await member.timeout(until, reason=reason_auto)
            except discord.Forbidden:
                return "⚠️ Gagal timeout otomatis (kurang izin)."
            await self.send_log(ctx.guild, embeds.mod_action(
                f"⏱️ Auto-Timeout {timeout_dur} Menit",
                member, self.bot.user, reason_auto, discord.Color.yellow()
            ))
            logger.info(f"AUTO-TIMEOUT | {member} selama {timeout_dur}m (warn ke-{warn_count})")
            return f"⏱️ **Auto-timeout {timeout_dur} menit** ({warn_count} warn)"

        elif action == "kick":
            try:
                await member.kick(reason=reason_auto)
            except discord.Forbidden:
                return "⚠️ Gagal auto-kick (kurang izin)."
            await self.send_log(ctx.guild, embeds.mod_action("👢 Auto-Kick", member, self.bot.user, reason_auto))
            logger.info(f"AUTO-KICK | {member} (warn ke-{warn_count})")
            return f"👢 **Auto-kick** ({warn_count} warn)"

        elif action == "ban":
            try:
                await member.ban(reason=reason_auto)
            except discord.Forbidden:
                return "⚠️ Gagal auto-ban (kurang izin)."
            await self.send_log(ctx.guild, embeds.mod_action("🔨 Auto-Ban", member, self.bot.user, reason_auto, discord.Color.red()))
            logger.info(f"AUTO-BAN | {member} (warn ke-{warn_count})")
            return f"🔨 **Auto-ban** ({warn_count} warn)"

        return None

    # GRUP PERINTAH: config
    @commands.group(
        name="config",
        invoke_without_command=True,
        help="Kelola konfigurasi bot untuk server ini."
    )
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def config_group(self, ctx):
        embed = discord.Embed(
            title="⚙️ Perintah Config",
            color=discord.Color.blurple(),
            description="Gunakan sub-perintah berikut. Semua perubahan hanya berlaku untuk server ini."
        )
        embed.add_field(
            name="Sub-perintah",
            value=(
                "`!config show` — Lihat config aktif\n"
                "`!config setwarn <N> <aksi>` — Atur aksi pada warn ke-N\n"
                "`!config removewarn <N>` — Hapus threshold warn ke-N\n"
                "`!config setTimeout <menit>` — Atur durasi auto-timeout\n"
                "`!config setdecay <hari>` — Atur durasi decay warn (0 = nonaktif)\n"
                "`!config reset` — Kembalikan semua config ke default\n"
            ),
            inline=False
        )
        embed.add_field(
            name="Aksi tersedia untuk setwarn",
            value="`timeout` · `kick` · `ban` · `none` (nonaktifkan threshold)",
            inline=False
        )
        await ctx.send(embed=embed)

    # ── !config show ──────────────────────────────────────────────────────
    @config_group.command(name="show", help="Tampilkan konfigurasi aktif server ini.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def config_show(self, ctx):
        cfg = get_guild_config(ctx.guild.id)

        embed = discord.Embed(
            title=f"⚙️ Konfigurasi — {ctx.guild.name}",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)

        # Threshold warn
        thresholds = cfg["warn_thresholds"]
        th_lines = "\n".join(
            f"Warn **{k}×** → `{v}`"
            for k, v in sorted(thresholds.items(), key=lambda x: int(x[0]))
        ) if thresholds else "*(tidak ada threshold)*"
        embed.add_field(name="📊 Threshold Warn", value=th_lines, inline=False)

        # Durasi timeout & decay
        embed.add_field(
            name="⏱️ Durasi Auto-Timeout",
            value=f"**{cfg['timeout_duration']} menit**",
            inline=True
        )
        decay = cfg["warn_decay_days"]
        embed.add_field(
            name="⏳ Decay Warn",
            value=f"**{decay} hari** per poin" if decay > 0 else "**Nonaktif**",
            inline=True
        )

        embed.set_footer(text="Gunakan !config untuk melihat daftar perintah pengaturan.")
        await ctx.send(embed=embed)

    # ── !config setwarn ───────────────────────────────────────────────────
    @config_group.command(name="setwarn", help="Atur tindakan otomatis pada warn ke-N. Contoh: !config setwarn 3 timeout")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def config_setwarn(self, ctx, jumlah: int, aksi: str):
        aksi = aksi.lower()
        if jumlah < 1 or jumlah > MAX_WARN_COUNT:
            return await ctx.send(embed=embeds.error(f"Jumlah warn harus antara 1–{MAX_WARN_COUNT}."))
        if aksi not in VALID_ACTIONS:
            return await ctx.send(embed=embeds.error(f"Aksi tidak valid. Pilihan: `{'` · `'.join(VALID_ACTIONS)}`"))

        raw = _load_config()
        raw.setdefault(str(ctx.guild.id), {}).setdefault("warn_thresholds", {})[str(jumlah)] = aksi
        _save_config(raw)

        desc = (f"Threshold warn **{jumlah}×** dinonaktifkan." if aksi == "none"
                else f"Warn **{jumlah}×** sekarang akan memicu **{aksi}** otomatis.")
        await ctx.send(embed=embeds.success(desc, title="✅ Threshold Diperbarui"))
        logger.info(f"CONFIG setwarn | Guild {ctx.guild.id} | warn {jumlah} → {aksi} oleh {ctx.author}")

    # ── !config removewarn ────────────────────────────────────────────────
    @config_group.command(name="removewarn", help="Hapus threshold warn pada angka tertentu.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def config_removewarn(self, ctx, jumlah: int):
        raw        = _load_config()
        gk         = str(ctx.guild.id)
        thresholds = raw.get(gk, {}).get("warn_thresholds", {})
        if str(jumlah) not in thresholds:
            return await ctx.send(embed=embeds.error(f"Tidak ada threshold custom untuk warn ke-**{jumlah}**."))
        del thresholds[str(jumlah)]
        raw.setdefault(gk, {})["warn_thresholds"] = thresholds
        _save_config(raw)
        await ctx.send(embed=embeds.success(
            f"Threshold warn **{jumlah}×** dihapus.",
            title="🗑️ Threshold Dihapus"
        ))
        logger.info(f"CONFIG removewarn | Guild {ctx.guild.id} | hapus threshold {jumlah} oleh {ctx.author}")

    # ── !config setTimeout ────────────────────────────────────────────────
    @config_group.command(name="setTimeout", help="Atur durasi auto-timeout (menit). Contoh: !config setTimeout 10")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def config_set_timeout(self, ctx, menit: int):
        if menit < 1 or menit > MAX_TIMEOUT_MIN:
            return await ctx.send(embed=embeds.error(f"Durasi harus antara 1–{MAX_TIMEOUT_MIN} menit."))
        _set_guild_value(ctx.guild.id, "timeout_duration", menit)
        await ctx.send(embed=embeds.success(
            f"Durasi auto-timeout diatur ke **{menit} menit**.",
            title="✅ Timeout Duration Diperbarui"
        ))
        logger.info(f"CONFIG setTimeout | Guild {ctx.guild.id} | {menit}m oleh {ctx.author}")

    # ── !config setdecay ──────────────────────────────────────────────────
    @config_group.command(
        name="setdecay",
        help=(
            "Atur durasi decay warn per poin (hari). "
            "Contoh: !config setdecay 30  |  Gunakan 0 untuk menonaktifkan decay."
        )
    )
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def config_set_decay(self, ctx, hari: int):
        if hari < 0 or hari > MAX_DECAY_DAYS:
            return await ctx.send(embed=embeds.error(f"Durasi decay harus antara 0–{MAX_DECAY_DAYS} hari."))

        _set_guild_value(ctx.guild.id, "warn_decay_days", hari)

        if hari == 0:
            desc = "Decay warn **dinonaktifkan**. Warn aktif tidak akan expire otomatis."
        else:
            desc = (
                f"Durasi decay diatur ke **{hari} hari** per poin.\n"
                f"Contoh: member dengan 2 warn aktif akan kehilangan poin ke-1 setelah "
                f"**{hari} hari** tanpa pelanggaran, dan poin ke-2 setelah **{hari * 2} hari**."
            )
        await ctx.send(embed=embeds.success(desc, title="✅ Decay Warn Diperbarui"))
        logger.info(f"CONFIG setdecay | Guild {ctx.guild.id} | {hari} hari oleh {ctx.author}")

    # ── !config reset ─────────────────────────────────────────────────────
    @config_group.command(name="reset", help="Kembalikan seluruh config server ke default.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def config_reset(self, ctx):
        _reset_guild_config(ctx.guild.id)
        await ctx.send(embed=embeds.success(
            "Semua konfigurasi server ini telah dikembalikan ke **default**.",
            title="🔄 Config Di-reset"
        ))
        logger.info(f"CONFIG reset | Guild {ctx.guild.id} oleh {ctx.author}")

    # PERINTAH: warn
    @commands.command(name="warn", help="Beri peringatan ke member (dikirim via DM).")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def warn(self, ctx, member: discord.Member, *, alasan: str = "Tidak ada alasan."):
        if member == ctx.author:
            return await ctx.send(embed=embeds.error("Kamu tidak bisa warn dirimu sendiri."))
        if member.top_role >= ctx.author.top_role:
            return await ctx.send(embed=embeds.error("Kamu tidak bisa warn member dengan role lebih tinggi."))

        cfg        = get_guild_config(ctx.guild.id)
        decay_days = cfg["warn_decay_days"]

        data = _load_warns()

        # ── Lazy decay: cek expire SEBELUM tambah warn baru ───────────────
        expired = process_warn_decay(data, ctx.guild.id, member.id, decay_days)
        if expired:
            _save_warns(data)
            logger.info(f"DECAY | {expired} warn {member} expire sebelum warn baru")

        # ── Tambah warn baru ───────────────────────────────────────────────
        entry = {
            "status":    "active",
            "alasan":    alasan,
            "oleh_id":   ctx.author.id,
            "oleh_nama": str(ctx.author),
            "waktu":     discord.utils.utcnow().isoformat(),
        }
        _add_warn_entry(data, ctx.guild.id, member.id, entry)
        _save_warns(data)

        active_warns = _get_active_warns(data, ctx.guild.id, member.id)
        warn_count   = len(active_warns)

        # ── Info decay untuk DM ────────────────────────────────────────────
        decay_note = ""
        if decay_days > 0:
            decay_note = (
                f"\n**Decay:** Poin ke-{warn_count} akan hilang otomatis dalam "
                f"**{warn_count * decay_days} hari** tanpa pelanggaran."
            )

        # ── DM ke member ───────────────────────────────────────────────────
        try:
            dm_embed = embeds.warning(
                f"Kamu mendapat peringatan di **{ctx.guild.name}**.\n"
                f"**Alasan:** {alasan}\n"
                f"**Total peringatan aktif:** {warn_count}"
                f"{decay_note}",
                title="⚠️ Peringatan"
            )
            await member.send(embed=dm_embed)
            dm_status = "📨 DM terkirim"
        except discord.Forbidden:
            dm_status = "⚠️ DM diblokir"

        # ── Embed konfirmasi di channel ────────────────────────────────────
        embed = embeds.mod_action("⚠️ Member Diperingatkan", member, ctx.author, alasan, discord.Color.gold())
        embed.add_field(name="Total Warn Aktif", value=f"**{warn_count}** poin", inline=True)
        embed.add_field(name="Status DM",        value=dm_status,                inline=True)

        if decay_days > 0:
            embed.add_field(
                name="⏳ Decay",
                value=(
                    f"Timer decay semua poin di-reset.\n"
                    f"Poin ke-1 expire {discord.utils.format_dt(discord.utils.utcnow() + datetime.timedelta(days=decay_days), style='R')}."
                ),
                inline=False
            )

        action_taken = await self._apply_threshold_action(ctx, member, warn_count)
        if action_taken:
            embed.add_field(name="Tindakan Otomatis", value=action_taken, inline=False)

        await ctx.send(embed=embed)
        await self.send_log(ctx.guild, embed)
        logger.info(f"WARN #{warn_count} | {member} oleh {ctx.author} | Alasan: {alasan}")

    # PERINTAH: warnlist  (khusus moderator — bisa lihat warn siapapun)
    @commands.command(name="warnlist", aliases=["warns", "warnhistory"], help="Lihat riwayat warn member.")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def warnlist(self, ctx, member: discord.Member):
        cfg        = get_guild_config(ctx.guild.id)
        decay_days = cfg["warn_decay_days"]

        data = _load_warns()

        # Lazy decay sebelum tampilkan
        expired = process_warn_decay(data, ctx.guild.id, member.id, decay_days)
        if expired:
            _save_warns(data)

        await self._send_warnlist_embed(ctx, member, data, decay_days, expired)

    # PERINTAH: mywarns  (semua user — hanya bisa lihat warn sendiri)
    @commands.command(name="mywarns", help="Lihat riwayat warnmu sendiri (hanya bisa melihat milik sendiri).")
    @commands.guild_only()
    async def mywarns(self, ctx):
        cfg        = get_guild_config(ctx.guild.id)
        decay_days = cfg["warn_decay_days"]

        data = _load_warns()

        # Lazy decay sebelum tampilkan
        expired = process_warn_decay(data, ctx.guild.id, ctx.author.id, decay_days)
        if expired:
            _save_warns(data)

        # Kirim via DM agar tidak terekspos di channel publik
        try:
            await self._send_warnlist_embed(ctx, ctx.author, data, decay_days, expired, via_dm=True)
            if ctx.guild:   # Konfirmasi singkat di channel
                await ctx.send(
                    embed=embeds.success("Riwayat warnmu sudah dikirim ke DM kamu. 📨", title="📋 My Warns"),
                    delete_after=10
                )
        except discord.Forbidden:
            # DM diblokir, tampilkan di channel saja
            await self._send_warnlist_embed(ctx, ctx.author, data, decay_days, expired)

    # ── Helper: kirim embed warnlist ──────────────────────────────────────
    async def _send_warnlist_embed(
        self,
        ctx: commands.Context,
        member: discord.Member | discord.User,
        data: dict,
        decay_days: int,
        auto_expired: int = 0,
        via_dm: bool = False,
    ):
        all_warns     = _get_member_warns(data, ctx.guild.id, member.id)
        active_warns  = [w for w in all_warns if w.get("status", "active") == "active"]
        cleared_warns = [w for w in all_warns if w.get("status") == "cleared"]
        expired_warns = [w for w in all_warns if w.get("status") == "expired"]

        dest = member if via_dm else ctx   # kirim ke DM atau channel

        if not all_warns:
            embed = embeds.success(
                f"{'Kamu' if via_dm else member.mention} tidak memiliki riwayat peringatan.",
                title="📋 Riwayat Warn"
            )
            await dest.send(embed=embed)
            return

        # Urutkan active dari terlama ke terbaru untuk kalkulasi decay
        active_sorted  = sorted(active_warns, key=lambda w: w.get("waktu", ""))
        decay_countdowns = _decay_info(active_sorted, decay_days)

        display_name = "Kamu" if via_dm else member.display_name
        embed = discord.Embed(
            title=f"📋 Riwayat Warn — {display_name}",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        if hasattr(member, "display_avatar"):
            embed.set_thumbnail(url=member.display_avatar.url)

        # Ringkasan
        decay_str = f"**{decay_days} hari** per poin" if decay_days > 0 else "Nonaktif"
        ringkasan = (
            f"🔴 Warn aktif: **{len(active_warns)}** poin\n"
            f"✅ Di-clear manual: **{len(cleared_warns)}**\n"
            f"💨 Expire otomatis: **{len(expired_warns)}**\n"
            f"📊 Total sepanjang waktu: **{len(all_warns)}**\n"
            f"⏳ Decay: {decay_str}"
        )
        if auto_expired:
            ringkasan += f"\n\n*({auto_expired} warn baru saja expire saat kamu membuka riwayat ini)*"
        embed.add_field(name="Ringkasan", value=ringkasan, inline=False)

        # ── Warn aktif + countdown decay ──────────────────────────────────
        if active_sorted:
            embed.add_field(name="─── ⚠️ Warn Aktif ───", value="", inline=False)
            display_active = active_sorted[-5:]
            if len(active_sorted) > 5:
                embed.add_field(
                    name="", inline=False,
                    value=f"*...dan {len(active_sorted) - 5} warn aktif lainnya (menampilkan 5 terbaru)*"
                )
            # Sesuaikan offset countdown dengan slice yang ditampilkan
            start_idx = len(active_sorted) - len(display_active)
            for i, w in enumerate(display_active):
                global_i    = start_idx + i          # index dalam active_sorted
                warn_num    = global_i + 1            # nomor urut poin (1-based)
                countdown   = decay_countdowns[global_i]
                try:
                    waktu_str = discord.utils.format_dt(
                        datetime.datetime.fromisoformat(w["waktu"]), style="d"
                    )
                except (KeyError, ValueError):
                    waktu_str = "Tidak diketahui"
                embed.add_field(
                    name=f"Poin #{warn_num} 🔴",
                    value=(
                        f"**Alasan:** {w.get('alasan', '-')}\n"
                        f"**Oleh:** {w.get('oleh_nama', 'Unknown')} (<@{w.get('oleh_id', 0)}>)\n"
                        f"**Tanggal:** {waktu_str}\n"
                        f"**Expire:** {countdown}"
                    ),
                    inline=False,
                )

        # ── Warn yang sudah di-clear manual ───────────────────────────────
        if cleared_warns:
            embed.add_field(name="─── 🧹 Di-clear Manual ───", value="", inline=False)
            for w in cleared_warns[-3:]:
                try:
                    warn_waktu  = discord.utils.format_dt(datetime.datetime.fromisoformat(w["waktu"]), style="d")
                except (KeyError, ValueError):
                    warn_waktu = "?"
                try:
                    clear_waktu = discord.utils.format_dt(datetime.datetime.fromisoformat(w["cleared_waktu"]), style="d")
                except (KeyError, ValueError):
                    clear_waktu = "?"
                embed.add_field(
                    name="Warn (cleared) ✅",
                    value=(
                        f"**Alasan warn:** {w.get('alasan', '-')} *(diberi {warn_waktu})*\n"
                        f"**Di-clear oleh:** {w.get('cleared_by_nama', 'Unknown')} (<@{w.get('cleared_by_id', 0)}>)\n"
                        f"**Alasan clear:** {w.get('cleared_alasan', '-')}\n"
                        f"**Tanggal clear:** {clear_waktu}"
                    ),
                    inline=False,
                )
            if len(cleared_warns) > 3:
                embed.add_field(name="", value=f"*...dan {len(cleared_warns) - 3} riwayat clear lainnya*", inline=False)

        # ── Warn yang expire otomatis ──────────────────────────────────────
        if expired_warns:
            embed.add_field(name="─── 💨 Expire Otomatis ───", value="", inline=False)
            for w in expired_warns[-3:]:
                try:
                    warn_waktu = discord.utils.format_dt(datetime.datetime.fromisoformat(w["waktu"]), style="d")
                except (KeyError, ValueError):
                    warn_waktu = "?"
                try:
                    exp_waktu = discord.utils.format_dt(datetime.datetime.fromisoformat(w["expired_waktu"]), style="d")
                except (KeyError, ValueError):
                    exp_waktu = "?"
                embed.add_field(
                    name="Warn (expired) 💨",
                    value=(
                        f"**Alasan:** {w.get('alasan', '-')} *(diberi {warn_waktu})*\n"
                        f"**Expire pada:** {exp_waktu}"
                    ),
                    inline=False,
                )
            if len(expired_warns) > 3:
                embed.add_field(name="", value=f"*...dan {len(expired_warns) - 3} riwayat expire lainnya*", inline=False)

        await dest.send(embed=embed)

    # PERINTAH: clearwarns
    @commands.command(name="clearwarns", help="Hapus semua warn aktif milik member.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def clearwarns(self, ctx, member: discord.Member, *, alasan: str = "Tidak ada alasan."):
        data        = _load_warns()
        active_list = _get_active_warns(data, ctx.guild.id, member.id)

        if not active_list:
            return await ctx.send(embed=embeds.success(
                f"{member.mention} tidak memiliki warn aktif untuk dihapus.",
                title="✅ Clear Warns"
            ))

        jumlah = _soft_clear_warns(
            data, ctx.guild.id, member.id,
            ctx.author.id, str(ctx.author), alasan
        )
        _save_warns(data)

        embed = embeds.success(
            f"**{jumlah}** warn aktif milik {member.mention} berhasil di-clear.\n"
            f"**Alasan:** {alasan}\n"
            f"*Riwayat tetap tersimpan dan bisa dilihat dengan `!warnlist`.*",
            title="🧹 Warn Di-clear"
        )
        embed.set_footer(text=f"Oleh: {ctx.author}")
        await ctx.send(embed=embed)
        await self.send_log(ctx.guild, embed)
        logger.info(f"CLEARWARNS | {jumlah} warn {member} di-clear oleh {ctx.author} | Alasan: {alasan}")

    # PERINTAH: removewarn  (hapus 1 poin warn TERLAMA)
    @commands.command(
        name="removewarn",
        aliases=["delwarn"],
        help="Hapus 1 poin warn terlama milik member. Contoh: !removewarn @user [alasan]"
    )
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def removewarn(self, ctx, member: discord.Member, *, alasan: str = "Tidak ada alasan."):
        if member == ctx.author:
            return await ctx.send(embed=embeds.error("Kamu tidak bisa menghapus warnmu sendiri."))

        data        = _load_warns()
        active_list = _get_active_warns(data, ctx.guild.id, member.id)

        if not active_list:
            return await ctx.send(embed=embeds.error(
                f"{member.mention} tidak memiliki warn aktif."
            ))

        total_aktif = len(active_list)

        # Hapus poin ke-1 (terlama) — index 1-based
        cleared = _soft_clear_one_warn(
            data, ctx.guild.id, member.id,
            warn_index=1,
            cleared_by_id=ctx.author.id,
            cleared_by_nama=str(ctx.author),
            alasan_clear=alasan
        )
        _save_warns(data)

        sisa = total_aktif - 1

        try:
            warn_tgl = discord.utils.format_dt(
                datetime.datetime.fromisoformat(cleared["waktu"]), style="d"
            )
        except (KeyError, ValueError):
            warn_tgl = "?"

        embed = embeds.success(
            f"1 poin warn terlama milik {member.mention} berhasil dihapus.\n\n"
            f"**Alasan warn asli:** {cleared.get('alasan', '-')} *(diberikan {warn_tgl})*\n"
            f"**Alasan dihapus:** {alasan}\n"
            f"**Sisa warn aktif:** {sisa} poin\n\n"
            f"*Riwayat tetap tersimpan dan bisa dilihat dengan `!warnlist`.*",
            title="🗑️ Warn Terlama Dihapus"
        )
        embed.set_footer(text=f"Oleh: {ctx.author}")
        await ctx.send(embed=embed)
        await self.send_log(ctx.guild, embed)
        logger.info(
            f"REMOVEWARN | Poin terlama {member} di-clear oleh {ctx.author} | "
            f"Alasan: {alasan} | Sisa: {sisa}"
        )

    # PERINTAH MODERASI STANDAR
    @commands.command(name="kick", help="Kick member dari server.")
    @commands.has_permissions(kick_members=True)
    @commands.guild_only()
    async def kick(self, ctx, member: discord.Member, *, alasan: str = "Tidak ada alasan."):
        if member == ctx.author:
            return await ctx.send(embed=embeds.error("Kamu tidak bisa kick dirimu sendiri."))
        if member.top_role >= ctx.author.top_role:
            return await ctx.send(embed=embeds.error("Kamu tidak bisa kick member dengan role lebih tinggi."))
        await member.kick(reason=alasan)
        embed = embeds.mod_action("👢 Member Di-kick", member, ctx.author, alasan)
        await ctx.send(embed=embed)
        await self.send_log(ctx.guild, embed)
        logger.info(f"KICK | {member} oleh {ctx.author} | Alasan: {alasan}")

    @commands.command(name="ban", help="Ban member dari server.")
    @commands.has_permissions(ban_members=True)
    @commands.guild_only()
    async def ban(self, ctx, member: discord.Member, *, alasan: str = "Tidak ada alasan."):
        if member == ctx.author:
            return await ctx.send(embed=embeds.error("Kamu tidak bisa ban dirimu sendiri."))
        if member.top_role >= ctx.author.top_role:
            return await ctx.send(embed=embeds.error("Kamu tidak bisa ban member dengan role lebih tinggi."))
        await member.ban(reason=alasan)
        embed = embeds.mod_action("🔨 Member Di-ban", member, ctx.author, alasan, discord.Color.red())
        await ctx.send(embed=embed)
        await self.send_log(ctx.guild, embed)
        logger.info(f"BAN | {member} oleh {ctx.author} | Alasan: {alasan}")

    @commands.command(name="unban", help="Unban member (format: Nama#1234 atau ID).")
    @commands.has_permissions(ban_members=True)
    @commands.guild_only()
    async def unban(self, ctx, *, target: str):
        bans = [entry async for entry in ctx.guild.bans()]
        user = None
        for ban_entry in bans:
            if str(ban_entry.user) == target or str(ban_entry.user.id) == target:
                user = ban_entry.user
                break
        if not user:
            return await ctx.send(embed=embeds.error(f"User **{target}** tidak ada di daftar ban."))
        await ctx.guild.unban(user)
        embed = embeds.success(f"**{user}** berhasil di-unban.", title="✅ Member Di-unban")
        embed.set_footer(text=f"Oleh: {ctx.author}")
        await ctx.send(embed=embed)
        logger.info(f"UNBAN | {user} oleh {ctx.author}")

    @commands.command(name="timeout", aliases=["to"], help="Timeout member (dalam menit).")
    @commands.has_permissions(moderate_members=True)
    @commands.guild_only()
    async def timeout(self, ctx, member: discord.Member, durasi: int = 10, *, alasan: str = "Tidak ada alasan."):
        if durasi < 1 or durasi > MAX_TIMEOUT_MIN:
            return await ctx.send(embed=embeds.error(f"Durasi timeout harus antara 1–{MAX_TIMEOUT_MIN} menit."))
        until = discord.utils.utcnow() + datetime.timedelta(minutes=durasi)
        await member.timeout(until, reason=alasan)
        embed = embeds.mod_action(f"⏱️ Timeout {durasi} Menit", member, ctx.author, alasan, discord.Color.yellow())
        await ctx.send(embed=embed)
        await self.send_log(ctx.guild, embed)
        logger.info(f"TIMEOUT | {member} selama {durasi}m oleh {ctx.author}")

    @commands.command(name="untimeout", aliases=["uto"], help="Hapus timeout member.")
    @commands.has_permissions(moderate_members=True)
    @commands.guild_only()
    async def untimeout(self, ctx, member: discord.Member):
        await member.timeout(None)
        embed = embeds.success(f"Timeout {member.mention} telah dihapus.", title="🔓 Timeout Dihapus")
        embed.set_footer(text=f"Oleh: {ctx.author}")
        await ctx.send(embed=embed)

    @commands.command(name="clear", aliases=["purge"], help="Hapus pesan di channel (maks 100).")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def clear(self, ctx, jumlah: int = 10):
        if not 1 <= jumlah <= 100:
            return await ctx.send(embed=embeds.error("Jumlah pesan harus antara 1–100."))
        await ctx.message.delete()
        deleted = await ctx.channel.purge(limit=jumlah)
        msg = await ctx.send(embed=embeds.success(f"**{len(deleted)}** pesan berhasil dihapus.", title="🗑️ Clear"))
        await msg.delete(delay=5)
        logger.info(f"CLEAR | {len(deleted)} pesan di #{ctx.channel.name} oleh {ctx.author}")

    @commands.command(name="slowmode", help="Atur slowmode channel (0 = nonaktif).")
    @commands.has_permissions(manage_channels=True)
    @commands.guild_only()
    async def slowmode(self, ctx, detik: int = 0):
        if not 0 <= detik <= 21600:
            return await ctx.send(embed=embeds.error("Nilai slowmode harus antara 0–21600 detik."))
        await ctx.channel.edit(slowmode_delay=detik)
        if detik == 0:
            await ctx.send(embed=embeds.success("Slowmode **dinonaktifkan**."))
        else:
            await ctx.send(embed=embeds.success(f"Slowmode diatur ke **{detik} detik**."))

    @commands.command(name="lock", help="Kunci channel agar member tidak bisa kirim pesan.")
    @commands.has_permissions(manage_channels=True)
    @commands.guild_only()
    async def lock(self, ctx):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(embed=embeds.warning(f"Channel {ctx.channel.mention} **dikunci**. 🔒"))

    @commands.command(name="unlock", help="Buka kunci channel.")
    @commands.has_permissions(manage_channels=True)
    @commands.guild_only()
    async def unlock(self, ctx):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = True
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(embed=embeds.success(f"Channel {ctx.channel.mention} **dibuka**. 🔓"))

    # Error handlers
    @kick.error
    @ban.error
    @timeout.error
    @warn.error
    @warnlist.error
    @mywarns.error
    @removewarn.error
    @clearwarns.error
    @clear.error
    async def mod_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=embeds.error("Kamu tidak punya izin untuk perintah ini."))
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=embeds.error("Member tidak ditemukan."))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=embeds.error(f"Argumen kurang. Coba: `help {ctx.command.name}`"))
        else:
            logger.error(f"Error pada {ctx.command}: {error}")
            await ctx.send(embed=embeds.error(f"Terjadi error: `{error}`"))

    @config_group.error
    async def config_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=embeds.error("Hanya **Administrator** server yang bisa mengubah konfigurasi bot."))
        else:
            logger.error(f"Error pada config: {error}")
            await ctx.send(embed=embeds.error(f"Terjadi error: `{error}`"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))