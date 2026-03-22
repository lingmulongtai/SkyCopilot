<div align="center">

# 🛸 SkyCopilot

**An AI-powered Discord bot that delivers real-time, personalised Hypixel Skyblock coaching.**

SkyCopilot connects your Discord account to your Minecraft profile, fetches live stats via the [SkyCrypt](https://sky.shiiyu.moe) public API, and routes every question through a resilient multi-provider LLM layer — so you always get a fast, context-aware answer, even when one AI service is down.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![discord.py 2.3+](https://img.shields.io/badge/discord.py-2.3%2B-5865F2?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-pytest-orange?logo=pytest)](tests/)

</div>

---

## ✨ Features

| Command | Description | Cooldown |
|---|---|---|
| `/register <minecraft_id>` | Link your Discord account to a Minecraft username. Resolves the name to a UUID via the Mojang API and persists it locally. | — |
| `/unregister` | Remove your Minecraft registration from the bot's database. | — |
| `/profile` | Display your current Skyblock stats (level, skills, catacombs, magical power, equipped gear, and slayer levels) as a rich Discord embed — no AI call needed. | — |
| `/ask <question>` | Ask the AI assistant any Skyblock question. Your live stats are automatically included as context so advice is tailored to your current progression. | 30 s |
| `/advice` | Get three AI-generated next-step recommendations based on your stats, covering gold farming, skill leveling, gear upgrades, and dungeon progression. | 60 s |

---

## 🏗️ Architecture

```
SkyCopilot/
├── main.py                        # Bot entry-point: loads cogs, syncs slash commands
├── .env.example                   # Template for all environment variables
├── requirements.txt               # Python dependencies
│
├── cogs/
│   ├── registration.py            # /register, /unregister — Mojang UUID resolution + DB persistence
│   └── ai_assistant.py            # /profile, /ask, /advice — stat fetching + LLM dispatch
│
├── utils/
│   ├── database.py                # SQLite helpers: init_db, upsert_user, get_user, delete_user
│   ├── skyblock_api.py            # Mojang & SkyCrypt REST clients + context extraction
│   ├── llm.py                     # Public ask_llm() entry-point; builds the router singleton
│   ├── llm_format.py              # System prompt definition and output post-processing
│   ├── llm_router.py              # Fallback routing, per-provider retry, circuit breaker
│   └── llm_providers/
│       ├── base.py                # LLMProvider ABC + RetryableError exception
│       ├── openrouter_provider.py # OpenRouter Chat Completions (openai/gpt-4o-mini default)
│       ├── gemini_provider.py     # Google Gemini REST API (gemini-1.5-flash default)
│       └── groq_provider.py       # Groq API — OpenAI-compatible (llama3-8b-8192 default)
│
└── tests/
    ├── test_database.py           # SQLite helper unit tests (in-memory DB)
    ├── test_llm_router.py         # Router, circuit breaker, and format enforcement tests
    └── test_skyblock_api.py       # SkyCrypt extraction and context formatting tests
```

### LLM Fallback Flow

When a command triggers an LLM call, the following sequence runs:

```
ask_llm()
  └─► LLMRouter.chat()
        ├─► Provider 1 (e.g. OpenRouter)
        │     ├─ attempt 1 → HTTP 429 → exponential back-off → retry
        │     ├─ attempt 2 → HTTP 429 → exponential back-off → retry
        │     └─ attempt 3 → HTTP 429 → circuit breaker records failure → NEXT PROVIDER
        ├─► Provider 2 (e.g. Gemini)
        │     └─ attempt 1 → success → return response ✓
        └─► Provider 3 (e.g. Groq)   ← only reached if Provider 2 also fails
```

The circuit breaker opens after `LLM_CB_FAILURE_THRESHOLD` consecutive failures and enters a half-open probe state after `LLM_CB_RECOVERY_SECONDS`. All thresholds are tunable via environment variables — no code changes required.

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.10 or later**
- A [Discord application](https://discord.com/developers/applications) with a bot token and the `applications.commands` OAuth2 scope enabled
- At least one LLM API key (OpenRouter, Google AI Studio, or Groq — all have free tiers)

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

```bash
cp .env.example .env
```

Open `.env` and fill in your credentials. The only strictly required variable is `DISCORD_TOKEN`; everything else has a sensible default.

#### Required

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Your Discord bot token from the [Developer Portal](https://discord.com/developers/applications) |

#### LLM Providers — configure at least one

| Variable | Description | Free Tier |
|---|---|---|
| `OPENROUTER_API_KEY` | [OpenRouter API key](https://openrouter.ai/keys) | Many free models (e.g. `meta-llama/llama-3-8b-instruct:free`) |
| `OPENROUTER_MODEL` | Model name (default: `openai/gpt-4o-mini`) | — |
| `GEMINI_API_KEY` | [Google AI Studio key](https://aistudio.google.com/app/apikey) | Generous RPM/RPD limits with `gemini-1.5-flash` |
| `GEMINI_MODEL` | Model name (default: `gemini-1.5-flash`) | — |
| `GROQ_API_KEY` | [Groq API key](https://console.groq.com/keys) | Rate-limited free access to open-source models |
| `GROQ_MODEL` | Model name (default: `llama3-8b-8192`) | — |

#### Provider Order and Routing

```bash
# .env — try OpenRouter first, fall back to Gemini, then Groq
LLM_PROVIDER_ORDER=openrouter,gemini,groq
```

Providers not listed in `LLM_PROVIDER_ORDER`, or whose API key is missing, are silently skipped. The bot works perfectly with a single configured provider; extra providers only improve resilience.

#### Retry and Circuit-Breaker Tuning

These defaults are sized to stay within typical free-tier quotas. Tune them in `.env` whenever a provider changes its limits — **no code edits needed**.

| Variable | Default | Description |
|---|---|---|
| `LLM_RETRY_MAX` | `3` | Maximum retry attempts per provider before falling back to the next one |
| `LLM_RETRY_BASE_SECONDS` | `1.0` | Base back-off delay in seconds; doubles on each retry with full jitter |
| `LLM_CB_FAILURE_THRESHOLD` | `3` | Consecutive failures that trip a provider's circuit breaker |
| `LLM_CB_RECOVERY_SECONDS` | `60` | Seconds a tripped circuit breaker waits before allowing a probe request |

> **Provider Terms of Service**
> Each provider has its own ToS governing free-tier usage. Using multiple providers with legitimately obtained accounts is fine. Do **not** create duplicate accounts at any single provider to bypass rate limits — this violates the respective ToS and risks account suspension.

### 3. Run the Bot

```bash
python main.py
```

On first launch, SkyCopilot automatically:
- Creates a local SQLite database file (`skyCopilot.db`) to store Discord ↔ Minecraft mappings.
- Loads all cogs (`registration`, `ai_assistant`).
- Syncs slash commands with Discord globally.

---

## 🧪 Running Tests

The test suite requires no API keys and uses an in-memory SQLite database.

```bash
pytest tests/
```

The suite covers:

| Test file | What it tests |
|---|---|
| `tests/test_database.py` | `init_db`, `upsert_user`, `get_user`, `delete_user` with a temporary database |
| `tests/test_llm_router.py` | Provider selection order, retryable-error fallback, circuit-breaker states, output format enforcement |
| `tests/test_skyblock_api.py` | SkyCrypt JSON extraction, skill average calculation, slayer parsing, `format_context_for_prompt` |

---

## 🔑 How It Works

### Registration Flow

```
/register Steve
  └─► Mojang API  →  resolve "Steve" to UUID
        └─► SQLite  →  upsert (discord_id, uuid, canonical_name)
              └─► Ephemeral embed reply ✓
```

### AI Query Flow

```
/ask "What skill should I level next?"
  └─► SQLite  →  look up user's Minecraft UUID
        └─► SkyCrypt API  →  fetch live profile JSON
              └─► _extract_context()  →  lightweight stats dict
                    └─► format_context_for_prompt()  →  Markdown context block
                          └─► ask_llm()  →  LLMRouter  →  first healthy provider
                                └─► Discord embed reply ✓
```

### Stat Extraction

SkyCopilot extracts the following fields from the SkyCrypt API response and injects them into every LLM prompt:

| Field | Source |
|---|---|
| Profile name | Active profile key (marked `current: true`) |
| Skyblock Level | `skyblock_level.level` |
| Skill Average | Mean of all countable skills, excluding `runecrafting` and `social` |
| Catacombs Level | `dungeons.catacombs.level.level` |
| Magical Power | `misc.magical_power` |
| Equipped Armor | `inventory.armor.items[*].display_name` |
| Equipped Weapon | `inventory.equipment` then hotbar scan for weapon-type items |
| Slayer Levels | `slayers.{zombie,spider,wolf,enderman,blaze,vampire}.level.currentLevel` |

---

## ⚙️ Technology Stack

| Layer | Technology |
|---|---|
| Discord integration | [discord.py 2.3+](https://discordpy.readthedocs.io/) with application commands |
| HTTP client | [aiohttp 3.9+](https://docs.aiohttp.org/) (async, with retry + timeout) |
| LLM – OpenRouter | [OpenRouter](https://openrouter.ai/) REST API (via aiohttp) — routes to 200+ models |
| LLM – Gemini | Google AI Studio REST API (via aiohttp) |
| LLM – Groq | OpenAI-compatible REST API (via aiohttp) |
| Database | SQLite via the Python standard library (`sqlite3`) |
| Configuration | [python-dotenv](https://github.com/theskumar/python-dotenv) |
| Testing | [pytest](https://docs.pytest.org/) |

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

