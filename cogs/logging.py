import datetime
import json
import logging
from pathlib import Path

import discord
from discord.ext import commands

from utils import embeds as embed_utils

logger = logging.getLogger("discord_bot")

LOG_CONFIG_FILE = Path("data/log_config.json")

# Definisi kategori
CATEGORIES = {
    "moderation": {"label": "Moderasi",       "emoji": "🔨", "color": discord.Color.red()},
    "messages":   {"label": "Pesan",          "emoji": "💬", "color": discord.Color.blue()},
    "members":    {"label": "Member",         "emoji": "👤", "color": discord.Color.green()},
    "roles":      {"label": "Role",           "emoji": "🎭", "color": discord.Color.purple()},
    "channels":   {"label": "Channel",        "emoji": "📢", "color": discord.Color.orange()},
    "server":     {"label": "Server",         "emoji": "🏠", "color": discord.Color.gold()},
    "voice":      {"label": "Voice",          "emoji": "🎙️", "color": discord.Color.teal()},
}

# Daftar kategori untuk help text
CATEGORY_LIST = " · ".join(f"`{k}`" for k in CATEGORIES)


# Helper I/O
def _load_log_config() -> dict:
    try:
        if LOG_CONFIG_FILE.exists():
            with open(LOG_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Gagal membaca log_config.json: {e}")
    return {}


def _save_log_config(data: dict) -> None:
    LOG_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(LOG_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"Gagal menyimpan log_config.json: {e}")


def _guild_log_config(data: dict, guild_id: int) -> dict:
    """Kembalikan config log guild, buat default jika belum ada."""
    gk = str(guild_id)
    if gk not in data:
        data[gk] = {
            "categories": {
                cat: {"enabled": False, "channel_id": None}
                for cat in CATEGORIES
            }
        }
    # Pastikan semua kategori ada (backward compat jika ada kategori baru)
    for cat in CATEGORIES:
        data[gk]["categories"].setdefault(cat, {"enabled": False, "channel_id": None})
    return data[gk]


def _get_cat_config(guild_id: int, category: str) -> dict | None:
    """Kembalikan config satu kategori, atau None jika tidak valid."""
    if category not in CATEGORIES:
        return None
    data = _load_log_config()
    cfg  = _guild_log_config(data, guild_id)
    return cfg["categories"][category]


# Helper: kirim log embed ke channel kategori
async def send_log(
    guild: discord.Guild,
    category: str,
    embed: discord.Embed,
) -> None:
    """
    Fungsi publik yang dipanggil dari cog lain (misal moderation)
    maupun dari dalam cog ini sendiri.
    Kirim embed ke channel log kategori jika enabled dan channel diset.
    """
    data    = _load_log_config()
    cfg     = _guild_log_config(data, guild.id)
    cat_cfg = cfg["categories"].get(category, {})

    if not cat_cfg.get("enabled"):
        return
    channel_id = cat_cfg.get("channel_id")
    if not channel_id:
        return

    channel = guild.get_channel(channel_id)
    if not channel:
        return

    try:
        await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.warning(f"LOG [{category}] Gagal kirim ke #{channel.name}: {e}")


def _make_embed(
    category: str,
    title: str,
    description: str = "",
    fields: list[tuple] = None,   # list of (name, value, inline)
    thumbnail_url: str = None,
) -> discord.Embed:
    """Buat embed log dengan warna dan footer konsisten per kategori."""
    cat_info = CATEGORIES.get(category, {})
    embed = discord.Embed(
        title=f"{cat_info.get('emoji', '📋')} {title}",
        description=description or "",
        color=cat_info.get("color", discord.Color.greyple()),
        timestamp=discord.utils.utcnow(),
    )
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=str(value)[:1024] or "—", inline=inline)
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    embed.set_footer(text=f"Log: {cat_info.get('label', category)}")
    return embed


