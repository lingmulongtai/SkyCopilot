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
- At least one LLM API key (see below)

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in DISCORD_TOKEN and at least one LLM API key
```

#### Required

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Your Discord bot token |

#### LLM Providers (configure at least one)

The bot uses a **fallback-first routing layer**: providers are tried in the order defined by `LLM_PROVIDER_ORDER`. If the primary provider hits a rate limit, timeout, or transient server error, the next provider is automatically tried.

| Variable | Description | Free tier |
|---|---|---|
| `OPENAI_API_KEY` | [OpenAI API key](https://platform.openai.com/api-keys) | Trial credit for new accounts |
| `OPENAI_MODEL` | Model name (default: `gpt-4o-mini`) | — |
| `GEMINI_API_KEY` | [Google AI Studio key](https://aistudio.google.com/app/apikey) | Generous free RPM/RPD with `gemini-1.5-flash` |
| `GEMINI_MODEL` | Model name (default: `gemini-1.5-flash`) | — |
| `GROQ_API_KEY` | [Groq API key](https://console.groq.com/keys) | Rate-limited free tier for open-source models |
| `GROQ_MODEL` | Model name (default: `llama3-8b-8192`) | — |

#### Fallback order and routing

```
# .env
LLM_PROVIDER_ORDER=openai,gemini,groq   # try OpenAI first, then Gemini, then Groq
```

Providers not listed in `LLM_PROVIDER_ORDER` or without a configured API key are silently skipped.
The bot works with only a single configured provider; additional providers just improve resilience.

#### Retry and circuit-breaker tuning

These values are designed to keep the bot within typical free-tier limits.
Adjust them in `.env` when a provider changes its quota – **no code changes needed**.

| Variable | Default | Description |
|---|---|---|
| `LLM_RETRY_MAX` | `3` | Max retries per provider before trying the next one |
| `LLM_RETRY_BASE_SECONDS` | `1.0` | Base back-off delay (seconds); doubles each retry with jitter |
| `LLM_CB_FAILURE_THRESHOLD` | `3` | Consecutive failures before a provider's circuit breaker opens |
| `LLM_CB_RECOVERY_SECONDS` | `60` | Seconds before a tripped circuit breaker allows probe requests again |

> **Important – Provider Terms of Service**
> Each provider listed above has its own Terms of Service governing free-tier usage.
> Using multiple providers is fine as long as each account is legitimately obtained.
> Do **not** create multiple accounts at the same provider to circumvent rate limits –
> that violates the respective ToS and may result in account suspension.

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
├── main.py                             # Bot entry-point
├── cogs/
│   ├── registration.py                 # /register, /unregister
│   └── ai_assistant.py                 # /profile, /ask, /advice
└── utils/
    ├── database.py                     # SQLite helpers
    ├── skyblock_api.py                 # Mojang & SkyCrypt API helpers
    ├── llm.py                          # Public ask_llm() entry-point
    ├── llm_format.py                   # System prompt & output formatting
    ├── llm_router.py                   # Fallback routing, retry, circuit breaker
    └── llm_providers/
        ├── base.py                     # LLMProvider ABC + RetryableError
        ├── openai_provider.py          # OpenAI Chat Completions
        ├── gemini_provider.py          # Google Gemini REST API
        └── groq_provider.py            # Groq (OpenAI-compatible) REST API
```

### Fallback flow

```
ask_llm()
  └─► LLMRouter.chat()
        ├─► Provider 1 (e.g. OpenAI)
        │     ├─ attempt 1 → 429 → back-off → retry
        │     ├─ attempt 2 → 429 → back-off → retry
        │     └─ attempt 3 → 429 → circuit breaker records failure → NEXT
        ├─► Provider 2 (e.g. Gemini)
        │     └─ attempt 1 → success → return response ✓
        └─► Provider 3 (e.g. Groq)   ← only reached if Provider 2 also fails
```

