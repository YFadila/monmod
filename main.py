import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

from utils.logger import setup_logger

load_dotenv()

logger = setup_logger()

COGS = [
    "cogs.moderation",
    "cogs.info",
    "cogs.events",
]

def get_prefix(bot, message):
    return os.getenv("BOT_PREFIX", "!")


async def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True

    bot = commands.Bot(
        command_prefix=get_prefix,
        intents=intents,
        help_command=commands.DefaultHelpCommand(no_category="Umum"),
        description="Bot moderasi server Discord",
    )

    for cog in COGS:
        try:
            await bot.load_extension(cog)
            logger.info(f"✅ Cog dimuat: {cog}")
        except Exception as e:
            logger.error(f"❌ Gagal memuat cog {cog}: {e}")

    return bot


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.critical("DISCORD_TOKEN tidak ditemukan di .env!")
        sys.exit(1)

    bot = await create_bot()

    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
