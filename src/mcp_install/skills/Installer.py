"""Validate and deploy Skill directories independently of Agent-specific paths."""

from __future__ import annotations

import datetime
import json
import pathlib
import re
import shutil
import tempfile

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SkillSpec:
    path: str
    name: Optional[str] = None

    @classmethod
    def fromDict(cls, value: dict) -> "SkillSpec":
        if not isinstance(value, dict) or not isinstance(value.get("path"), str):
            raise ValueError("Each skill must contain a string 'path'")

        name = value.get("name")
        if name is not None and not isinstance(name, str):
            raise ValueError("Skill 'name' must be a string")

        return cls(path=value["path"], name=name)


@dataclass(frozen=True)
class PreparedSkill:
    name: str
    source: Optional[pathlib.Path]


class SkillInstaller:
    """Owns Skill validation and safe filesystem operations, never Agent routing."""

    _NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    _MARKER = ".mcp-install.json"

    @classmethod
    def _validateName(cls, name: str) -> str:
        if not cls._NAME.fullmatch(name):
            raise ValueError(
                f"Invalid skill name: {name!r} (use lowercase letters, digits and hyphens)"
            )

        return name

    @classmethod
    def _source(cls, spec: SkillSpec, manifestPath: pathlib.Path) -> pathlib.Path:
        relative = pathlib.PurePath(spec.path)
        if (
            "\\" in spec.path
            or ":" in spec.path
            or relative.is_absolute()
            or ".." in relative.parts
        ):
            raise ValueError(f"Skill path must remain under the manifest directory: {spec.path}")

        root = manifestPath.parent.resolve()
        source = (root / relative).resolve()
        if not source.is_relative_to(root):
            raise ValueError(f"Skill path escapes the manifest directory: {spec.path}")
        if not source.is_dir():
            raise FileNotFoundError(f"Skill directory not found: {source}")

        for entry in [source, *source.rglob("*")]:
            if entry.is_symlink():
                raise ValueError(f"Skill contains an unsafe symbolic link: {entry}")

        skillFile = source / "SKILL.md"
        if not skillFile.is_file():
            raise ValueError(f"Missing SKILL.md in {source}")

        text = skillFile.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError(f"SKILL.md requires YAML frontmatter: {skillFile}")

        return source

    @classmethod
    def _requireSafeDirectory(cls, directory: pathlib.Path) -> None:
        for ancestor in [directory, *directory.parents]:
            if ancestor.is_symlink():
                raise ValueError(f"Refusing to write through symbolic link: {ancestor}")

    @classmethod
    def _owned(cls, destination: pathlib.Path) -> bool:
        marker = destination / cls._MARKER
        if not marker.is_file() or marker.is_symlink():
            return False

        metadata = json.loads(marker.read_text(encoding="utf-8"))
        return metadata.get("managed_by") == "mcp-install"

    @classmethod
    def _publish(
        cls,
        source: pathlib.Path,
        destination: pathlib.Path,
        overwrite: bool,
    ) -> Optional[pathlib.Path]:
        cls._requireSafeDirectory(destination.parent)
        if destination.exists() or destination.is_symlink():
            if not overwrite:
                raise FileExistsError(f"Skill already exists at {destination}; use --overwrite")
            if not destination.is_dir() or destination.is_symlink():
                raise ValueError(f"Refusing to replace non-directory: {destination}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        stagingPath = pathlib.Path(
            tempfile.mkdtemp(prefix=".mcp-install-", dir=destination.parent)
        )
        stagedSkill = stagingPath / "skill"
        backupPath = None

        try:
            shutil.copytree(source, stagedSkill, symlinks=False)
            (stagedSkill / cls._MARKER).write_text(
                json.dumps({"managed_by": "mcp-install"}) + "\n",
                encoding="utf-8",
            )

            if destination.exists():
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                backupPath = destination.with_name(f"{destination.name}.bak_{timestamp}")
                destination.rename(backupPath)

            stagedSkill.rename(destination)
        except Exception:
            if backupPath is not None and not destination.exists():
                backupPath.rename(destination)
            raise
        finally:
            shutil.rmtree(stagingPath)

        return backupPath

    @classmethod
    def prepare(
        cls,
        specs: list[SkillSpec],
        manifestPath: pathlib.Path,
        uninstall: bool = False,
    ) -> list[PreparedSkill]:
        if not specs:
            raise ValueError("Skill component selected but no skills are configured")

        skills = []
        for spec in specs:
            name = cls._validateName(spec.name or pathlib.PurePath(spec.path).name)
            source = None if uninstall else cls._source(spec, manifestPath)
            skills.append(PreparedSkill(name, source))

        names = [skill.name for skill in skills]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate Skill names in the manifest")

        return skills

    @classmethod
    def install(
        cls,
        skill: PreparedSkill,
        destination: pathlib.Path,
        overwrite: bool,
    ) -> Optional[pathlib.Path]:
        if skill.source is None:
            raise ValueError(f"Skill {skill.name} does not have a source directory")

        return cls._publish(skill.source, destination, overwrite)

    @classmethod
    def uninstall(cls, destination: pathlib.Path) -> bool:
        cls._requireSafeDirectory(destination.parent)
        if not destination.exists() and not destination.is_symlink():
            return False
        if destination.is_symlink() or not cls._owned(destination):
            raise ValueError(f"Refusing to uninstall unmanaged skill: {destination}")

        shutil.rmtree(destination)
        return True
