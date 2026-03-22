"""
cogs/registration.py
--------------------
Slash command: /register <minecraft_id>

Resolves the Minecraft username to a UUID via Mojang's API and stores the
mapping (Discord ID ↔ Minecraft UUID) in the local SQLite database.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.database import upsert_user, delete_user
from utils.skyblock_api import fetch_uuid

logger = logging.getLogger(__name__)


class Registration(commands.Cog):
    """Handles player registration."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="register",
        description="MinecraftのIDを登録して、Skyblock AIアシスタントを使えるようにします。",
    )
    @app_commands.describe(minecraft_id="あなたのMinecraftユーザー名 (例: Steve)")
    async def register(self, interaction: discord.Interaction, minecraft_id: str) -> None:
        """Register or update the caller's Minecraft username."""
        await interaction.response.defer(ephemeral=True)

        minecraft_id = minecraft_id.strip()
        if not minecraft_id or len(minecraft_id) > 16:
            await interaction.followup.send(
                "❌ 有効なMinecraft IDを入力してください（1〜16文字）。",
                ephemeral=True,
            )
            return

        try:
            uuid, canonical_name = await fetch_uuid(minecraft_id)
        except ValueError:
            await interaction.followup.send(
                f"❌ Minecraft ユーザー **{discord.utils.escape_markdown(minecraft_id)}** が見つかりませんでした。"
                " IDのスペルをご確認ください。",
                ephemeral=True,
            )
            return
        except Exception as exc:
            logger.error("Mojang API error during /register: %s", exc)
            await interaction.followup.send(
                "⚠️ Mojang APIとの通信中にエラーが発生しました。しばらくしてから再試行してください。",
                ephemeral=True,
            )
            return

        discord_id = str(interaction.user.id)
        try:
            upsert_user(discord_id, uuid, canonical_name)
        except Exception as exc:
            logger.error("Database error during /register: %s", exc)
            await interaction.followup.send(
                "⚠️ データベースへの保存中にエラーが発生しました。",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="✅ 登録完了",
            description=(
                f"Minecraft ID **{discord.utils.escape_markdown(canonical_name)}** を登録しました！\n"
                "これで `/ask` や `/advice` コマンドが使えます。"
            ),
            color=discord.Color.green(),
        )
        embed.add_field(name="UUID", value=uuid, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="unregister",
        description="登録済みのMinecraft IDを削除します。",
    )
    async def unregister(self, interaction: discord.Interaction) -> None:
        """Remove the caller's Minecraft registration."""
        await interaction.response.defer(ephemeral=True)

        discord_id = str(interaction.user.id)
        try:
            removed = delete_user(discord_id)
        except Exception as exc:
            logger.error("Database error during /unregister: %s", exc)
            await interaction.followup.send(
                "⚠️ データベースの操作中にエラーが発生しました。",
                ephemeral=True,
            )
            return

        if removed:
            await interaction.followup.send(
                "✅ 登録を削除しました。再び使うには `/register` で再登録してください。",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "❌ まだ登録されていません。",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Registration(bot))
