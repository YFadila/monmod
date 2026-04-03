"""
Cog: Moderasi
Semua perintah moderasi server.
"""

import datetime
import logging
import os

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("discord_bot")


class Moderation(commands.Cog, name="Moderasi"):
    """Perintah-perintah moderasi server."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_log(self, guild: discord.Guild, embed: discord.Embed):
        """Kirim log ke channel log moderasi jika dikonfigurasi."""
        log_channel_id = os.getenv("LOG_CHANNEL_ID")
        if log_channel_id:
            channel = guild.get_channel(int(log_channel_id))
            if channel:
                await channel.send(embed=embed)

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
        if durasi < 1 or durasi > 40320:  # max 28 hari
            return await ctx.send(embed=embeds.error("Durasi timeout harus antara 1 menit – 40320 menit (28 hari)."))

        until = discord.utils.utcnow() + datetime.timedelta(minutes=durasi)
        await member.timeout(until, reason=alasan)
        embed = embeds.mod_action(
            f"⏱️ Timeout {durasi} Menit", member, ctx.author, alasan, discord.Color.yellow()
        )
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

    @commands.command(name="warn", help="Beri peringatan ke member (dikirim via DM).")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def warn(self, ctx, member: discord.Member, *, alasan: str = "Tidak ada alasan."):
        try:
            dm_embed = embeds.warning(
                f"Kamu mendapat peringatan di **{ctx.guild.name}**.\n**Alasan:** {alasan}",
                title="⚠️ Peringatan"
            )
            await member.send(embed=dm_embed)
            dm_status = "📨 DM terkirim"
        except discord.Forbidden:
            dm_status = "⚠️ DM diblokir"

        embed = embeds.mod_action("⚠️ Member Diperingatkan", member, ctx.author, alasan, discord.Color.gold())
        embed.add_field(name="Status", value=dm_status, inline=False)
        await ctx.send(embed=embed)
        await self.send_log(ctx.guild, embed)
        logger.info(f"WARN | {member} oleh {ctx.author} | Alasan: {alasan}")

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

    @kick.error
    @ban.error
    @timeout.error
    @warn.error
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


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
