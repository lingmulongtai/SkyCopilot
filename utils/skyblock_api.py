"""
utils/skyblock_api.py
---------------------
Async helpers for:
  1. Resolving a Minecraft username → UUID via the Mojang API.
  2. Fetching a player's Skyblock profile from the SkyCrypt public API.
  3. Extracting a lightweight context dict from the raw JSON for the LLM.

SkyCrypt API base: https://sky.shiiyu.moe/api/v2/profile/{uuid}
"""

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

MOJANG_API = "https://api.mojang.com/users/profiles/minecraft/{username}"
SKYCRYPT_API = "https://sky.shiiyu.moe/api/v2/profile/{uuid}"

# Maximum time (seconds) to wait for an external API response.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

# How many times to retry on rate-limit (HTTP 429) before giving up.
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0  # seconds

# Item type substrings considered weapons.
_WEAPON_TYPES = ("sword", "bow", "wand", "rod", "scythe", "axe")

# Slayer boss keys (SkyCrypt) → display labels.
_SLAYER_TARGETS = {
    "zombie": "Zombie",
    "spider": "Spider",
    "wolf": "Wolf",
    "enderman": "Enderman",
}


async def _get(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    """Perform a GET request with retry logic for rate-limits and timeouts."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(url, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 429:
                    retry_after = float(resp.headers.get("Retry-After", RETRY_BACKOFF * attempt))
                    logger.warning("Rate-limited by %s, retrying in %.1fs (attempt %d)", url, retry_after, attempt)
                    await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except asyncio.TimeoutError:
            logger.warning("Timeout on %s (attempt %d/%d)", url, attempt, MAX_RETRIES)
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(RETRY_BACKOFF * attempt)
    raise RuntimeError(f"Failed to GET {url} after {MAX_RETRIES} attempts")


async def fetch_uuid(username: str) -> tuple[str, str]:
    """
    Resolve *username* to a Minecraft UUID via the Mojang API.

    Returns
    -------
    (uuid, canonical_name)

    Raises
    ------
    ValueError  – if the username does not exist.
    RuntimeError – on network / API errors.
    """
    url = MOJANG_API.format(username=username)
    async with aiohttp.ClientSession() as session:
        data = await _get(session, url)

    uuid: str | None = data.get("id")
    name: str | None = data.get("name")
    if not uuid or not name:
        raise ValueError(f"Minecraft user '{username}' not found.")
    return uuid, name


async def fetch_skyblock_context(uuid: str) -> dict[str, Any]:
    """
    Fetch the SkyCrypt profile for *uuid* and return a lightweight context
    dict suitable for inclusion in an LLM prompt.

    The returned dict has the following keys (values may be ``"N/A"``):
        profile_name, skyblock_level, skill_average, catacombs_level,
        magical_power, armor, weapon, slayers
    """
    url = SKYCRYPT_API.format(uuid=uuid)
    async with aiohttp.ClientSession() as session:
        raw = await _get(session, url)

    return _extract_context(raw)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _safe(value: Any, default: str = "N/A") -> Any:
    """Return *value* if it is not None/empty, otherwise *default*."""
    if value is None or value == "":
        return default
    return value


def _extract_context(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Extract the minimum required fields from the SkyCrypt JSON.

    SkyCrypt /api/v2/profile/{uuid} returns a top-level object whose keys
    are profile names (e.g. "Tomato", "Banana").  Each profile has a
    ``current`` flag set to ``true`` for the active profile.
    """
    # ── 1. Locate the currently selected profile ──────────────────────────
    profile_name = "N/A"
    profile_data: dict[str, Any] = {}

    for name, pdata in raw.items():
        if not isinstance(pdata, dict):
            continue
        if pdata.get("current"):
            profile_name = name
            profile_data = pdata
            break

    # Fallback: use the first profile found
    if not profile_data:
        for name, pdata in raw.items():
            if isinstance(pdata, dict):
                profile_name = name
                profile_data = pdata
                break

    if not profile_data:
        return _empty_context()

    # ── 2. Skyblock Level ─────────────────────────────────────────────────
    skyblock_level: Any = _safe(
        _deep(profile_data, "skyblock_level", "level")
    )

    # ── 3. Skill Average ─────────────────────────────────────────────────
    skills_raw = profile_data.get("skills") or {}
    skill_levels: list[float] = []
    for skill_name, skill_val in skills_raw.items():
        if skill_name in ("runecrafting", "social"):
            # These skills are not counted in the official average
            continue
        level = _deep(skill_val, "level")
        if isinstance(level, (int, float)):
            skill_levels.append(float(level))
    skill_average: Any = (
        round(sum(skill_levels) / len(skill_levels), 2) if skill_levels else "N/A"
    )

    # ── 4. Catacombs Level ───────────────────────────────────────────────
    catacombs_level: Any = _safe(
        _deep(profile_data, "dungeons", "catacombs", "level", "level")
    )

    # ── 5. Magical Power ─────────────────────────────────────────────────
    magical_power: Any = _safe(
        _deep(profile_data, "misc", "magical_power")
        or _deep(profile_data, "magical_power")
    )

    # ── 6. Equipped Armor & Weapon ────────────────────────────────────────
    armor_pieces: list[str] = []
    weapon_name = "N/A"

    inventory = profile_data.get("inventory") or {}
    armor_data = inventory.get("armor") or {}
    armor_items = armor_data.get("items") or []

    for item in armor_items:
        if not isinstance(item, dict):
            continue
        display = (
            item.get("display_name")
            or _deep(item, "tag", "display", "Name")
        )
        if display:
            armor_pieces.append(str(display))

    # Weapon – look through the player's hotbar / equipment
    equipment_data = inventory.get("equipment") or {}
    equipment_items = equipment_data.get("items") or []
    for item in equipment_items:
        if not isinstance(item, dict):
            continue
        item_type = (item.get("type") or "").lower()
        if any(t in item_type for t in _WEAPON_TYPES):
            weapon_name = item.get("display_name") or "Unknown weapon"
            break

    # Fallback: scan hotbar for weapons
    if weapon_name == "N/A":
        hotbar = (inventory.get("inv_contents") or {}).get("items") or []
        for item in hotbar[:9]:  # first 9 slots
            if not isinstance(item, dict):
                continue
            item_type = (item.get("type") or "").lower()
            if any(t in item_type for t in _WEAPON_TYPES):
                weapon_name = item.get("display_name") or "Unknown weapon"
                break

    armor_str = ", ".join(armor_pieces) if armor_pieces else "N/A"

    # ── 7. Slayers ────────────────────────────────────────────────────────
    slayers_raw = profile_data.get("slayers") or {}
    slayers: dict[str, Any] = {}
    for key, label in _SLAYER_TARGETS.items():
        boss = slayers_raw.get(key) or {}
        slayers[label] = _safe(_deep(boss, "level", "currentLevel") or _deep(boss, "level"))

    return {
        "profile_name": profile_name,
        "skyblock_level": skyblock_level,
        "skill_average": skill_average,
        "catacombs_level": catacombs_level,
        "magical_power": magical_power,
        "armor": armor_str,
        "weapon": weapon_name,
        "slayers": slayers,
    }


def _empty_context() -> dict[str, Any]:
    return {
        "profile_name": "N/A",
        "skyblock_level": "N/A",
        "skill_average": "N/A",
        "catacombs_level": "N/A",
        "magical_power": "N/A",
        "armor": "N/A",
        "weapon": "N/A",
        "slayers": {"Zombie": "N/A", "Spider": "N/A", "Wolf": "N/A", "Enderman": "N/A"},
    }


def _deep(obj: Any, *keys: str) -> Any:
    """Safely traverse nested dicts; returns ``None`` if any key is missing."""
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def format_context_for_prompt(ctx: dict[str, Any], minecraft_name: str) -> str:
    """
    Convert the context dict into a human-readable block for the LLM prompt.
    """
    slayers = ctx.get("slayers", {})
    slayer_lines = "\n".join(
        f"  - {boss}: Lv {level}" for boss, level in slayers.items()
    )
    return (
        f"## プレイヤー情報\n"
        f"- Minecraft名: {minecraft_name}\n"
        f"- プロファイル: {ctx['profile_name']}\n"
        f"- Skyblock Level: {ctx['skyblock_level']}\n"
        f"- Skill Average: {ctx['skill_average']}\n"
        f"- Catacombs Level: {ctx['catacombs_level']}\n"
        f"- Magical Power: {ctx['magical_power']}\n"
        f"- 装備中Armor: {ctx['armor']}\n"
        f"- 装備中Weapon: {ctx['weapon']}\n"
        f"- Slayerレベル:\n{slayer_lines}\n"
    )
