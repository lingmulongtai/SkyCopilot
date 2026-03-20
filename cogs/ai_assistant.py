"""
cogs/ai_assistant.py
--------------------
Slash commands:
  /ask <question>  – Ask the LLM a question in the context of your Skyblock stats.
  /advice          – Get three AI-generated next-step recommendations.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands
from openai import RateLimitError, APITimeoutError

from utils.database import get_user
from utils.skyblock_api import fetch_skyblock_context, format_context_for_prompt
from utils.llm import ask_llm

logger = logging.getLogger(__name__)

_NOT_REGISTERED_MSG = (
    "❌ まだ登録されていません。先に `/register <Minecraft_ID>` を実行してください。"
)

# Maximum characters per Discord message (embed description limit is 4096)
EMBED_DESCRIPTION_LIMIT = 4000


def _truncate(text: str, limit: int = EMBED_DESCRIPTION_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class AIAssistant(commands.Cog):
    """Provides AI-powered Skyblock advice."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _get_stats_context(self, discord_id: str) -> tuple[str, str] | None:
        """
        Fetch the player's Skyblock stats and return (context_block, minecraft_name).
        Returns ``None`` if the user is not registered.
        """
        row = get_user(discord_id)
        if not row:
            return None

        minecraft_name: str = row["minecraft_name"]
        uuid: str = row["minecraft_uuid"]

        ctx = await fetch_skyblock_context(uuid)
        context_block = format_context_for_prompt(ctx, minecraft_name)
        return context_block, minecraft_name

    # ------------------------------------------------------------------
    # /ask
    # ------------------------------------------------------------------

    @app_commands.command(
        name="ask",
        description="Skyblockに関する質問をAIアシスタントに聞きます。",
    )
    @app_commands.describe(question="AIに聞きたいこと（例: 「次に強化すべきスキルは？」）")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        """Ask the LLM a question, with the user's stats as context."""
        await interaction.response.defer()

        result = await self._get_stats_context(str(interaction.user.id))
        if result is None:
            await interaction.followup.send(_NOT_REGISTERED_MSG)
            return

        context_block, minecraft_name = result

        try:
            answer = await ask_llm(user_message=question, stats_context=context_block)
        except RateLimitError:
            await interaction.followup.send(
                "⚠️ AIのレートリミットに達しました。少し待ってから再試行してください。"
            )
            return
        except APITimeoutError:
            await interaction.followup.send(
                "⚠️ AIへのリクエストがタイムアウトしました。再試行してください。"
            )
            return
        except Exception as exc:
            logger.error("LLM error in /ask: %s", exc)
            await interaction.followup.send(
                "⚠️ AI応答の取得中にエラーが発生しました。"
            )
            return

        embed = discord.Embed(
            title=f"💬 {discord.utils.escape_markdown(minecraft_name)} への回答",
            description=_truncate(answer),
            color=discord.Color.blue(),
        )
        embed.set_footer(text="SkyCopilot AI Assistant")
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /advice
    # ------------------------------------------------------------------

    @app_commands.command(
        name="advice",
        description="現在のSkyblockの状況から、次にやるべきおすすめタスクを3つ提案します。",
    )
    async def advice(self, interaction: discord.Interaction) -> None:
        """Ask the LLM for three next-step recommendations based on the user's stats."""
        await interaction.response.defer()

        result = await self._get_stats_context(str(interaction.user.id))
        if result is None:
            await interaction.followup.send(_NOT_REGISTERED_MSG)
            return

        context_block, minecraft_name = result

        advice_prompt = (
            "上記のステータスを踏まえて、今すぐ取り組むべき**次のおすすめタスクを3つ**提案してください。\n"
            "各タスクには、なぜそれが優先されるべきか簡単な理由も添えてください。\n"
            "金策、スキル上げ、装備更新、ダンジョン攻略など幅広い観点から提案してください。"
        )

        try:
            answer = await ask_llm(user_message=advice_prompt, stats_context=context_block)
        except RateLimitError:
            await interaction.followup.send(
                "⚠️ AIのレートリミットに達しました。少し待ってから再試行してください。"
            )
            return
        except APITimeoutError:
            await interaction.followup.send(
                "⚠️ AIへのリクエストがタイムアウトしました。再試行してください。"
            )
            return
        except Exception as exc:
            logger.error("LLM error in /advice: %s", exc)
            await interaction.followup.send(
                "⚠️ AI応答の取得中にエラーが発生しました。"
            )
            return

        embed = discord.Embed(
            title=f"📋 {discord.utils.escape_markdown(minecraft_name)} へのおすすめタスク",
            description=_truncate(answer),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="SkyCopilot AI Assistant")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AIAssistant(bot))
