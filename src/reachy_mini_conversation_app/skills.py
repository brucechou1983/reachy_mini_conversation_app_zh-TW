"""Agent Skills catalog scanner for profile-based skill discovery."""

import re
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).parent / "profiles"


@dataclass
class SkillEntry:
    """A discovered skill with its metadata."""
    name: str
    description: str
    skill_dir: Path

    @property
    def skill_md_path(self) -> Path:
        return self.skill_dir / "SKILL.md"

    def load_body(self) -> str:
        """Load the full SKILL.md body (everything after frontmatter)."""
        content = self.skill_md_path.read_text(encoding="utf-8")
        # Strip YAML frontmatter (between --- markers)
        match = re.match(r"^---\s*\n.*?\n---\s*\n", content, re.DOTALL)
        if match:
            return content[match.end():].strip()
        return content.strip()


def scan_skills(profile: str) -> list[SkillEntry]:
    """Scan a profile's skills/ directory and return catalog entries."""
    skills_dir = PROFILES_DIR / profile / "skills"
    if not skills_dir.is_dir():
        return []

    entries = []
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue

        content = skill_md.read_text(encoding="utf-8")

        # Parse YAML frontmatter for name and description
        fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not fm_match:
            logger.warning("Skill %s has no frontmatter, skipping", skill_dir.name)
            continue

        frontmatter = fm_match.group(1)
        name = _extract_yaml_field(frontmatter, "name") or skill_dir.name
        description = _extract_yaml_field(frontmatter, "description") or ""

        entries.append(SkillEntry(name=name, description=description, skill_dir=skill_dir))
        logger.info("Discovered skill: %s — %s", name, description[:80])

    return entries


def format_catalog(entries: list[SkillEntry]) -> str:
    """Format skill entries into a compact catalog block for system prompt injection."""
    if not entries:
        return ""

    lines = ["## 可用遊戲技能（用 activate_skill 工具開始遊戲）"]
    for entry in entries:
        lines.append(f"- **{entry.name}**: {entry.description}")
    return "\n".join(lines)


def _extract_yaml_field(frontmatter: str, field: str) -> str | None:
    """Simple YAML field extraction (no full parser needed)."""
    match = re.search(rf"^{field}:\s*(.+)$", frontmatter, re.MULTILINE)
    if match:
        value = match.group(1).strip()
        # Strip surrounding quotes if present
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        return value
    return None
