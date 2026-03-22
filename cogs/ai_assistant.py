"""
cogs/ai_assistant.py
--------------------
Slash commands:
  /profile         – Show your current Skyblock stats as an embed.
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
    # /profile
    # ------------------------------------------------------------------

    @app_commands.command(
        name="profile",
        description="登録済みのSkyblockステータスを表示します。",
    )
    async def profile(self, interaction: discord.Interaction) -> None:
        """Display the user's current Skyblock stats without calling the LLM."""
        await interaction.response.defer()

        row = get_user(str(interaction.user.id))
        if not row:
            await interaction.followup.send(_NOT_REGISTERED_MSG)
            return

        minecraft_name: str = row["minecraft_name"]
        uuid: str = row["minecraft_uuid"]

        try:
            ctx = await fetch_skyblock_context(uuid)
        except Exception as exc:
            logger.error("SkyCrypt API error in /profile: %s", exc)
            await interaction.followup.send(
                "⚠️ Skyblockのデータ取得中にエラーが発生しました。しばらくしてから再試行してください。"
            )
            return

        slayers = ctx.get("slayers", {})
        slayer_lines = "\n".join(
            f"　・{boss}: Lv {level}" for boss, level in slayers.items()
        )

        embed = discord.Embed(
            title=f"🧑‍🚀 {discord.utils.escape_markdown(minecraft_name)} のプロフィール",
            color=discord.Color.teal(),
        )
        embed.add_field(name="プロファイル", value=ctx["profile_name"], inline=True)
        embed.add_field(name="Skyblock Level", value=str(ctx["skyblock_level"]), inline=True)
        embed.add_field(name="Skill Average", value=str(ctx["skill_average"]), inline=True)
        embed.add_field(name="Catacombs Level", value=str(ctx["catacombs_level"]), inline=True)
        embed.add_field(name="Magical Power", value=str(ctx["magical_power"]), inline=True)
        embed.add_field(name="Armor", value=ctx["armor"], inline=False)
        embed.add_field(name="Weapon", value=ctx["weapon"], inline=False)
        embed.add_field(name="Slayer", value=slayer_lines or "N/A", inline=False)
        embed.set_footer(text="SkyCopilot AI Assistant")
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /ask
    # ------------------------------------------------------------------

    @app_commands.command(
        name="ask",
        description="Skyblockに関する質問をAIアシスタントに聞きます。",
    )
    @app_commands.describe(question="AIに聞きたいこと（例: 「次に強化すべきスキルは？」）")
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.user.id)
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
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: i.user.id)
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

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            retry = round(error.retry_after)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"⏳ コマンドはクールダウン中です。あと **{retry}秒** 後に再試行してください。",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"⏳ コマンドはクールダウン中です。あと **{retry}秒** 後に再試行してください。",
                    ephemeral=True,
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AIAssistant(bot))
