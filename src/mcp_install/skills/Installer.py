"""Install local Agent Skills without mixing filesystem deployment into MCP registration."""

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


class SkillBackend:
    """Maps one Agent's user/project skill directories to a common deployment operation."""

    def __init__(self, target: str, userDirectory: str, projectDirectory: Optional[str]):
        self.target = target
        self.userDirectory = userDirectory
        self.projectDirectory = projectDirectory

    def root(self, scope: str, homePath: pathlib.Path, projectPath: pathlib.Path) -> pathlib.Path:
        if scope == "user":
            return homePath / self.userDirectory
        if self.projectDirectory is None:
            raise ValueError(f"{self.target} does not support project-scoped skills")
        return projectPath / self.projectDirectory


class SkillInstaller:
    """Validates a packaged skill and publishes complete, owned directories to Agent roots."""

    _NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    _MARKER = ".mcp-install.json"

    def __init__(self, homePath: Optional[pathlib.Path] = None):
        self.homePath = homePath or pathlib.Path.home()
        self.backends = {
            target.target: target for target in (
                SkillBackend("claude-code", ".claude/skills", ".claude/skills"),
                SkillBackend("codex", ".agents/skills", ".agents/skills"),
                SkillBackend("grok-build", ".grok/skills", ".grok/skills"),
            )
        }

    @classmethod
    def _validateName(cls, name: str) -> str:
        if not cls._NAME.fullmatch(name):
            raise ValueError(f"Invalid skill name: {name!r} (use lowercase letters, digits and hyphens)")
        return name

    @classmethod
    def _source(cls, spec: SkillSpec, manifestPath: pathlib.Path) -> pathlib.Path:
        relative = pathlib.PurePath(spec.path)
        if relative.is_absolute() or ".." in relative.parts:
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
        return json.loads(marker.read_text(encoding="utf-8")).get("managed_by") == "mcp-install"

    @classmethod
    def _publish(cls, source: pathlib.Path, destination: pathlib.Path, overwrite: bool) -> Optional[pathlib.Path]:
        cls._requireSafeDirectory(destination.parent)
        if destination.exists() or destination.is_symlink():
            if not overwrite:
                raise FileExistsError(f"Skill already exists at {destination}; use --overwrite")
            if not destination.is_dir() or destination.is_symlink():
                raise ValueError(f"Refusing to replace non-directory: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        stagingPath = pathlib.Path(tempfile.mkdtemp(prefix=".mcp-install-", dir=destination.parent))
        stagingSkill = stagingPath / "skill"
        backupPath = None
        try:
            shutil.copytree(source, stagingSkill, symlinks=False)
            (stagingSkill / cls._MARKER).write_text(json.dumps({"managed_by": "mcp-install"}) + "\n", encoding="utf-8")
            if destination.exists():
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                backupPath = destination.with_name(f"{destination.name}.bak_{timestamp}")
                destination.rename(backupPath)
            stagingSkill.rename(destination)
        except Exception:
            if backupPath is not None and not destination.exists():
                backupPath.rename(destination)
            raise
        finally:
            shutil.rmtree(stagingPath)
        return backupPath

    @classmethod
    def _remove(cls, destination: pathlib.Path) -> bool:
        cls._requireSafeDirectory(destination.parent)
        if not destination.exists() and not destination.is_symlink():
            return False
        if destination.is_symlink() or not cls._owned(destination):
            raise ValueError(f"Refusing to uninstall unmanaged skill: {destination}")
        shutil.rmtree(destination)
        return True

    def apply(
        self,
        specs: list[SkillSpec],
        targets: list[str],
        scope: str,
        manifestPath: pathlib.Path,
        projectPath: pathlib.Path,
        overwrite: bool = False,
        uninstall: bool = False,
        printOnly: bool = False,
    ) -> None:
        if not specs:
            raise ValueError("Skill component selected but no skills are configured")
        if scope not in ("user", "project"):
            raise ValueError(f"Invalid skill scope: {scope}")

        for spec in specs:
            name = self._validateName(spec.name or pathlib.PurePath(spec.path).name)
            source = None if uninstall else self._source(spec, manifestPath)
            for target in targets:
                backend = self.backends.get(target)
                if backend is None:
                    print(f"Warning: {target} does not support filesystem Skill installation; skipped.")
                    continue
                destination = backend.root(scope, self.homePath, projectPath) / name
                if printOnly:
                    print(f"Skill {name}: {source} -> {target}: {destination}")
                elif uninstall:
                    removed = self._remove(destination)
                    print(f"{'Removed' if removed else 'Not found'} skill {name} at {destination}")
                else:
                    backupPath = self._publish(source, destination, overwrite)
                    print(f"Installed skill {name} into {destination}")
                    if backupPath:
                        print(f"Backup: {backupPath}")
