import json
import logging
import os
from pathlib import Path

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("discord_bot")

PREFIX_FILE     = Path("data/prefixes.json")
DEFAULT_PREFIX  = os.getenv("BOT_PREFIX", "!")
MAX_PREFIX_LEN  = 10   # batas panjang prefix agar tidak disalahgunakan


# Helper I/O
def _load_prefixes() -> dict:
    try:
        if PREFIX_FILE.exists():
            with open(PREFIX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Gagal membaca prefixes.json: {e}")
    return {}


def _save_prefixes(data: dict) -> None:
    PREFIX_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(PREFIX_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"Gagal menyimpan prefixes.json: {e}")


# Fungsi utama — daftarkan ini ke bot di main.py
def get_prefix(bot: commands.Bot, message: discord.Message) -> list[str]:
    """
    Callable prefix untuk discord.py.
    Kembalikan list prefix yang berlaku untuk pesan ini:
      1. Prefix custom guild (jika ada)
      2. Prefix default dari .env / fallback "!"
      3. Mention bot (@BotName) — selalu aktif sebagai fallback darurat
    """
    # DM tidak punya guild → pakai default saja
    if not message.guild:
        return commands.when_mentioned_or(DEFAULT_PREFIX)(bot, message)

    data   = _load_prefixes()
    prefix = data.get(str(message.guild.id), DEFAULT_PREFIX)
    return commands.when_mentioned_or(prefix)(bot, message)


# Cog
class Prefix(commands.Cog, name="Prefix"):
    """Kelola prefix bot untuk server ini."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Helper: ambil prefix aktif guild ──────────────────────────────────
    def _get_guild_prefix(self, guild_id: int) -> str:
        data = _load_prefixes()
        return data.get(str(guild_id), DEFAULT_PREFIX)

    # PERINTAH: setprefix
    @commands.command(
        name="setprefix",
        help="Ganti prefix bot untuk server ini. Contoh: setprefix ??"
    )
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def setprefix(self, ctx, prefix: str):
        # Validasi panjang
        if len(prefix) > MAX_PREFIX_LEN:
            return await ctx.send(embed=embeds.error(
                f"Prefix terlalu panjang. Maksimum **{MAX_PREFIX_LEN}** karakter."
            ))

        # Tolak spasi di awal/akhir yang tidak disengaja
        if prefix != prefix.strip():
            return await ctx.send(embed=embeds.error(
                "Prefix tidak boleh diawali atau diakhiri dengan spasi."
            ))

        # Tolak prefix yang sama dengan default agar tidak menumpuk entri
        data = _load_prefixes()
        if prefix == DEFAULT_PREFIX:
            # Jika sama dengan default, hapus entri custom (kembali ke default)
            data.pop(str(ctx.guild.id), None)
            _save_prefixes(data)
            return await ctx.send(embed=embeds.success(
                f"Prefix dikembalikan ke default: `{DEFAULT_PREFIX}`",
                title="✅ Prefix Diperbarui"
            ))

        old_prefix = data.get(str(ctx.guild.id), DEFAULT_PREFIX)
        data[str(ctx.guild.id)] = prefix
        _save_prefixes(data)

        embed = embeds.success(
            f"Prefix server ini diubah dari `{old_prefix}` → `{prefix}`\n\n"
            f"Contoh penggunaan: `{prefix}help`, `{prefix}warn @user`\n\n"
            f"💡 *Kamu juga bisa selalu pakai mention bot sebagai prefix darurat.*",
            title="✅ Prefix Diperbarui"
        )
        embed.set_footer(text=f"Diubah oleh: {ctx.author}")
        await ctx.send(embed=embed)
        logger.info(f"SETPREFIX | Guild {ctx.guild.id} | '{old_prefix}' → '{prefix}' oleh {ctx.author}")

    # PERINTAH: resetprefix
    @commands.command(
        name="resetprefix",
        help="Kembalikan prefix server ini ke default."
    )
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def resetprefix(self, ctx):
        data = _load_prefixes()
        gk   = str(ctx.guild.id)

        if gk not in data:
            return await ctx.send(embed=embeds.success(
                f"Server ini sudah menggunakan prefix default: `{DEFAULT_PREFIX}`",
                title="ℹ️ Prefix"
            ))

        data.pop(gk)
        _save_prefixes(data)

        await ctx.send(embed=embeds.success(
            f"Prefix dikembalikan ke default: `{DEFAULT_PREFIX}`",
            title="🔄 Prefix Di-reset"
        ))
        logger.info(f"RESETPREFIX | Guild {ctx.guild.id} oleh {ctx.author}")

    # PERINTAH: prefix  (info — bisa dipakai semua user)
    @commands.command(
        name="prefix",
        help="Lihat prefix aktif bot di server ini."
    )
    @commands.guild_only()
    async def prefix_info(self, ctx):
        current = self._get_guild_prefix(ctx.guild.id)
        is_default = current == DEFAULT_PREFIX

        embed = discord.Embed(
            title="🔧 Prefix Bot",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Prefix aktif",
            value=f"`{current}`{'  *(default)*' if is_default else '  *(custom)*'}",
            inline=False
        )
        embed.add_field(
            name="Prefix darurat",
            value=f"{self.bot.user.mention} <perintah>",
            inline=False
        )
        if not is_default:
            embed.add_field(
                name="Prefix default",
                value=f"`{DEFAULT_PREFIX}` *(gunakan `{current}resetprefix` untuk kembali)*",
                inline=False
            )
        embed.set_footer(text="Hanya Administrator yang dapat mengubah prefix.")
        await ctx.send(embed=embed)

    # Error handler
    @setprefix.error
    @resetprefix.error
    async def prefix_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=embeds.error(
                "Hanya **Administrator** server yang bisa mengubah prefix bot."
            ))
        elif isinstance(error, commands.MissingRequiredArgument):
            current = self._get_guild_prefix(ctx.guild.id)
            await ctx.send(embed=embeds.error(
                f"Argumen kurang. Contoh: `{current}setprefix ??`"
            ))
        else:
            logger.error(f"Error pada {ctx.command}: {error}")
            await ctx.send(embed=embeds.error(f"Terjadi error: `{error}`"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Prefix(bot))