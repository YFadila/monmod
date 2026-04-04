"""
Cog: Moderasi
Semua perintah moderasi server + sistem konfigurasi per-guild.
"""

import datetime
import json
import logging
import os
from pathlib import Path

import discord
from discord.ext import commands

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
    # ID channel log moderasi (override .env per-guild, null = pakai .env)
    "log_channel_id": None,
}

# Batas nilai yang boleh diset agar tidak disalahgunakan
VALID_ACTIONS    = {"timeout", "kick", "ban", "none"}
MAX_WARN_COUNT   = 50          # maksimum threshold warn yang masuk akal
MAX_TIMEOUT_MIN  = 40320       # 28 hari (batas Discord)

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
    """
    Kembalikan config untuk guild tertentu.
    Field yang belum diset akan di-fallback ke DEFAULT_CONFIG.
    """
    raw = _load_config()
    guild_cfg = raw.get(str(guild_id), {})

    # Deep-merge: ambil default, timpa dengan nilai guild jika ada
    cfg = {
        "warn_thresholds": {
            **DEFAULT_CONFIG["warn_thresholds"],
            **guild_cfg.get("warn_thresholds", {}),
        },
        "timeout_duration": guild_cfg.get("timeout_duration", DEFAULT_CONFIG["timeout_duration"]),
        "log_channel_id":   guild_cfg.get("log_channel_id",   DEFAULT_CONFIG["log_channel_id"]),
    }
    return cfg


def _set_guild_value(guild_id: int, key: str, value) -> None:
    """Set satu key di config guild, lalu simpan."""
    raw = _load_config()
    gk  = str(guild_id)
    raw.setdefault(gk, {})[key] = value
    _save_config(raw)


def _reset_guild_config(guild_id: int) -> None:
    """Hapus seluruh config custom guild (kembali ke default)."""
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
    return data.get(str(guild_id), {}).get(str(member_id), [])


def _add_warn_entry(data: dict, guild_id: int, member_id: int, entry: dict) -> None:
    data.setdefault(str(guild_id), {}).setdefault(str(member_id), []).append(entry)


def _get_active_warns(data: dict, guild_id: int, member_id: int) -> list:
    """Kembalikan hanya warn yang masih aktif (belum di-clear)."""
    all_warns = _get_member_warns(data, guild_id, member_id)
    return [w for w in all_warns if w.get("status", "active") == "active"]


def _soft_clear_warns(
    data: dict,
    guild_id: int,
    member_id: int,
    cleared_by_id: int,
    cleared_by_nama: str,
    alasan_clear: str = "Tidak ada alasan.",
) -> int:
    """
    Tandai semua warn aktif sebagai 'cleared' (soft-delete).
    Kembalikan jumlah warn yang di-clear.
    """
    gk, mk = str(guild_id), str(member_id)
    warn_list = data.get(gk, {}).get(mk, [])
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


