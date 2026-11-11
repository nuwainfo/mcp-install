"""Filesystem destinations exposed by Agent Skill hosts."""

from __future__ import annotations

import pathlib
from typing import Optional


class SkillBackend:
    """Maps an Agent's user/project Skill roots to filesystem destinations."""

    def __init__(self, target: str, userDirectory: str, projectDirectory: Optional[str]):
        self.target = target
        self.userDirectory = userDirectory
        self.projectDirectory = projectDirectory

    def roots(self, scope: str, homePath: pathlib.Path, projectPath: pathlib.Path) -> list[pathlib.Path]:
        if scope == "user":
            return [homePath / self.userDirectory]
        if self.projectDirectory is None:
            raise ValueError(f"{self.target} does not support project-scoped skills")
        return [projectPath / self.projectDirectory]

    @property
    def installationNotice(self) -> Optional[str]:
        return None
