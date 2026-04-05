import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from cogs.prefix import get_prefix   # callable prefix per-guild
from utils.logger import setup_logger

load_dotenv()
setup_logger()
logger = logging.getLogger("discord_bot")

# Daftar cog yang akan di-load (urutan bebas)
COGS = [
    "cogs.prefix",        # ← harus di-load agar get_prefix bisa bekerja
    "cogs.logging",   # logging terpusat — load awal agar cog lain bisa pakai
    "cogs.moderation",
    "cogs.roles",         # auto role + reaction role
    "cogs.info",
    "cogs.events",
]

# Inisialisasi bot
intents = discord.Intents.default()
intents.members         = True
intents.message_content = True

bot = commands.Bot(
    command_prefix=get_prefix,   # callable — dipanggil tiap pesan masuk
    intents=intents,
    help_command=commands.DefaultHelpCommand(),
)


# Events
@bot.event
async def on_ready():
    logger.info(f"Bot online sebagai {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="server | @mention untuk prefix"
    ))


# Load semua cog
async def load_cogs():
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            logger.info(f"Cog loaded: {cog}")
        except Exception as e:
            logger.error(f"Gagal load cog {cog}: {e}")


async def main():
    async with bot:
        await load_cogs()
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            raise ValueError("DISCORD_TOKEN tidak ditemukan di .env!")
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())