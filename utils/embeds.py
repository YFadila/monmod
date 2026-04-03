"""
Helper untuk membuat embed Discord yang konsisten.
"""

import datetime
import discord


def success(description: str, title: str = None) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=discord.Color.green(),
        timestamp=datetime.datetime.utcnow(),
    )


def error(description: str, title: str = "❌ Error") -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=discord.Color.red(),
        timestamp=datetime.datetime.utcnow(),
    )


def warning(description: str, title: str = None) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=discord.Color.orange(),
        timestamp=datetime.datetime.utcnow(),
    )


def info(description: str, title: str = None) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.utcnow(),
    )


def mod_action(
    title: str,
    target: discord.Member,
    moderator: discord.Member,
    alasan: str,
    color: discord.Color = discord.Color.orange(),
) -> discord.Embed:
    """Embed standar untuk aksi moderasi."""
    embed = discord.Embed(title=title, color=color, timestamp=datetime.datetime.utcnow())
    embed.add_field(name="Member", value=target.mention, inline=True)
    embed.add_field(name="Moderator", value=moderator.mention, inline=True)
    embed.add_field(name="Alasan", value=alasan, inline=False)
    embed.set_thumbnail(url=target.display_avatar.url)
    return embed
