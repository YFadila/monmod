import json
import logging
import uuid
from pathlib import Path

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("discord_bot")

ROLES_FILE = Path("data/roles.json")
MAX_BUTTONS_PER_PANEL = 25   # batas Discord: 5 baris × 5 tombol


# Helper I/O
def _load_roles() -> dict:
    try:
        if ROLES_FILE.exists():
            with open(ROLES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Gagal membaca roles.json: {e}")
    return {}


def _save_roles(data: dict) -> None:
    ROLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(ROLES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"Gagal menyimpan roles.json: {e}")


def _guild_data(data: dict, guild_id: int) -> dict:
    return data.setdefault(str(guild_id), {"auto_roles": [], "reaction_panels": {}})


# Persistent Button View untuk satu panel
class RoleButton(discord.ui.Button):
    """Satu tombol = satu role (toggle: tambah jika belum punya, lepas jika sudah)."""

    def __init__(self, role_id: int, label: str, emoji: str | None):
        # custom_id harus unik dan statis agar persistent setelah restart
        super().__init__(
            label=label,
            emoji=emoji or None,
            custom_id=f"role_btn:{role_id}",
            style=discord.ButtonStyle.secondary,
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            return await interaction.response.send_message(
                "❌ Role tidak ditemukan. Mungkin sudah dihapus dari server.",
                ephemeral=True
            )

        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason="Reaction role (button)")
            await interaction.response.send_message(
                f"✅ Role **{role.name}** berhasil dilepas.", ephemeral=True
            )
        else:
            await interaction.user.add_roles(role, reason="Reaction role (button)")
            await interaction.response.send_message(
                f"✅ Role **{role.name}** berhasil ditambahkan.", ephemeral=True
            )


class RolePanelView(discord.ui.View):
    """View persisten untuk satu panel reaction role."""

    def __init__(self, panel_roles: list[dict]):
        # timeout=None agar view tidak expired
        super().__init__(timeout=None)
        for r in panel_roles:
            self.add_item(RoleButton(
                role_id=r["role_id"],
                label=r.get("label", "Role"),
                emoji=r.get("emoji"),
            ))


# Cog
class Roles(commands.Cog, name="Roles"):
    """Sistem Auto Role dan Reaction Role berbasis button."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """Pasang ulang semua persistent view saat bot (re)start."""
        await self._restore_views()

    async def _restore_views(self):
        """
        Iterasi semua panel di semua guild, daftarkan kembali RolePanelView
        ke bot agar tombol tetap berfungsi setelah restart.
        """
        data    = _load_roles()
        count   = 0
        for guild_data in data.values():
            for panel in guild_data.get("reaction_panels", {}).values():
                if panel.get("message_id") and panel.get("roles"):
                    view = RolePanelView(panel["roles"])
                    self.bot.add_view(view, message_id=panel["message_id"])
                    count += 1
        logger.info(f"ROLES | {count} panel view dipulihkan.")

    # ── Helper internal ────────────────────────────────────────────────────
    def _build_panel_embed(self, panel: dict, guild: discord.Guild) -> discord.Embed:
        """Buat embed untuk pesan panel reaction role."""
        embed = discord.Embed(
            title=f"🎭 {panel['name']}",
            description=panel.get("description") or "Klik tombol di bawah untuk mendapatkan atau melepas role.",
            color=discord.Color.blurple(),
        )
        if panel.get("roles"):
            role_lines = []
            for r in panel["roles"]:
                role = guild.get_role(r["role_id"])
                emoji = r.get("emoji", "")
                name  = role.mention if role else f"~~{r.get('label', '?')}~~ *(dihapus)*"
                role_lines.append(f"{emoji} {name}".strip())
            embed.add_field(name="Role tersedia", value="\n".join(role_lines), inline=False)
        embed.set_footer(text="Klik tombol untuk toggle role • Bisa dipilih lebih dari satu")
        return embed

    # EVENT: on_member_join — auto role
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        data       = _load_roles()
        guild_data = data.get(str(member.guild.id), {})
        auto_roles = guild_data.get("auto_roles", [])

        if not auto_roles:
            return

        roles_to_add = []
        for role_id in auto_roles:
            role = member.guild.get_role(role_id)
            if role:
                roles_to_add.append(role)
            else:
                logger.warning(f"AUTO-ROLE | Role {role_id} tidak ditemukan di guild {member.guild.id}")

        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Auto role saat join")
                logger.info(
                    f"AUTO-ROLE | {member} mendapat {len(roles_to_add)} role "
                    f"di guild {member.guild.id}"
                )
            except discord.Forbidden:
                logger.error(
                    f"AUTO-ROLE | Gagal memberi role ke {member} — bot kurang izin "
                    f"atau role berada di atas role bot."
                )

    # GRUP PERINTAH: autorole
    @commands.group(
        name="autorole",
        invoke_without_command=True,
        help="Kelola auto role saat member join."
    )
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def autorole_group(self, ctx):
        embed = discord.Embed(
            title="⚙️ Perintah Auto Role",
            color=discord.Color.blurple(),
            description="Role yang didaftarkan akan otomatis diberikan ke member yang baru join."
        )
        embed.add_field(
            name="Sub-perintah",
            value=(
                "`!autorole list` — Lihat daftar auto role aktif\n"
                "`!autorole add <@role>` — Tambah role ke daftar auto role\n"
                "`!autorole remove <@role>` — Hapus role dari daftar auto role\n"
                "`!autorole clear` — Hapus semua auto role\n"
            ),
            inline=False
        )
        await ctx.send(embed=embed)

    # ── !autorole list ────────────────────────────────────────────────────
    @autorole_group.command(name="list", help="Lihat daftar auto role aktif. Contoh: !autorole list")
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def autorole_list(self, ctx):
        data       = _load_roles()
        guild_data = _guild_data(data, ctx.guild.id)
        auto_roles = guild_data.get("auto_roles", [])

        if not auto_roles:
            return await ctx.send(embed=embeds.success(
                "Belum ada auto role yang didaftarkan.",
                title="📋 Auto Role"
            ))

        lines = []
        for role_id in auto_roles:
            role = ctx.guild.get_role(role_id)
            lines.append(role.mention if role else f"~~{role_id}~~ *(role dihapus)*")

        embed = discord.Embed(
            title="📋 Auto Role Aktif",
            description="\n".join(lines),
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Total: {len(auto_roles)} role")
        await ctx.send(embed=embed)

    # ── !autorole add <@role> ─────────────────────────────────────────────
    @autorole_group.command(name="add", help="Tambah role ke daftar auto role. Contoh: !autorole add @Member")
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def autorole_add(self, ctx, role: discord.Role):
        # Cegah role berbahaya
        if role.permissions.administrator:
            return await ctx.send(embed=embeds.error(
                "Tidak bisa mendaftarkan role dengan permission **Administrator** sebagai auto role."
            ))
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=embeds.error(
                "Role tersebut berada di atas atau sejajar dengan role bot. "
                "Bot tidak bisa memberikan role yang lebih tinggi dari dirinya sendiri."
            ))

        data       = _load_roles()
        guild_data = _guild_data(data, ctx.guild.id)

        if role.id in guild_data["auto_roles"]:
            return await ctx.send(embed=embeds.error(
                f"{role.mention} sudah ada di daftar auto role."
            ))

        guild_data["auto_roles"].append(role.id)
        _save_roles(data)

        await ctx.send(embed=embeds.success(
            f"{role.mention} ditambahkan ke daftar auto role.\n"
            f"Member yang join setelah ini akan otomatis mendapat role ini.",
            title="✅ Auto Role Ditambahkan"
        ))
        logger.info(f"AUTOROLE ADD | {role} di guild {ctx.guild.id} oleh {ctx.author}")

    # ── !autorole remove <@role> ──────────────────────────────────────────
    @autorole_group.command(name="remove", help="Hapus role dari daftar auto role. Contoh: !autorole remove @Member")
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def autorole_remove(self, ctx, role: discord.Role):
        data       = _load_roles()
        guild_data = _guild_data(data, ctx.guild.id)

        if role.id not in guild_data["auto_roles"]:
            return await ctx.send(embed=embeds.error(
                f"{role.mention} tidak ada di daftar auto role."
            ))

        guild_data["auto_roles"].remove(role.id)
        _save_roles(data)

        await ctx.send(embed=embeds.success(
            f"{role.mention} dihapus dari daftar auto role.",
            title="🗑️ Auto Role Dihapus"
        ))
        logger.info(f"AUTOROLE REMOVE | {role} di guild {ctx.guild.id} oleh {ctx.author}")

    # ── !autorole clear ───────────────────────────────────────────────────
    @autorole_group.command(name="clear", help="Hapus semua auto role. Contoh: !autorole clear")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def autorole_clear(self, ctx):
        data       = _load_roles()
        guild_data = _guild_data(data, ctx.guild.id)

        if not guild_data["auto_roles"]:
            return await ctx.send(embed=embeds.success(
                "Tidak ada auto role yang perlu dihapus.",
                title="📋 Auto Role"
            ))

        jumlah = len(guild_data["auto_roles"])
        guild_data["auto_roles"] = []
        _save_roles(data)

        await ctx.send(embed=embeds.success(
            f"**{jumlah}** auto role berhasil dihapus.",
            title="🧹 Auto Role Di-reset"
        ))
        logger.info(f"AUTOROLE CLEAR | Guild {ctx.guild.id} oleh {ctx.author}")

    # GRUP PERINTAH: panel  (reaction role)
    @commands.group(
        name="panel",
        invoke_without_command=True,
        help="Kelola panel reaction role berbasis button."
    )
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def panel_group(self, ctx):
        embed = discord.Embed(
            title="⚙️ Perintah Panel Reaction Role",
            color=discord.Color.blurple(),
            description=(
                "Panel adalah pesan embed berisi tombol-tombol role.\n"
                "Member klik tombol → dapat role (klik lagi → lepas role)."
            )
        )
        embed.add_field(
            name="Sub-perintah",
            value=(
                "`!panel list` — Lihat semua panel\n"
                "`!panel create <nama>` — Buat panel baru\n"
                "`!panel desc <panel_id> <deskripsi>` — Atur deskripsi panel\n"
                "`!panel addrole <panel_id> <@role> <label> [emoji]` — Tambah role ke panel\n"
                "`!panel removerole <panel_id> <@role>` — Hapus role dari panel\n"
                "`!panel send <panel_id> [#channel]` — Kirim/perbarui panel ke channel\n"
                "`!panel delete <panel_id>` — Hapus panel permanen\n"
            ),
            inline=False
        )
        embed.add_field(
            name="💡 Alur kerja",
            value=(
                "1. `!panel create Game` — buat panel\n"
                "2. `!panel addrole <id> @Valorant Valorant 🎯` — tambah role\n"
                "3. `!panel send <id> #role-picker` — kirim ke channel"
            ),
            inline=False
        )
        await ctx.send(embed=embed)

    # ── !panel list ───────────────────────────────────────────────────────
    @panel_group.command(name="list", help="Lihat semua panel reaction role. Contoh: !panel list")
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def panel_list(self, ctx):
        data    = _load_roles()
        panels  = _guild_data(data, ctx.guild.id).get("reaction_panels", {})

        if not panels:
            return await ctx.send(embed=embeds.success(
                "Belum ada panel reaction role. Gunakan `!panel create <nama>` untuk membuat.",
                title="📋 Panel Reaction Role"
            ))

        embed = discord.Embed(
            title="📋 Panel Reaction Role",
            color=discord.Color.blurple(),
        )
        for panel_id, panel in panels.items():
            channel = ctx.guild.get_channel(panel.get("channel_id", 0))
            status  = (
                f"📨 Terkirim di {channel.mention}" if channel and panel.get("message_id")
                else "⏳ Belum dikirim"
            )
            role_count = len(panel.get("roles", []))
            embed.add_field(
                name=f"🎭 {panel['name']}",
                value=(
                    f"**ID:** `{panel_id}`\n"
                    f"**Role:** {role_count} tombol\n"
                    f"**Status:** {status}"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)

    # ── !panel create <nama> ──────────────────────────────────────────────
    @panel_group.command(name="create", help="Buat panel reaction role baru. Contoh: !panel create Game")
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def panel_create(self, ctx, *, nama: str):
        if len(nama) > 50:
            return await ctx.send(embed=embeds.error("Nama panel maksimal 50 karakter."))

        data       = _load_roles()
        guild_data = _guild_data(data, ctx.guild.id)
        panels     = guild_data.setdefault("reaction_panels", {})

        # Cek nama duplikat
        if any(p["name"].lower() == nama.lower() for p in panels.values()):
            return await ctx.send(embed=embeds.error(
                f"Panel dengan nama **{nama}** sudah ada."
            ))

        panel_id = str(uuid.uuid4())[:8]   # ID pendek 8 karakter
        panels[panel_id] = {
            "name":        nama,
            "description": None,
            "channel_id":  None,
            "message_id":  None,
            "roles":       [],
        }
        _save_roles(data)

        await ctx.send(embed=embeds.success(
            f"Panel **{nama}** berhasil dibuat dengan ID `{panel_id}`.\n\n"
            f"Langkah selanjutnya:\n"
            f"• `!panel addrole {panel_id} @role Label emoji` — tambah role\n"
            f"• `!panel send {panel_id} #channel` — kirim ke channel",
            title="✅ Panel Dibuat"
        ))
        logger.info(f"PANEL CREATE | '{nama}' [{panel_id}] di guild {ctx.guild.id} oleh {ctx.author}")

    # ── !panel desc <panel_id> <deskripsi> ───────────────────────────────
    @panel_group.command(name="desc", help="Atur deskripsi panel. Contoh: !panel desc abc12345 Pilih role gamemu!")
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def panel_desc(self, ctx, panel_id: str, *, deskripsi: str):
        data       = _load_roles()
        guild_data = _guild_data(data, ctx.guild.id)
        panel      = guild_data.get("reaction_panels", {}).get(panel_id)

        if not panel:
            return await ctx.send(embed=embeds.error(
                f"Panel `{panel_id}` tidak ditemukan. Gunakan `!panel list` untuk melihat ID."
            ))

        panel["description"] = deskripsi[:300]
        _save_roles(data)

        await ctx.send(embed=embeds.success(
            f"Deskripsi panel **{panel['name']}** diperbarui.\n"
            f"Gunakan `!panel send {panel_id}` untuk memperbarui pesan panel.",
            title="✅ Deskripsi Diperbarui"
        ))

    # ── !panel addrole <panel_id> <@role> <label> [emoji] ────────────────
    @panel_group.command(
        name="addrole",
        help="Tambah role ke panel. Contoh: !panel addrole abc12345 @Valorant Valorant 🎯"
    )
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def panel_addrole(self, ctx, panel_id: str, role: discord.Role, label: str, emoji: str = None):
        # Validasi role
        if role.permissions.administrator:
            return await ctx.send(embed=embeds.error(
                "Tidak bisa menambahkan role **Administrator** ke panel reaction role."
            ))
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=embeds.error(
                "Role tersebut berada di atas role bot. Bot tidak bisa memberikannya."
            ))

        data       = _load_roles()
        guild_data = _guild_data(data, ctx.guild.id)
        panel      = guild_data.get("reaction_panels", {}).get(panel_id)

        if not panel:
            return await ctx.send(embed=embeds.error(
                f"Panel `{panel_id}` tidak ditemukan."
            ))
        if len(panel["roles"]) >= MAX_BUTTONS_PER_PANEL:
            return await ctx.send(embed=embeds.error(
                f"Panel sudah mencapai batas maksimum **{MAX_BUTTONS_PER_PANEL}** tombol."
            ))
        if any(r["role_id"] == role.id for r in panel["roles"]):
            return await ctx.send(embed=embeds.error(
                f"{role.mention} sudah ada di panel ini."
            ))

        panel["roles"].append({
            "role_id": role.id,
            "label":   label[:80],   # batas label Discord
            "emoji":   emoji,
        })
        _save_roles(data)

        await ctx.send(embed=embeds.success(
            f"Role {role.mention} ditambahkan ke panel **{panel['name']}**.\n"
            f"Total tombol: **{len(panel['roles'])}**\n"
            f"Gunakan `!panel send {panel_id}` untuk memperbarui pesan panel.",
            title="✅ Role Ditambahkan ke Panel"
        ))
        logger.info(f"PANEL ADDROLE | {role} → panel [{panel_id}] guild {ctx.guild.id} oleh {ctx.author}")

    # ── !panel removerole <panel_id> <@role> ─────────────────────────────
    @panel_group.command(name="removerole", help="Hapus role dari panel. Contoh: !panel removerole abc12345 @Valorant")
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def panel_removerole(self, ctx, panel_id: str, role: discord.Role):
        data       = _load_roles()
        guild_data = _guild_data(data, ctx.guild.id)
        panel      = guild_data.get("reaction_panels", {}).get(panel_id)

        if not panel:
            return await ctx.send(embed=embeds.error(f"Panel `{panel_id}` tidak ditemukan."))

        before = len(panel["roles"])
        panel["roles"] = [r for r in panel["roles"] if r["role_id"] != role.id]

        if len(panel["roles"]) == before:
            return await ctx.send(embed=embeds.error(
                f"{role.mention} tidak ditemukan di panel ini."
            ))

        _save_roles(data)

        await ctx.send(embed=embeds.success(
            f"Role {role.mention} dihapus dari panel **{panel['name']}**.\n"
            f"Gunakan `!panel send {panel_id}` untuk memperbarui pesan panel.",
            title="🗑️ Role Dihapus dari Panel"
        ))
        logger.info(f"PANEL REMOVEROLE | {role} ← panel [{panel_id}] guild {ctx.guild.id} oleh {ctx.author}")

    # ── !panel send <panel_id> [#channel] ─────────────────────────────────
    @panel_group.command(
        name="send",
        help=(
            "Kirim atau perbarui panel ke channel. "
            "Contoh: !panel send abc12345 #role-picker  "
            "Jika panel sudah dikirim sebelumnya, pesan lama diperbarui (tidak perlu sebut channel lagi)."
        )
    )
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def panel_send(self, ctx, panel_id: str, channel: discord.TextChannel = None):
        data       = _load_roles()
        guild_data = _guild_data(data, ctx.guild.id)
        panel      = guild_data.get("reaction_panels", {}).get(panel_id)

        if not panel:
            return await ctx.send(embed=embeds.error(f"Panel `{panel_id}` tidak ditemukan."))
        if not panel["roles"]:
            return await ctx.send(embed=embeds.error(
                "Panel belum punya role. Tambahkan dulu dengan `!panel addrole`."
            ))

        # Tentukan channel target
        target_channel = channel
        if not target_channel and panel.get("channel_id"):
            target_channel = ctx.guild.get_channel(panel["channel_id"])
        if not target_channel:
            return await ctx.send(embed=embeds.error(
                "Sebutkan channel tujuan: `!panel send {panel_id} #channel`"
            ))

        panel_embed = self._build_panel_embed(panel, ctx.guild)
        view        = RolePanelView(panel["roles"])

        # Coba edit pesan lama jika sudah pernah dikirim di channel yang sama
        existing_msg = None
        if panel.get("message_id") and panel.get("channel_id") == target_channel.id:
            try:
                existing_msg = await target_channel.fetch_message(panel["message_id"])
            except (discord.NotFound, discord.HTTPException):
                existing_msg = None

        if existing_msg:
            await existing_msg.edit(embed=panel_embed, view=view)
            self.bot.add_view(view, message_id=existing_msg.id)
            await ctx.send(embed=embeds.success(
                f"Panel **{panel['name']}** diperbarui di {target_channel.mention}.",
                title="✅ Panel Diperbarui"
            ))
        else:
            # Kirim pesan baru
            msg = await target_channel.send(embed=panel_embed, view=view)
            self.bot.add_view(view, message_id=msg.id)
            panel["channel_id"] = target_channel.id
            panel["message_id"] = msg.id
            _save_roles(data)
            await ctx.send(embed=embeds.success(
                f"Panel **{panel['name']}** berhasil dikirim ke {target_channel.mention}.",
                title="✅ Panel Dikirim"
            ))

        logger.info(
            f"PANEL SEND | [{panel_id}] '{panel['name']}' → "
            f"#{target_channel.name} guild {ctx.guild.id} oleh {ctx.author}"
        )

    # ── !panel delete <panel_id> ──────────────────────────────────────────
    @panel_group.command(name="delete", help="Hapus panel permanen (termasuk pesannya). Contoh: !panel delete abc12345")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def panel_delete(self, ctx, panel_id: str):
        data       = _load_roles()
        guild_data = _guild_data(data, ctx.guild.id)
        panels     = guild_data.get("reaction_panels", {})

        if panel_id not in panels:
            return await ctx.send(embed=embeds.error(f"Panel `{panel_id}` tidak ditemukan."))

        panel = panels.pop(panel_id)
        _save_roles(data)

        # Coba hapus pesan panel dari Discord
        if panel.get("channel_id") and panel.get("message_id"):
            ch = ctx.guild.get_channel(panel["channel_id"])
            if ch:
                try:
                    msg = await ch.fetch_message(panel["message_id"])
                    await msg.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass

        await ctx.send(embed=embeds.success(
            f"Panel **{panel['name']}** (`{panel_id}`) berhasil dihapus.",
            title="🗑️ Panel Dihapus"
        ))
        logger.info(f"PANEL DELETE | [{panel_id}] '{panel['name']}' guild {ctx.guild.id} oleh {ctx.author}")

    # Error handler
    @autorole_group.error
    @panel_group.error
    async def roles_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=embeds.error("Kamu tidak punya izin untuk perintah ini."))
        elif isinstance(error, commands.RoleNotFound):
            await ctx.send(embed=embeds.error("Role tidak ditemukan. Pastikan kamu mention role dengan benar."))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=embeds.error(
                f"Argumen kurang. Gunakan `!{ctx.command.qualified_name}` dengan benar."
            ))
        else:
            logger.error(f"Error pada {ctx.command}: {error}")
            await ctx.send(embed=embeds.error(f"Terjadi error: `{error}`"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Roles(bot))