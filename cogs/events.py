"""
Cog: Events
Event listener untuk bot (on_ready, on_member_join, dll).
"""

import datetime
import logging
import os

import discord
from discord.ext import commands

logger = logging.getLogger("discord_bot")


class Events(commands.Cog, name="Events"):
    """Event listener bot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        prefix = os.getenv("BOT_PREFIX", "!")
        guilds = len(self.bot.guilds)
        logger.info(f"Bot aktif sebagai {self.bot.user} | {guilds} server | Prefix: {prefix}")

        await self.bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{guilds} server | {prefix}help",
            )
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        channel = member.guild.system_channel
        if channel:
            embed = discord.Embed(
                title="👋 Member Baru!",
                description=(
                    f"Selamat datang {member.mention} di **{member.guild.name}**!\n"
                    f"Kamu adalah member ke-**{member.guild.member_count}**."
                ),
                color=discord.Color.green(),
                timestamp=datetime.datetime.utcnow(),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)
        logger.info(f"JOIN | {member} bergabung ke {member.guild.name}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        channel = member.guild.system_channel
        if channel:
            embed = discord.Embed(
                title="🚶 Member Keluar",
                description=f"**{member}** telah meninggalkan server.",
                color=discord.Color.red(),
                timestamp=datetime.datetime.utcnow(),
            )
            await channel.send(embed=embed)
        logger.info(f"LEAVE | {member} keluar dari {member.guild.name}")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Global error handler."""
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.NoPrivateMessage):
            return await ctx.send("❌ Perintah ini hanya bisa digunakan di server.")
        if isinstance(error, commands.CheckFailure):
            return
        logger.warning(f"Unhandled error di {ctx.command}: {error}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))
