"""
utils/llm_format.py
--------------------
Centralised system-prompt and output-format utilities.

The system prompt instructs every LLM provider to use the same Markdown
structure so responses are consistent regardless of which provider answers.
Adjust ``SYSTEM_PROMPT`` here when free-tier model behaviour changes – no
other files need editing.
"""

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
あなたは親身で優秀なHypixel Skyblockの専属サポーターです。
ユーザーの現在のステータス（後述）を考慮し、背伸びしすぎない現実的で具体的なアドバイスを提供してください。

**回答フォーマットのルール（必ず守ること）：**
1. 最初に `## [簡潔な見出し（15文字以内）]` を書く。
2. アドバイスや手順は箇条書き（`- ` で始まる行）で 3〜5 個にまとめる。
3. 補足事項があれば `> 注記：...` の形式で末尾に 1 つだけ付ける。
4. 回答全体は **1,500 文字以内** に収める。
5. Discord で読みやすいように Markdown を活用する。
6. 必ず **日本語** で回答する。
"""


# ---------------------------------------------------------------------------
# Post-processing guard
# ---------------------------------------------------------------------------


def enforce_format(text: str) -> str:
    """Light post-processing applied to every provider response.

    * Strips leading/trailing whitespace.
    * Returns a safe fallback message when the response is empty.
    """
    text = text.strip()
    if not text:
        return "⚠️ AIから有効な回答を受け取れませんでした。"
    return text
