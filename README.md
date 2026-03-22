# SkyCopilot

An intelligent Discord bot using LLM and SkyCrypt APIs to offer tailored gameplay advice based on real-time Hypixel Skyblock stats.

---

## Features

| Command | Description |
|---|---|
| `/register <minecraft_id>` | Minecraft IDを登録してBotを有効化する |
| `/unregister` | 登録済みのMinecraft IDを削除する |
| `/profile` | 現在のSkyblockステータスをEmbedで表示する |
| `/ask <question>` | AIアシスタントにSkyblockに関する質問をする（クールダウン: 30秒） |
| `/advice` | 現在のステータスに基づいた次のおすすめタスクを3つ提案する（クールダウン: 60秒） |

---

## Getting started

### 1. Prerequisites

- Python 3.10+
- A [Discord bot token](https://discord.com/developers/applications) with the **applications.commands** scope enabled
- An [OpenAI API key](https://platform.openai.com/api-keys)

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in DISCORD_TOKEN and OPENAI_API_KEY
```

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Your Discord bot token |
| `OPENAI_API_KEY` | Your OpenAI API key |
| `OPENAI_MODEL` | Model to use (default: `gpt-4o-mini`) |

### 4. Run

```bash
python main.py
```

The bot will automatically create a local SQLite database (`skyCopilot.db`) and sync slash commands with Discord.

---

## Running tests

```bash
pip install pytest
pytest tests/
```

---

## Architecture

```
SkyCopilot/
├── main.py                 # Bot entry-point
├── cogs/
│   ├── registration.py     # /register, /unregister
│   └── ai_assistant.py     # /profile, /ask, /advice
└── utils/
    ├── database.py         # SQLite helpers
    ├── skyblock_api.py     # Mojang & SkyCrypt API helpers
    └── llm.py              # OpenAI wrapper
```

