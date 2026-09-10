"""Portable skill files loaded through an explicit model tool, not provider SDK features."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class SkillLoadError(ValueError):
    pass


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str


def parse_skill_md(text: str, path: Path | None = None) -> Skill:
    if not text.startswith("---"):
        raise SkillLoadError(f"{path or 'SKILL.md'}: missing YAML frontmatter")
    try:
        _, frontmatter, body = text.split("---", 2)
    except ValueError as error:
        raise SkillLoadError(f"{path or 'SKILL.md'}: malformed frontmatter") from error
    metadata = yaml.safe_load(frontmatter) or {}
    if not metadata.get("name") or not metadata.get("description"):
        raise SkillLoadError(f"{path or 'SKILL.md'}: frontmatter needs name and description")
    return Skill(str(metadata["name"]), str(metadata["description"]).strip(), body.strip())


class SkillRegistry:
    def __init__(self, skills: list[Skill]) -> None:
        self._skills = sorted(skills, key=lambda skill: skill.name)
        self._by_name = {skill.name: skill for skill in self._skills}
        if len(self._skills) != len(self._by_name):
            raise SkillLoadError("skill names must be unique")

    @classmethod
    def from_dir(cls, root: Path) -> SkillRegistry:
        skills = [
            parse_skill_md((child / "SKILL.md").read_text(encoding="utf-8"), child / "SKILL.md")
            for child in root.iterdir()
            if child.is_dir() and (child / "SKILL.md").is_file()
        ]
        return cls(skills)

    @property
    def names(self) -> list[str]:
        return [skill.name for skill in self._skills]

    def index_block(self) -> str:
        return (
            "\n".join(f"- `{skill.name}`: {skill.description}" for skill in self._skills)
            or "(no skills installed)"
        )

    def get_instructions(self, name: str) -> str | None:
        skill = self._by_name.get(name)
        return skill.body if skill else None
