"""
main.py
-------
SkyCopilot Discord Bot entry-point.

Usage
-----
1. Copy .env.example to .env and fill in your tokens.
2. Install dependencies:  pip install -r requirements.txt
3. Run:  python main.py
"""

import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from utils.database import init_db

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

load_dotenv()

DISCORD_TOKEN: str = os.environ.get("DISCORD_TOKEN", "")
if not DISCORD_TOKEN:
    raise EnvironmentError(
        "DISCORD_TOKEN is not set. "
        "Copy .env.example to .env and add your bot token."
    )

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

COGS = [
    "cogs.registration",
    "cogs.ai_assistant",
]


class SkyCopilot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        # Initialise the SQLite database
        init_db()

        # Load all Cogs
        for cog in COGS:
            try:
                await self.load_extension(cog)
                logger.info("Loaded cog: %s", cog)
            except Exception as exc:
                logger.error("Failed to load cog %s: %s", cog, exc)

        # Sync slash commands with Discord
        synced = await self.tree.sync()
        logger.info("Synced %d slash command(s).", len(synced))

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "?")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Hypixel Skyblock ✨",
            )
        )


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

async def main() -> None:
    async with SkyCopilot() as bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
