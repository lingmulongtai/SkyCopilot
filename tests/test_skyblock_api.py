"""
tests/test_skyblock_api.py
--------------------------
Unit tests for utils/skyblock_api.py (pure functions only – no HTTP calls).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.skyblock_api import (
    _deep,
    _safe,
    _empty_context,
    _extract_context,
    format_context_for_prompt,
    _SLAYER_TARGETS,
)


class TestDeep:
    def test_simple_key(self):
        assert _deep({"a": 1}, "a") == 1

    def test_nested_keys(self):
        assert _deep({"a": {"b": {"c": 42}}}, "a", "b", "c") == 42

    def test_missing_key_returns_none(self):
        assert _deep({"a": 1}, "b") is None

    def test_non_dict_intermediate_returns_none(self):
        assert _deep({"a": "string"}, "a", "b") is None

    def test_empty_dict(self):
        assert _deep({}, "a") is None


class TestSafe:
    def test_returns_value_when_truthy(self):
        assert _safe(42) == 42

    def test_returns_default_for_none(self):
        assert _safe(None) == "N/A"

    def test_returns_default_for_empty_string(self):
        assert _safe("") == "N/A"

    def test_custom_default(self):
        assert _safe(None, "unknown") == "unknown"

    def test_returns_zero(self):
        # 0 is a valid value that should not be replaced by default
        assert _safe(0) == 0


class TestSlayerTargets:
    def test_all_six_slayers_present(self):
        expected = {"zombie", "spider", "wolf", "enderman", "blaze", "vampire"}
        assert set(_SLAYER_TARGETS.keys()) == expected


class TestEmptyContext:
    def test_has_all_expected_keys(self):
        ctx = _empty_context()
        for key in ("profile_name", "skyblock_level", "skill_average",
                    "catacombs_level", "magical_power", "armor", "weapon", "slayers"):
            assert key in ctx

    def test_slayers_includes_blaze_and_vampire(self):
        ctx = _empty_context()
        assert "Blaze" in ctx["slayers"]
        assert "Vampire" in ctx["slayers"]


class TestExtractContext:
    def _make_raw(self, **overrides) -> dict:
        """Build a minimal SkyCrypt-like raw profile dict."""
        profile: dict = {
            "current": True,
            "skyblock_level": {"level": 150},
            "skills": {
                "farming": {"level": 30},
                "mining": {"level": 25},
                "runecrafting": {"level": 3},   # excluded from average
                "social": {"level": 5},          # excluded from average
            },
            "dungeons": {
                "catacombs": {"level": {"level": 20}}
            },
            "misc": {"magical_power": 800},
            "inventory": {},
            "slayers": {
                "zombie": {"level": {"currentLevel": 7}},
                "blaze": {"level": {"currentLevel": 4}},
                "vampire": {"level": {"currentLevel": 2}},
            },
        }
        profile.update(overrides)
        return {"Mango": profile}

    def test_picks_current_profile(self):
        raw = self._make_raw()
        raw["Banana"] = {"current": False, "skyblock_level": {"level": 1}}
        ctx = _extract_context(raw)
        assert ctx["profile_name"] == "Mango"

    def test_skyblock_level(self):
        ctx = _extract_context(self._make_raw())
        assert ctx["skyblock_level"] == 150

    def test_skill_average_excludes_runecrafting_and_social(self):
        ctx = _extract_context(self._make_raw())
        # farming=30, mining=25 → average = 27.5
        assert ctx["skill_average"] == pytest.approx(27.5)

    def test_catacombs_level(self):
        ctx = _extract_context(self._make_raw())
        assert ctx["catacombs_level"] == 20

    def test_magical_power(self):
        ctx = _extract_context(self._make_raw())
        assert ctx["magical_power"] == 800

    def test_slayer_zombie_level(self):
        ctx = _extract_context(self._make_raw())
        assert ctx["slayers"]["Zombie"] == 7

    def test_slayer_blaze_level(self):
        ctx = _extract_context(self._make_raw())
        assert ctx["slayers"]["Blaze"] == 4

    def test_slayer_vampire_level(self):
        ctx = _extract_context(self._make_raw())
        assert ctx["slayers"]["Vampire"] == 2

    def test_empty_raw_returns_empty_context(self):
        ctx = _extract_context({})
        assert ctx["profile_name"] == "N/A"
        assert ctx["skill_average"] == "N/A"


class TestFormatContextForPrompt:
    def test_contains_player_name(self):
        ctx = _empty_context()
        text = format_context_for_prompt(ctx, "Steve")
        assert "Steve" in text

    def test_contains_all_slayer_labels(self):
        ctx = _empty_context()
        text = format_context_for_prompt(ctx, "Steve")
        for label in ("Zombie", "Spider", "Wolf", "Enderman", "Blaze", "Vampire"):
            assert label in text
