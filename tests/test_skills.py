"""Tests for the Agent Skills catalog scanner (skills.py) and its prompt wiring.

All tests are filesystem-only — no robot hardware, network, or OpenAI key.
"""

from pathlib import Path

import pytest

import reachy_mini_conversation_app.skills as skills_mod
from reachy_mini_conversation_app.skills import (
    SkillEntry,
    scan_skills,
    format_catalog,
    _extract_yaml_field,
)


ENGLISH_LEARNER_SKILLS = {
    "color-detective",
    "simon-says",
    "teach-robot",
    "emotion-mirror",
    "photo-hunt",
    "story-builder",
    "read-with-me",
}


# ------------------------------------------------------------------
# _extract_yaml_field
# ------------------------------------------------------------------


class TestExtractYamlField:
    def test_unquoted(self):
        assert _extract_yaml_field("name: color-detective", "name") == "color-detective"

    def test_double_quoted(self):
        assert _extract_yaml_field('name: "hello world"', "name") == "hello world"

    def test_single_quoted(self):
        assert _extract_yaml_field("name: 'hello'", "name") == "hello"

    def test_missing_field_returns_none(self):
        assert _extract_yaml_field("name: x", "description") is None

    def test_picks_correct_field_among_many(self):
        fm = "name: foo\ndescription: bar baz"
        assert _extract_yaml_field(fm, "description") == "bar baz"


# ------------------------------------------------------------------
# format_catalog (pure)
# ------------------------------------------------------------------


class TestFormatCatalog:
    def test_empty_returns_empty_string(self):
        assert format_catalog([]) == ""

    def test_lists_each_entry(self):
        entries = [
            SkillEntry(name="a", description="desc-a", skill_dir=Path("/x/a")),
            SkillEntry(name="b", description="desc-b", skill_dir=Path("/x/b")),
        ]
        catalog = format_catalog(entries)
        assert "## 可用遊戲技能" in catalog
        assert "- **a**: desc-a" in catalog
        assert "- **b**: desc-b" in catalog


# ------------------------------------------------------------------
# scan_skills + SkillEntry.load_body against a synthetic profile tree
# ------------------------------------------------------------------


def _write_skill(skills_dir: Path, name: str, description: str, body: str = "RULES") -> None:
    d = skills_dir / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )


class TestScanSkills:
    @pytest.fixture()
    def fake_profiles(self, tmp_path: Path, monkeypatch):
        """Point skills.PROFILES_DIR at an empty tmp tree for isolated scans."""
        monkeypatch.setattr(skills_mod, "PROFILES_DIR", tmp_path)
        return tmp_path

    def test_missing_skills_dir_returns_empty(self, fake_profiles):
        assert scan_skills("no_such_profile") == []

    def test_discovers_and_sorts_by_dir_name(self, fake_profiles):
        skills_dir = fake_profiles / "p" / "skills"
        _write_skill(skills_dir, "banana", "B game")
        _write_skill(skills_dir, "apple", "A game")

        entries = scan_skills("p")
        assert [e.name for e in entries] == ["apple", "banana"]
        assert entries[0].description == "A game"

    def test_skips_dir_without_skill_md(self, fake_profiles):
        skills_dir = fake_profiles / "p" / "skills"
        _write_skill(skills_dir, "good", "ok")
        (skills_dir / "empty").mkdir(parents=True)

        entries = scan_skills("p")
        assert [e.name for e in entries] == ["good"]

    def test_skips_skill_without_frontmatter(self, fake_profiles):
        skills_dir = fake_profiles / "p" / "skills"
        nofm = skills_dir / "nofm"
        nofm.mkdir(parents=True)
        (nofm / "SKILL.md").write_text("# body only, no frontmatter\n", encoding="utf-8")

        assert scan_skills("p") == []

    def test_name_defaults_to_dir_when_field_absent(self, fake_profiles):
        skills_dir = fake_profiles / "p" / "skills"
        d = skills_dir / "fallback"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\ndescription: d\n---\nbody\n", encoding="utf-8")

        entries = scan_skills("p")
        assert entries[0].name == "fallback"

    def test_load_body_strips_frontmatter(self, fake_profiles):
        skills_dir = fake_profiles / "p" / "skills"
        _write_skill(skills_dir, "g", "d", body="# Title\nplay the game")

        body = scan_skills("p")[0].load_body()
        assert body.startswith("# Title")
        assert "play the game" in body
        assert "name:" not in body
        assert "description:" not in body


# ------------------------------------------------------------------
# Regression against the real english_learner profile
# ------------------------------------------------------------------


class TestEnglishLearnerProfile:
    def test_all_skills_discovered(self):
        names = {e.name for e in scan_skills("english_learner")}
        assert names == ENGLISH_LEARNER_SKILLS

    def test_skill_name_matches_directory(self):
        # activate_skill matches on entry.name and the model may guess the
        # directory name, so the two must stay in sync.
        for entry in scan_skills("english_learner"):
            assert entry.name == entry.skill_dir.name

    def test_every_skill_has_description_and_loadable_body(self):
        for entry in scan_skills("english_learner"):
            assert entry.description, f"{entry.name} missing description"
            body = entry.load_body()
            assert body, f"{entry.name} has empty body"
            # frontmatter must be stripped from the first line
            assert not body.splitlines()[0].startswith("---")

    def test_catalog_contains_every_skill(self):
        catalog = format_catalog(scan_skills("english_learner"))
        assert "## 可用遊戲技能" in catalog
        for name in ENGLISH_LEARNER_SKILLS:
            assert name in catalog


# ------------------------------------------------------------------
# Prompt injection (prompts.get_session_instructions)
# ------------------------------------------------------------------


class TestPromptCatalogInjection:
    def test_english_learner_prompt_includes_catalog(self, monkeypatch):
        import reachy_mini_conversation_app.prompts as prompts_mod
        from reachy_mini_conversation_app.config import config

        monkeypatch.setattr(config, "REACHY_MINI_CUSTOM_PROFILE", "english_learner")
        instructions = prompts_mod.get_session_instructions()

        assert "## 可用遊戲技能" in instructions
        for name in ENGLISH_LEARNER_SKILLS:
            assert name in instructions

    def test_profile_without_skills_has_no_catalog(self, monkeypatch):
        import reachy_mini_conversation_app.prompts as prompts_mod
        from reachy_mini_conversation_app.config import config

        # cosmic_kitchen has instructions.txt but no skills/ directory.
        monkeypatch.setattr(config, "REACHY_MINI_CUSTOM_PROFILE", "cosmic_kitchen")
        instructions = prompts_mod.get_session_instructions()

        assert "## 可用遊戲技能" not in instructions
