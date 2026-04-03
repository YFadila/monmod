"""
Cog: Info
Perintah informasi server dan member.
"""

import datetime

import discord
from discord.ext import commands

from utils import embeds


class Info(commands.Cog, name="Info"):
    """Perintah informasi server & member."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="userinfo", aliases=["ui", "whois"], help="Tampilkan info member.")
    @commands.guild_only()
    async def userinfo(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        roles = [r.mention for r in reversed(member.roles) if r != ctx.guild.default_role]

        embed = discord.Embed(
            title=f"👤 {member}",
            color=member.color if member.color != discord.Color.default() else discord.Color.blurple(),
            timestamp=datetime.datetime.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="Nickname", value=member.nick or "—", inline=True)
        embed.add_field(name="Bot?", value="✅ Ya" if member.bot else "❌ Tidak", inline=True)
        embed.add_field(
            name="Bergabung Server",
            value=f"<t:{int(member.joined_at.timestamp())}:R>",
            inline=True,
        )
        embed.add_field(
            name="Akun Dibuat",
            value=f"<t:{int(member.created_at.timestamp())}:R>",
            inline=True,
        )
        embed.add_field(
            name=f"Roles ({len(roles)})",
            value=" ".join(roles[:10]) + ("..." if len(roles) > 10 else "") if roles else "—",
            inline=False,
        )
        embed.set_footer(text=f"Diminta oleh {ctx.author}")
        await ctx.send(embed=embed)

    @commands.command(name="serverinfo", aliases=["si", "server"], help="Tampilkan info server.")
    @commands.guild_only()
    async def serverinfo(self, ctx):
        guild = ctx.guild
        bots = sum(1 for m in guild.members if m.bot)
        humans = guild.member_count - bots

        embed = discord.Embed(
            title=f"🏠 {guild.name}",
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.utcnow(),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            embed.set_image(url=guild.banner.url)

        embed.add_field(name="Owner", value=guild.owner.mention, inline=True)
        embed.add_field(name="ID", value=f"`{guild.id}`", inline=True)
        embed.add_field(
            name="Dibuat",
            value=f"<t:{int(guild.created_at.timestamp())}:R>",
            inline=True,
        )
        embed.add_field(name="👥 Member", value=f"{humans} manusia + {bots} bot", inline=True)
        embed.add_field(name="💬 Channel", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="🏷️ Role", value=str(len(guild.roles)), inline=True)
        embed.add_field(name="Boost Level", value=f"Level {guild.premium_tier} ({guild.premium_subscription_count} boost)", inline=False)
        embed.set_footer(text=f"Diminta oleh {ctx.author}")
        await ctx.send(embed=embed)

    @commands.command(name="avatar", aliases=["av"], help="Tampilkan avatar member.")
    @commands.guild_only()
    async def avatar(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=f"🖼️ Avatar {member}", color=discord.Color.blurple())
        embed.set_image(url=member.display_avatar.url)
        embed.set_footer(text=f"Diminta oleh {ctx.author}")
        await ctx.send(embed=embed)

    @commands.command(name="ping", help="Cek latensi bot.")
    async def ping(self, ctx):
        latency = round(self.bot.latency * 1000)
        color = discord.Color.green() if latency < 100 else discord.Color.orange() if latency < 200 else discord.Color.red()
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Latensi: **{latency}ms**",
            color=color,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