def _fmt_user(user: discord.User | discord.Member) -> str:
    return f"{user.mention} (`{user}` · ID: `{user.id}`)"


def _fmt_channel(channel) -> str:
    return f"{channel.mention} (`#{channel.name}` · ID: `{channel.id}`)"


# Cog
class Logging(commands.Cog, name="Logging"):
    """Sistem logging server per-kategori."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # GRUP PERINTAH: logset
    @commands.group(
        name="logset",
        invoke_without_command=True,
        help="Konfigurasi sistem logging server."
    )
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def logset_group(self, ctx):
        embed = discord.Embed(
            title="📋 Konfigurasi Logging",
            color=discord.Color.blurple(),
            description=(
                "Atur channel dan aktifkan/nonaktifkan log per kategori.\n"
                f"Kategori tersedia: {CATEGORY_LIST}"
            )
        )
        embed.add_field(
            name="Sub-perintah",
            value=(
                "`!logset status` — Lihat status semua kategori log\n"
                "`!logset channel <kategori> <#channel>` — Set channel log\n"
                "`!logset enable <kategori>` — Aktifkan kategori log\n"
                "`!logset disable <kategori>` — Nonaktifkan kategori log\n"
                "`!logset enableall` — Aktifkan semua kategori sekaligus\n"
                "`!logset disableall` — Nonaktifkan semua kategori sekaligus\n"
                "`!logset reset` — Reset seluruh konfigurasi log server ini\n"
            ),
            inline=False
        )
        embed.add_field(
            name="💡 Alur kerja",
            value=(
                "1. `!logset channel moderation #mod-log` — set channel\n"
                "2. `!logset enable moderation` — aktifkan\n"
                "3. Selesai — log moderasi akan masuk ke #mod-log"
            ),
            inline=False
        )
        await ctx.send(embed=embed)

    # ── !logset status ────────────────────────────────────────────────────
    @logset_group.command(name="status", help="Lihat status semua kategori log.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def logset_status(self, ctx):
        data    = _load_log_config()
        cfg     = _guild_log_config(data, ctx.guild.id)
        cats    = cfg["categories"]

        embed = discord.Embed(
            title=f"📋 Status Logging — {ctx.guild.name}",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)

        for cat_key, cat_info in CATEGORIES.items():
            cat_cfg    = cats.get(cat_key, {})
            enabled    = cat_cfg.get("enabled", False)
            channel_id = cat_cfg.get("channel_id")
            channel    = ctx.guild.get_channel(channel_id) if channel_id else None

            status_icon  = "🟢" if enabled else "🔴"
            channel_str  = channel.mention if channel else "*(belum diset)*"
            if enabled and not channel:
                channel_str += " ⚠️ *(aktif tapi channel belum diset!)*"

            embed.add_field(
                name=f"{cat_info['emoji']} {cat_info['label']}",
                value=f"{status_icon} {'Aktif' if enabled else 'Nonaktif'}\n📌 {channel_str}",
                inline=True,
            )

        embed.set_footer(text="Gunakan !logset untuk mengubah konfigurasi.")
        await ctx.send(embed=embed)

    # ── !logset channel <kategori> <#channel> ─────────────────────────────
    @logset_group.command(
        name="channel",
        help="Set channel log untuk satu kategori. Contoh: !logset channel messages #message-log"
    )
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def logset_channel(self, ctx, category: str, channel: discord.TextChannel):
        category = category.lower()
        if category not in CATEGORIES:
            return await ctx.send(embed=embed_utils.error(
                f"Kategori tidak valid.\nPilihan: {CATEGORY_LIST}"
            ))

        data     = _load_log_config()
        cfg      = _guild_log_config(data, ctx.guild.id)
        cfg["categories"][category]["channel_id"] = channel.id
        _save_log_config(data)

        cat_info = CATEGORIES[category]
        await ctx.send(embed=embed_utils.success(
            f"Channel log **{cat_info['label']}** diatur ke {channel.mention}.\n"
            f"Pastikan kategori ini sudah diaktifkan: `!logset enable {category}`",
            title=f"✅ Log Channel Diset — {cat_info['emoji']} {cat_info['label']}"
        ))
        logger.info(f"LOGSET CHANNEL | {category} → #{channel.name} guild {ctx.guild.id} oleh {ctx.author}")

    # ── !logset enable <kategori> ─────────────────────────────────────────
    @logset_group.command(name="enable", help="Aktifkan kategori log. Contoh: !logset enable messages")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def logset_enable(self, ctx, category: str):
        category = category.lower()
        if category not in CATEGORIES:
            return await ctx.send(embed=embed_utils.error(
                f"Kategori tidak valid.\nPilihan: {CATEGORY_LIST}"
            ))

        data     = _load_log_config()
        cfg      = _guild_log_config(data, ctx.guild.id)
        cat_cfg  = cfg["categories"][category]
        cat_cfg["enabled"] = True
        _save_log_config(data)

        cat_info   = CATEGORIES[category]
        channel_id = cat_cfg.get("channel_id")
        channel    = ctx.guild.get_channel(channel_id) if channel_id else None
        extra      = (
            f"\n✅ Log akan masuk ke {channel.mention}."
            if channel else
            f"\n⚠️ Channel belum diset. Gunakan: `!logset channel {category} #channel`"
        )
        await ctx.send(embed=embed_utils.success(
            f"Kategori **{cat_info['label']}** diaktifkan.{extra}",
            title=f"🟢 Log Diaktifkan — {cat_info['emoji']} {cat_info['label']}"
        ))
        logger.info(f"LOGSET ENABLE | {category} guild {ctx.guild.id} oleh {ctx.author}")

    # ── !logset disable <kategori> ────────────────────────────────────────
    @logset_group.command(name="disable", help="Nonaktifkan kategori log. Contoh: !logset disable voice")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def logset_disable(self, ctx, category: str):
        category = category.lower()
        if category not in CATEGORIES:
            return await ctx.send(embed=embed_utils.error(
                f"Kategori tidak valid.\nPilihan: {CATEGORY_LIST}"
            ))

        data    = _load_log_config()
        cfg     = _guild_log_config(data, ctx.guild.id)
        cfg["categories"][category]["enabled"] = False
        _save_log_config(data)

        cat_info = CATEGORIES[category]
        await ctx.send(embed=embed_utils.success(
            f"Kategori **{cat_info['label']}** dinonaktifkan.",
            title=f"🔴 Log Dinonaktifkan — {cat_info['emoji']} {cat_info['label']}"
        ))
        logger.info(f"LOGSET DISABLE | {category} guild {ctx.guild.id} oleh {ctx.author}")

    # ── !logset enableall ─────────────────────────────────────────────────
    @logset_group.command(name="enableall", help="Aktifkan semua kategori log sekaligus.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def logset_enableall(self, ctx):
        data = _load_log_config()
        cfg  = _guild_log_config(data, ctx.guild.id)
        for cat in CATEGORIES:
            cfg["categories"][cat]["enabled"] = True
        _save_log_config(data)

        # Cek kategori yang belum punya channel
        no_channel = [
            f"`{cat}`" for cat, c in cfg["categories"].items()
            if not c.get("channel_id")
        ]
        extra = (
            f"\n\n⚠️ Kategori berikut belum punya channel log:\n{', '.join(no_channel)}"
            if no_channel else ""
        )
        await ctx.send(embed=embed_utils.success(
            f"Semua kategori log diaktifkan.{extra}",
            title="🟢 Semua Log Diaktifkan"
        ))
        logger.info(f"LOGSET ENABLEALL | Guild {ctx.guild.id} oleh {ctx.author}")

    # ── !logset disableall ────────────────────────────────────────────────
    @logset_group.command(name="disableall", help="Nonaktifkan semua kategori log sekaligus.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def logset_disableall(self, ctx):
        data = _load_log_config()
        cfg  = _guild_log_config(data, ctx.guild.id)
        for cat in CATEGORIES:
            cfg["categories"][cat]["enabled"] = False
        _save_log_config(data)

        await ctx.send(embed=embed_utils.success(
            "Semua kategori log dinonaktifkan.",
            title="🔴 Semua Log Dinonaktifkan"
        ))
        logger.info(f"LOGSET DISABLEALL | Guild {ctx.guild.id} oleh {ctx.author}")

    # ── !logset reset ─────────────────────────────────────────────────────
    @logset_group.command(name="reset", help="Reset seluruh konfigurasi log server ini.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def logset_reset(self, ctx):
        data = _load_log_config()
        data.pop(str(ctx.guild.id), None)
        _save_log_config(data)

        await ctx.send(embed=embed_utils.success(
            "Seluruh konfigurasi log server ini telah direset.",
            title="🔄 Log Config Di-reset"
        ))
        logger.info(f"LOGSET RESET | Guild {ctx.guild.id} oleh {ctx.author}")

    # EVENTS: Messages
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        content = message.content or "*(tidak ada teks — mungkin embed atau attachment)*"
        fields  = [
            ("Pengirim",  _fmt_user(message.author), False),
            ("Channel",   _fmt_channel(message.channel), False),
            ("Isi Pesan", content[:1020], False),
        ]
        if message.attachments:
            att_list = "\n".join(a.filename for a in message.attachments)
            fields.append(("Attachment", att_list, False))

        embed = _make_embed(
            "messages", "Pesan Dihapus",
            fields=fields,
            thumbnail_url=message.author.display_avatar.url,
        )
        await send_log(message.guild, "messages", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content:
            return   # edit embed/attachment tanpa ubah teks, abaikan

        before_content = before.content or "*(kosong)*"
        after_content  = after.content  or "*(kosong)*"

        fields = [
            ("Pengirim",       _fmt_user(before.author), False),
            ("Channel",        _fmt_channel(before.channel), False),
            ("Sebelum",        before_content[:1020], False),
            ("Sesudah",        after_content[:1020], False),
            ("Tautan Pesan",   f"[Klik di sini]({after.jump_url})", False),
        ]
        embed = _make_embed(
            "messages", "Pesan Diedit",
            fields=fields,
            thumbnail_url=before.author.display_avatar.url,
        )
        await send_log(before.guild, "messages", embed)

    # EVENTS: Members
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        created_at = discord.utils.format_dt(member.created_at, style="R")
        fields = [
            ("Member",        _fmt_user(member), False),
            ("Akun Dibuat",   created_at, True),
            ("Total Member",  str(member.guild.member_count), True),
        ]
        embed = _make_embed(
            "members", "Member Bergabung",
            fields=fields,
            thumbnail_url=member.display_avatar.url,
        )
        await send_log(member.guild, "members", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        joined_at = (
            discord.utils.format_dt(member.joined_at, style="R")
            if member.joined_at else "Tidak diketahui"
        )
        roles_list = ", ".join(r.mention for r in member.roles[1:]) or "*(tidak ada)*"
        fields = [
            ("Member",      _fmt_user(member), False),
            ("Bergabung",   joined_at, True),
            ("Role",        roles_list[:1020], False),
        ]
        embed = _make_embed(
            "members", "Member Keluar / Dikeluarkan",
            fields=fields,
            thumbnail_url=member.display_avatar.url,
        )
        await send_log(member.guild, "members", embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # Nickname berubah
        if before.nick != after.nick:
            fields = [
                ("Member",      _fmt_user(after), False),
                ("Nick Lama",   before.nick or "*(tidak ada)*", True),
                ("Nick Baru",   after.nick  or "*(tidak ada)*", True),
            ]
            embed = _make_embed(
                "members", "Nickname Berubah",
                fields=fields,
                thumbnail_url=after.display_avatar.url,
            )
            await send_log(after.guild, "members", embed)

        # Role member berubah — log di kategori "roles"
        added_roles   = [r for r in after.roles  if r not in before.roles]
        removed_roles = [r for r in before.roles if r not in after.roles]

        if added_roles or removed_roles:
            fields = [("Member", _fmt_user(after), False)]
            if added_roles:
                fields.append(("Role Ditambahkan", " ".join(r.mention for r in added_roles), False))
            if removed_roles:
                fields.append(("Role Dilepas", " ".join(r.mention for r in removed_roles), False))
            embed = _make_embed(
                "roles", "Role Member Berubah",
                fields=fields,
                thumbnail_url=after.display_avatar.url,
            )
            await send_log(after.guild, "roles", embed)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        # Username / avatar berubah — perlu iterasi semua guild karena User global
        if before.name == after.name and before.discriminator == after.discriminator:
            return
        for guild in self.bot.guilds:
            if guild.get_member(after.id):
                fields = [
                    ("User",        _fmt_user(after), False),
                    ("Username Lama", str(before), True),
                    ("Username Baru", str(after),  True),
                ]
                embed = _make_embed(
                    "members", "Username Berubah",
                    fields=fields,
                    thumbnail_url=after.display_avatar.url,
                )
                await send_log(guild, "members", embed)

    # EVENTS: Roles (role server dibuat / dihapus / diedit)
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        fields = [
            ("Role",   f"{role.mention} (`{role.name}` · ID: `{role.id}`)", False),
            ("Warna",  str(role.color), True),
            ("Posisi", str(role.position), True),
        ]
        embed = _make_embed("roles", "Role Dibuat", fields=fields)
        await send_log(role.guild, "roles", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        fields = [
            ("Role",   f"`{role.name}` (ID: `{role.id}`)", False),
            ("Warna",  str(role.color), True),
            ("Posisi", str(role.position), True),
        ]
        embed = _make_embed("roles", "Role Dihapus", fields=fields)
        await send_log(role.guild, "roles", embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        changes = []
        if before.name  != after.name:  changes.append(("Nama",  before.name,       after.name))
        if before.color != after.color: changes.append(("Warna", str(before.color), str(after.color)))
        if before.hoist != after.hoist: changes.append(("Hoist (tampil terpisah)", str(before.hoist), str(after.hoist)))
        if before.mentionable != after.mentionable:
            changes.append(("Mentionable", str(before.mentionable), str(after.mentionable)))
        if not changes:
            return

        fields = [("Role", f"{after.mention} (ID: `{after.id}`)", False)]
        for name, old, new in changes:
            fields.append((f"{name}: Lama → Baru", f"`{old}` → `{new}`", False))
        embed = _make_embed("roles", "Role Diedit", fields=fields)
        await send_log(after.guild, "roles", embed)

    # EVENTS: Channels
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        fields = [
            ("Channel",  _fmt_channel(channel), False),
            ("Tipe",     str(channel.type).replace("_", " ").title(), True),
            ("Kategori", channel.category.name if channel.category else "*(tidak ada)*", True),
        ]
        embed = _make_embed("channels", "Channel Dibuat", fields=fields)
        await send_log(channel.guild, "channels", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        fields = [
            ("Channel",  f"`#{channel.name}` (ID: `{channel.id}`)", False),
            ("Tipe",     str(channel.type).replace("_", " ").title(), True),
            ("Kategori", channel.category.name if channel.category else "*(tidak ada)*", True),
        ]
        embed = _make_embed("channels", "Channel Dihapus", fields=fields)
        await send_log(channel.guild, "channels", embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ):
        changes = []
        if before.name != after.name:
            changes.append(("Nama", before.name, after.name))

        # Text channel spesifik
        if isinstance(before, discord.TextChannel) and isinstance(after, discord.TextChannel):
            if before.topic != after.topic:
                changes.append(("Topic", before.topic or "*(kosong)*", after.topic or "*(kosong)*"))
            if before.slowmode_delay != after.slowmode_delay:
                changes.append((
                    "Slowmode",
                    f"{before.slowmode_delay}s",
                    f"{after.slowmode_delay}s"
                ))
            if before.nsfw != after.nsfw:
                changes.append(("NSFW", str(before.nsfw), str(after.nsfw)))

        if not changes:
            return

        fields = [("Channel", _fmt_channel(after), False)]
        for name, old, new in changes:
            fields.append((f"{name}: Lama → Baru", f"`{old}` → `{new}`", False))
        embed = _make_embed("channels", "Channel Diedit", fields=fields)
        await send_log(after.guild, "channels", embed)

    # EVENTS: Server
    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        changes = []
        if before.name != after.name:
            changes.append(("Nama Server", before.name, after.name))
        if before.icon != after.icon:
            changes.append(("Icon", "*(lama)*", "*(baru)*"))
        if before.verification_level != after.verification_level:
            changes.append(("Level Verifikasi", str(before.verification_level), str(after.verification_level)))
        if before.explicit_content_filter != after.explicit_content_filter:
            changes.append(("Filter Konten", str(before.explicit_content_filter), str(after.explicit_content_filter)))
        if before.default_notifications != after.default_notifications:
            changes.append(("Notifikasi Default", str(before.default_notifications), str(after.default_notifications)))
        if before.afk_channel != after.afk_channel:
            old_afk = before.afk_channel.name if before.afk_channel else "*(tidak ada)*"
            new_afk = after.afk_channel.name  if after.afk_channel  else "*(tidak ada)*"
            changes.append(("AFK Channel", old_afk, new_afk))

        if not changes:
            return

        fields = []
        for name, old, new in changes:
            fields.append((f"{name}: Lama → Baru", f"`{old}` → `{new}`", False))

        embed = _make_embed(
            "server", "Pengaturan Server Berubah",
            fields=fields,
            thumbnail_url=after.icon.url if after.icon else None,
        )
        await send_log(after, "server", embed)

    # EVENTS: Voice
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if before.channel == after.channel:
            return   # mute/deaf saja, tidak perlu dilog

        if before.channel is None:
            # Join voice
            fields = [
                ("Member",  _fmt_user(member), False),
                ("Channel", _fmt_channel(after.channel), False),
            ]
            embed = _make_embed(
                "voice", "Join Voice Channel",
                fields=fields,
                thumbnail_url=member.display_avatar.url,
            )
        elif after.channel is None:
            # Leave voice
            fields = [
                ("Member",  _fmt_user(member), False),
                ("Channel", _fmt_channel(before.channel), False),
            ]
            embed = _make_embed(
                "voice", "Leave Voice Channel",
                fields=fields,
                thumbnail_url=member.display_avatar.url,
            )
        else:
            # Pindah antar voice channel
            fields = [
                ("Member", _fmt_user(member), False),
                ("Dari",   _fmt_channel(before.channel), True),
                ("Ke",     _fmt_channel(after.channel),  True),
            ]
            embed = _make_embed(
                "voice", "Pindah Voice Channel",
                fields=fields,
                thumbnail_url=member.display_avatar.url,
            )

        await send_log(member.guild, "voice", embed)

    # Error handler
    @logset_group.error
    async def logset_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=embed_utils.error(
                "Hanya **Administrator** server yang bisa mengubah konfigurasi log."
            ))
        elif isinstance(error, commands.ChannelNotFound):
            await ctx.send(embed=embed_utils.error("Channel tidak ditemukan."))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=embed_utils.error(
                f"Argumen kurang. Gunakan `!logset` untuk melihat panduan."
            ))
        else:
            logger.error(f"Error pada {ctx.command}: {error}")
            await ctx.send(embed=embed_utils.error(f"Terjadi error: `{error}`"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Logging(bot))