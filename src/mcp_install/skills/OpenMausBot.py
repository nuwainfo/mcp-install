"""Stage Skills for OpenMausBot through upstream-supported native Agent directories."""

from __future__ import annotations

import pathlib

from .Backend import SkillBackend


class OpenMausBotSkillBackend(SkillBackend):
    """OpenMausBot imports user Skills from Claude Code and Codex through its reviewed setup flow."""

    def __init__(self):
        super().__init__("openmausbot", ".claude/skills", None)

    def roots(self, scope: str, homePath: pathlib.Path, projectPath: pathlib.Path) -> list[pathlib.Path]:
        if scope != "user":
            raise ValueError("OpenMausBot Skill staging is user-scoped; use --scope user")
        return [homePath / ".claude" / "skills", homePath / ".codex" / "skills"]

    @property
    def installationNotice(self) -> str:
        return (
            "OpenMausBot: Skills are staged in Claude Code/Codex user folders. "
            "To share them with every bot, use Settings > Replay welcome tour > "
            "Bring what you already use, then review/enable imported Skills. "
            "This preserves OpenMausBot's security scanning and index integrity."
        )