# Cog utama
class Moderation(commands.Cog, name="Moderasi"):
    """Perintah-perintah moderasi server."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Log channel (mendukung config per-guild) ───────────────────────────
    async def send_log(self, guild: discord.Guild, embed: discord.Embed):
        """Kirim log ke channel moderasi. Prioritas: config guild → env LOG_CHANNEL_ID."""
        cfg = get_guild_config(guild.id)
        channel_id = cfg["log_channel_id"] or os.getenv("LOG_CHANNEL_ID")
        if channel_id:
            channel = guild.get_channel(int(channel_id))
            if channel:
                await channel.send(embed=embed)

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
            log_embed = embeds.mod_action(
                f"⏱️ Auto-Timeout {timeout_dur} Menit",
                member, self.bot.user, reason_auto, discord.Color.yellow()
            )
            await self.send_log(ctx.guild, log_embed)
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

    # GRUP PERINTAH: config  (!config ...)
    # Hanya administrator guild yang boleh menggunakan perintah ini.
    @commands.group(
        name="config",
        invoke_without_command=True,
        help="Kelola konfigurasi bot untuk server ini."
    )
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def config_group(self, ctx):
        """Tampilkan semua sub-perintah config yang tersedia."""
        embed = discord.Embed(
            title="⚙️ Perintah Config",
            color=discord.Color.blurple(),
            description=(
                "Gunakan sub-perintah berikut untuk mengatur bot di server ini.\n"
                "Semua perubahan hanya berlaku untuk server ini."
            )
        )
        embed.add_field(
            name="Sub-perintah",
            value=(
                "`!config show` — Lihat config aktif\n"
                "`!config setwarn <jumlah> <aksi>` — Atur aksi pada warn ke-N\n"
                "`!config removewarn <jumlah>` — Hapus threshold warn\n"
                "`!config setTimeout <menit>` — Atur durasi auto-timeout\n"
                "`!config setlog <#channel | clear>` — Atur channel log moderasi\n"
                "`!config reset` — Kembalikan semua config ke default\n"
            ),
            inline=False
        )
        embed.add_field(
            name="Aksi yang tersedia",
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
        if thresholds:
            th_lines = "\n".join(
                f"Warn **{k}×** → `{v}`"
                for k, v in sorted(thresholds.items(), key=lambda x: int(x[0]))
            )
        else:
            th_lines = "*(tidak ada threshold)*"
        embed.add_field(name="📊 Threshold Warn", value=th_lines, inline=False)

        # Durasi timeout
        embed.add_field(
            name="⏱️ Durasi Auto-Timeout",
            value=f"**{cfg['timeout_duration']} menit**",
            inline=True
        )

        # Log channel
        log_id = cfg["log_channel_id"] or os.getenv("LOG_CHANNEL_ID")
        log_val = f"<#{log_id}>" if log_id else "*(belum diatur)*"
        embed.add_field(name="📋 Log Channel", value=log_val, inline=True)

        embed.set_footer(text="Gunakan !config untuk melihat daftar perintah pengaturan.")
        await ctx.send(embed=embed)

    # ── !config setwarn <jumlah> <aksi> ──────────────────────────────────
    @config_group.command(
        name="setwarn",
        help="Atur tindakan otomatis pada warn ke-N. Contoh: !config setwarn 3 timeout"
    )
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def config_setwarn(self, ctx, jumlah: int, aksi: str):
        aksi = aksi.lower()

        if jumlah < 1 or jumlah > MAX_WARN_COUNT:
            return await ctx.send(embed=embeds.error(f"Jumlah warn harus antara 1–{MAX_WARN_COUNT}."))
        if aksi not in VALID_ACTIONS:
            return await ctx.send(
                embed=embeds.error(f"Aksi tidak valid. Pilihan: `{'` · `'.join(VALID_ACTIONS)}`")
            )

        raw = _load_config()
        gk  = str(ctx.guild.id)
        raw.setdefault(gk, {}).setdefault("warn_thresholds", {})[str(jumlah)] = aksi
        _save_config(raw)

        if aksi == "none":
            desc = f"Threshold warn **{jumlah}×** dinonaktifkan."
        else:
            desc = f"Warn **{jumlah}×** sekarang akan memicu **{aksi}** otomatis."

        await ctx.send(embed=embeds.success(desc, title="✅ Threshold Diperbarui"))
        logger.info(f"CONFIG setwarn | Guild {ctx.guild.id} | warn {jumlah} → {aksi} oleh {ctx.author}")

    # ── !config removewarn <jumlah> ──────────────────────────────────────
    @config_group.command(
        name="removewarn",
        help="Hapus threshold warn pada angka tertentu. Contoh: !config removewarn 5"
    )
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def config_removewarn(self, ctx, jumlah: int):
        raw = _load_config()
        gk  = str(ctx.guild.id)
        thresholds = raw.get(gk, {}).get("warn_thresholds", {})

        if str(jumlah) not in thresholds:
            return await ctx.send(embed=embeds.error(f"Tidak ada threshold custom untuk warn ke-**{jumlah}**."))

        del thresholds[str(jumlah)]
        raw.setdefault(gk, {})["warn_thresholds"] = thresholds
        _save_config(raw)

        await ctx.send(embed=embeds.success(
            f"Threshold warn **{jumlah}×** dihapus. Bot akan kembali ke default jika ada.",
            title="🗑️ Threshold Dihapus"
        ))
        logger.info(f"CONFIG removewarn | Guild {ctx.guild.id} | hapus threshold {jumlah} oleh {ctx.author}")

    # ── !config setTimeout <menit> ────────────────────────────────────────
    @config_group.command(
        name="setTimeout",
        help="Atur durasi auto-timeout (menit). Contoh: !config setTimeout 10"
    )
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def config_set_timeout(self, ctx, menit: int):
        if menit < 1 or menit > MAX_TIMEOUT_MIN:
            return await ctx.send(embed=embeds.error(f"Durasi harus antara 1–{MAX_TIMEOUT_MIN} menit (28 hari)."))

        _set_guild_value(ctx.guild.id, "timeout_duration", menit)
        await ctx.send(embed=embeds.success(
            f"Durasi auto-timeout diatur ke **{menit} menit**.",
            title="✅ Timeout Duration Diperbarui"
        ))
        logger.info(f"CONFIG setTimeout | Guild {ctx.guild.id} | {menit}m oleh {ctx.author}")

    # ── !config setlog <#channel | clear> ────────────────────────────────
    @config_group.command(
        name="setlog",
        help="Atur channel log moderasi. Gunakan 'clear' untuk menghapus. Contoh: !config setlog #mod-log"
    )
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def config_set_log(self, ctx, *, target: str):
        target = target.strip()

        if target.lower() == "clear":
            _set_guild_value(ctx.guild.id, "log_channel_id", None)
            return await ctx.send(embed=embeds.success(
                "Log channel dihapus. Bot akan pakai `LOG_CHANNEL_ID` dari env (jika ada).",
                title="✅ Log Channel Dihapus"
            ))

        # Coba parse mention channel atau ID
        channel = None
        if ctx.message.channel_mentions:
            channel = ctx.message.channel_mentions[0]
        elif target.isdigit():
            channel = ctx.guild.get_channel(int(target))

        if not channel:
            return await ctx.send(embed=embeds.error("Channel tidak ditemukan. Mention channel atau kirim ID-nya."))

        _set_guild_value(ctx.guild.id, "log_channel_id", channel.id)
        await ctx.send(embed=embeds.success(
            f"Log moderasi akan dikirim ke {channel.mention}.",
            title="✅ Log Channel Diperbarui"
        ))
        logger.info(f"CONFIG setlog | Guild {ctx.guild.id} | #{channel.name} oleh {ctx.author}")

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
    @commands.command(name="warn", help="Beri peringatan ke member (dikirim langsung di channel).")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def warn(self, ctx, member: discord.Member, *, alasan: str = "Tidak ada alasan."):
        if member == ctx.author:
            return await ctx.send(embed=embeds.error("Kamu tidak bisa warn dirimu sendiri."))
        if member.top_role >= ctx.author.top_role:
            return await ctx.send(embed=embeds.error("Kamu tidak bisa warn member dengan role lebih tinggi."))

        data = _load_warns()
        entry = {
            "status":    "active",
            "alasan":    alasan,
            "oleh_id":   ctx.author.id,
            "oleh_nama": str(ctx.author),
            "waktu":     discord.utils.utcnow().isoformat(),
        }
        _add_warn_entry(data, ctx.guild.id, member.id, entry)
        _save_warns(data)

        warn_count = len(_get_active_warns(data, ctx.guild.id, member.id))

        embed = embeds.mod_action("⚠️ Member Diperingatkan", member, ctx.author, alasan, discord.Color.gold())
        embed.add_field(name="Total Warn", value=f"**{warn_count}** peringatan", inline=True)

        action_taken = await self._apply_threshold_action(ctx, member, warn_count)
        if action_taken:
            embed.add_field(name="Tindakan Otomatis", value=action_taken, inline=False)

        await ctx.send(content=f"Halo {member.mention}, kamu mendapatkan peringatan!", embed=embed)
        await self.send_log(ctx.guild, embed)
        logger.info(f"WARN #{warn_count} | {member} oleh {ctx.author} | Alasan: {alasan}")

    # PERINTAH: warnlist
    @commands.command(name="warnlist", aliases=["warns", "warnhistory"], help="Lihat riwayat warn member.")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def warnlist(self, ctx, member: discord.Member):
        data      = _load_warns()
        all_warns = _get_member_warns(data, ctx.guild.id, member.id)

        if not all_warns:
            return await ctx.send(embed=embeds.success(
                f"{member.mention} tidak memiliki riwayat peringatan.",
                title="📋 Riwayat Warn"
            ))

        active_warns  = [w for w in all_warns if w.get("status", "active") == "active"]
        cleared_warns = [w for w in all_warns if w.get("status") == "cleared"]

        embed = discord.Embed(
            title=f"📋 Riwayat Warn — {member.display_name}",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Ringkasan",
            value=(
                f"🔴 Warn aktif: **{len(active_warns)}**\n"
                f"✅ Pernah di-clear: **{len(cleared_warns)}**\n"
                f"📊 Total sepanjang waktu: **{len(all_warns)}**"
            ),
            inline=False
        )

        # ── Warn aktif ────────────────────────────────────────────────────
        if active_warns:
            embed.add_field(name="─── ⚠️ Warn Aktif ───", value="", inline=False)
            display_active = active_warns[-5:]   # maks 5 terbaru
            if len(active_warns) > 5:
                embed.add_field(
                    name="",
                    value=f"*...dan {len(active_warns) - 5} warn aktif lainnya (menampilkan 5 terbaru)*",
                    inline=False
                )
            offset = len(active_warns) - len(display_active) + 1
            for i, w in enumerate(display_active, start=offset):
                try:
                    waktu_str = discord.utils.format_dt(datetime.datetime.fromisoformat(w["waktu"]), style="d")
                except (KeyError, ValueError):
                    waktu_str = "Tidak diketahui"
                embed.add_field(
                    name=f"Warn #{i} 🔴",
                    value=(
                        f"**Alasan:** {w.get('alasan', '-')}\n"
                        f"**Oleh:** {w.get('oleh_nama', 'Unknown')} (<@{w.get('oleh_id', 0)}>)\n"
                        f"**Tanggal:** {waktu_str}"
                    ),
                    inline=False,
                )

        # ── Riwayat warn yang sudah di-clear ──────────────────────────────
        if cleared_warns:
            embed.add_field(name="─── 🧹 Riwayat Clear Warn ───", value="", inline=False)
            display_cleared = cleared_warns[-5:]   # maks 5 terbaru
            if len(cleared_warns) > 5:
                embed.add_field(
                    name="",
                    value=f"*...dan {len(cleared_warns) - 5} warn cleared lainnya (menampilkan 5 terbaru)*",
                    inline=False
                )
            # Kelompokkan per sesi clear (cleared_waktu yang sama = satu aksi clearwarns)
            # Tampilkan langsung per warn entry agar detail terlihat
            for i, w in enumerate(display_cleared, start=1):
                try:
                    warn_waktu = discord.utils.format_dt(datetime.datetime.fromisoformat(w["waktu"]), style="d")
                except (KeyError, ValueError):
                    warn_waktu = "?"
                try:
                    clear_waktu = discord.utils.format_dt(datetime.datetime.fromisoformat(w["cleared_waktu"]), style="d")
                except (KeyError, ValueError):
                    clear_waktu = "?"

                embed.add_field(
                    name=f"Warn (cleared) ✅",
                    value=(
                        f"**Alasan warn:** {w.get('alasan', '-')} *(diberi {warn_waktu})*\n"
                        f"**Di-clear oleh:** {w.get('cleared_by_nama', 'Unknown')} "
                        f"(<@{w.get('cleared_by_id', 0)}>)\n"
                        f"**Alasan clear:** {w.get('cleared_alasan', '-')}\n"
                        f"**Tanggal clear:** {clear_waktu}"
                    ),
                    inline=False,
                )

        await ctx.send(embed=embed)

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
            return await ctx.send(embed=embeds.error(f"Durasi timeout harus antara 1–{MAX_TIMEOUT_MIN} menit (28 hari)."))
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

    # Error handler global
    @kick.error
    @ban.error
    @timeout.error
    @warn.error
    @warnlist.error
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