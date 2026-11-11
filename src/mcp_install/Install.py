#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
#
# mcp-install - Reusable MCP server installer
# Copyright (C) 2026 nuwainfo contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""CLI orchestration for Agent-specific MCP registration and Skill installation."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import pathlib
import subprocess

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from mcp_install.skills import SkillInstaller, SkillSpec

from mcp_install.backends import (
    ClaudeCliBackend,
    ClaudeDesktopBackend,
    CodexBackend,
    AgentBackend,
    GrokBackend,
    OpenMausBotBackend,
    getClaudeCliPath,
    getDefaultClaudeDesktopConfigPath,
    getDefaultCodexConfigPath,
    getDefaultGrokConfigPath,
    getDefaultOpenMausBotConfigPath,
)

defaultAppConfigFilename = "install.config.json"
appConfigEnvVar = "INSTALL_APP_CONFIG"


@dataclass(frozen=True)
class AppConfig:
    serverName: Optional[str]
    entrypoint: Optional[str]
    skills: List[SkillSpec] = field(default_factory=list)
    envKeys: List[str] = field(default_factory=list)
    distributionName: Optional[str] = None
    binaryEnvVar: Optional[str] = None
    defaultEnvValues: Dict[str, str] = field(default_factory=dict)
    envWarnings: Dict[str, str] = field(default_factory=dict)


def resolveAppConfigPath(explicitPath: Optional[str]) -> pathlib.Path:
    if explicitPath:
        return pathlib.Path(explicitPath).expanduser().resolve(strict=False)

    envPath = os.environ.get(appConfigEnvVar)
    if envPath:
        return pathlib.Path(envPath).expanduser().resolve(strict=False)

    return pathlib.Path.cwd() / defaultAppConfigFilename


def loadAppConfig(explicitPath: Optional[str]) -> AppConfig:
    configPath = resolveAppConfigPath(explicitPath)
    if not configPath.exists():
        raise FileNotFoundError(
            f"App config not found: {configPath}. Pass --app-config, set {appConfigEnvVar}, "
            f"or run from a directory containing {defaultAppConfigFilename}."
        )

    data = json.loads(configPath.read_text(encoding="utf-8"))
    skillData = data.get("skills", [])
    if not isinstance(skillData, list):
        raise ValueError(f"{configPath}: skills must be a list")
    skills = [SkillSpec.fromDict(item) for item in skillData]
    if not skills and not (data.get("serverName") and data.get("entrypoint")):
        raise ValueError(f"{configPath}: configure an MCP server, a skill, or both")

    return AppConfig(
        serverName=data.get("serverName"),
        entrypoint=data.get("entrypoint"),
        skills=skills,
        envKeys=list(data.get("envKeys", [])),
        distributionName=data.get("distributionName"),
        binaryEnvVar=data.get("binaryEnvVar"),
        defaultEnvValues=dict(data.get("defaultEnvValues", {})),
        envWarnings=dict(data.get("envWarnings", {})),
    )


def parseEnvAssignment(text: str) -> Tuple[str, str]:
    if "=" not in text:
        raise ValueError(f"Invalid --env value {text!r}, expected KEY=VALUE")

    key, value = text.split("=", 1)
    return key.strip(), value


def parseEnvFile(path: pathlib.Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        strippedLine = line.strip()
        if not strippedLine or strippedLine.startswith("#"):
            continue

        key, value = parseEnvAssignment(strippedLine)
        env[key] = value

    return env


def inferUvxFromSpec(distributionName: Optional[str]) -> Optional[str]:
    if not distributionName:
        return None

    try:
        distInfo = importlib.metadata.distribution(distributionName)
    except importlib.metadata.PackageNotFoundError:
        return None

    directUrlText = distInfo.read_text("direct_url.json")
    if not directUrlText:
        return None

    try:
        info = json.loads(directUrlText)
    except json.JSONDecodeError:
        return None

    url = info.get("url")
    vcsInfo = info.get("vcs_info") or {}

    if not isinstance(url, str) or not url:
        return None

    # file:// URLs are local paths (e.g. bundled wheels) — useless as a uvx source
    if url.startswith("file://"):
        return None

    if url.startswith("git+"):
        return url

    if isinstance(vcsInfo, dict) and vcsInfo:
        return "git+" + url

    if url.startswith(("https://", "ssh://", "git://")):
        if url.endswith(".git") or "github.com" in url or "gitlab.com" in url or "bitbucket.org" in url:
            return "git+" + url

    return None


def collectEnv(overrides: Dict[str, str], envKeys: List[str]) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for key in envKeys:
        value = overrides.get(key)
        if value is None:
            value = os.environ.get(key)

        if value is None or value == "":
            continue

        env[key] = value

    return env


def buildMcpServerEntry(
    serverName: str,
    uvxFrom: Optional[str],
    entrypoint: str,
    env: Dict[str, str],
) -> Tuple[str, Dict[str, Any]]:
    if uvxFrom:
        args = ["--from", uvxFrom, entrypoint]
    else:
        args = [entrypoint]

    entry: Dict[str, Any] = {"command": "uvx", "args": args}
    if env:
        entry["env"] = env
    return serverName, entry


def warmPyappBinary(binaryPath: Optional[str]) -> None:
    if not binaryPath:
        return
    try:
        subprocess.run(
            [binaryPath, "--help"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except Exception:
        # Best effort only. Registration should still succeed even if warming fails.
        return


targetAliases = {
    "claude-cli": "claude-code",
    "codex-cli": "codex",
    "codex-desktop": "codex",
    "grok": "grok-build",
}


def normalizeInstallTargets(rawTargets: list[str]) -> list[str]:
    if "all" in rawTargets:
        rawTargets = ["claude-desktop", "claude-code", "codex", "grok-build", "openmausbot"]

    targets = []
    for target in rawTargets:
        normalizedTarget = targetAliases.get(target, target)
        if normalizedTarget not in targets:
            targets.append(normalizedTarget)

    allowedTargets = {"claude-desktop", "claude-code", "codex", "grok-build", "openmausbot"}
    invalidTargets = [target for target in targets if target not in allowedTargets]
    if invalidTargets:
        raise ValueError(f"Invalid --target: {', '.join(invalidTargets)}")
    return targets


def buildAgentBackends(
    claudeConfigPath: pathlib.Path,
    codexConfigPath: pathlib.Path,
    grokConfigPath: pathlib.Path,
    openMausBotConfigPath: pathlib.Path,
    cliScope: str,
) -> Dict[str, AgentBackend]:
    """Create one backend per Agent, even when an MCP CLI is unavailable."""
    return {
        "claude-desktop": ClaudeDesktopBackend(claudeConfigPath),
        "claude-code": ClaudeCliBackend(getClaudeCliPath(), cliScope),
        "codex": CodexBackend(codexConfigPath),
        "grok-build": GrokBackend(grokConfigPath),
        "openmausbot": OpenMausBotBackend(openMausBotConfigPath),
    }


class InstallCommand:
    """Runs a single Agent-target loop for every requested component."""

    @classmethod
    def createParser(cls) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Install MCP servers and Agent Skills into supported AI agents."
        )
        parser.add_argument(
            "--app-config",
            dest="appConfigPath",
            help=f"Path to {defaultAppConfigFilename} (optional).",
        )
        parser.add_argument("--config", dest="configPath", help="Claude Desktop JSON config.")
        parser.add_argument("--codex-config", dest="codexConfigPath", help="Codex TOML config.")
        parser.add_argument("--grok-config", dest="grokConfigPath", help="Grok TOML config.")
        parser.add_argument(
            "--openmausbot-config",
            dest="openMausBotConfigPath",
            help="OpenMausBot JSON config (defaults to OMB_DATA_DIR/config.json).",
        )

        parser.add_argument("--server-name", dest="serverName", help="Override serverName.")
        parser.add_argument("--entrypoint", dest="entrypoint", help="Override entrypoint.")
        parser.add_argument("--from", dest="uvxFrom", help="Force uvx --from source.")
        parser.add_argument("--overwrite", action="store_true")
        parser.add_argument("--uninstall", action="store_true")
        parser.add_argument("--print", action="store_true", dest="printOnly")
        parser.add_argument("-y", "--yes", action="store_true", dest="assumeYes")

        parser.add_argument(
            "--component",
            choices=("auto", "mcp", "skill", "all"),
            default="auto",
            help="Choose MCP, Skills, both, or infer from the manifest.",
        )
        parser.add_argument(
            "--scope",
            choices=("user", "project"),
            default="user",
            help="Skill installation scope (separate from --cli-scope).",
        )
        parser.add_argument(
            "--project-dir",
            dest="projectDir",
            help="Project root for project-scoped Skills (defaults to cwd).",
        )

        parser.add_argument(
            "--env",
            dest="envAssignments",
            action="append",
            metavar="KEY=VALUE",
            help="Set an MCP env var; repeatable.",
        )
        parser.add_argument(
            "--env-file",
            dest="envFilePath",
            help="Load MCP env vars from a KEY=VALUE file.",
        )
        parser.add_argument("--cli-scope", dest="cliScope", default="user")
        parser.add_argument(
            "--target",
            dest="installTargets",
            default="all",
            help=(
                "Comma-separated: all, claude-desktop, claude-code, codex, "
                "grok-build, openmausbot. Aliases: claude-cli, codex-cli, "
                "codex-desktop, grok."
            ),
        )

        return parser

    @classmethod
    def fromCLI(cls) -> "InstallCommand":
        args = cls.createParser().parse_args()
        manifestPath = resolveAppConfigPath(args.appConfigPath)
        return cls(args, loadAppConfig(args.appConfigPath), manifestPath)

    def __init__(
        self,
        args: argparse.Namespace,
        config: AppConfig,
        manifestPath: pathlib.Path,
    ):
        self.args = args
        self.config = config
        self.manifestPath = manifestPath

        self.serverName = args.serverName or config.serverName
        self.entrypoint = args.entrypoint or config.entrypoint
        self.installMCP = args.component in ("mcp", "all") or (
            args.component == "auto" and bool(self.serverName or self.entrypoint)
        )
        self.installSkills = args.component in ("skill", "all") or (
            args.component == "auto" and bool(config.skills)
        )

        self.targets = normalizeInstallTargets(
            [part.strip() for part in args.installTargets.split(",") if part.strip()]
        )
        self.projectPath = (
            pathlib.Path(args.projectDir).expanduser().resolve()
            if args.projectDir
            else pathlib.Path.cwd()
        )
        self.homePath = pathlib.Path.home()

    @staticmethod
    def _configPath(override: Optional[str], default: pathlib.Path) -> pathlib.Path:
        if not override:
            return default

        return pathlib.Path(override).expanduser().resolve(strict=False)

    def _buildBackends(self) -> Dict[str, AgentBackend]:
        args = self.args
        return buildAgentBackends(
            self._configPath(args.configPath, getDefaultClaudeDesktopConfigPath()),
            self._configPath(args.codexConfigPath, getDefaultCodexConfigPath()),
            self._configPath(args.grokConfigPath, getDefaultGrokConfigPath()),
            self._configPath(
                args.openMausBotConfigPath,
                getDefaultOpenMausBotConfigPath(),
            ),
            args.cliScope,
        )

    def _validate(self, backends: Dict[str, AgentBackend]) -> None:
        if self.args.printOnly and self.args.uninstall:
            raise ValueError("--print cannot be combined with --uninstall")

        if self.installMCP and not (self.serverName and self.entrypoint):
            raise ValueError("MCP installation requires both serverName and entrypoint")
        if self.installSkills and not self.config.skills:
            raise ValueError("Skill component selected but no skills are configured")

        if self.installSkills:
            for target in self.targets:
                backends[target].skillRoots(
                    self.args.scope,
                    self.homePath,
                    self.projectPath,
                )

    def _collectEnv(self) -> Dict[str, str]:
        overrides: Dict[str, str] = {}
        if self.args.envFilePath:
            envPath = pathlib.Path(self.args.envFilePath).expanduser().resolve(strict=False)
            overrides.update(parseEnvFile(envPath))

        for assignment in self.args.envAssignments or []:
            key, value = parseEnvAssignment(assignment)
            overrides[key] = value

        env = collectEnv(overrides, self.config.envKeys)
        for key, defaultValue in self.config.defaultEnvValues.items():
            env.setdefault(key, defaultValue)

        for key, warning in self.config.envWarnings.items():
            if key not in env:
                print(f"Warning: {warning}")

        return env

    def _buildEntry(self) -> Tuple[Dict[str, Any], Optional[str], Optional[str]]:
        env = self._collectEnv()
        binaryPath = (
            os.environ.get(self.config.binaryEnvVar)
            if self.config.binaryEnvVar
            else None
        )
        uvxFrom = self.args.uvxFrom or inferUvxFromSpec(self.config.distributionName)

        if binaryPath:
            entry: Dict[str, Any] = {"command": binaryPath, "args": []}
            if env:
                entry["env"] = env

            return entry, binaryPath, uvxFrom

        _, entry = buildMcpServerEntry(self.serverName, uvxFrom, self.entrypoint, env)
        return entry, None, uvxFrom

    def _applyMCP(self, backend: AgentBackend, entry: Dict[str, Any]) -> bool:
        if not backend.mcpAvailable:
            print(f"Warning: {backend.label} was not found; skipped MCP registration.")
            return False

        if self.args.printOnly:
            return False

        result = (
            backend.uninstall(self.serverName)
            if self.args.uninstall
            else backend.install(self.serverName, entry, self.args.overwrite)
        )
        action = "Removed" if self.args.uninstall else "Installed"
        preposition = "from" if self.args.uninstall else "into"

        print(f"{action} {self.serverName} {preposition} {result.label} config.")
        print(f"Config: {result.configPath}")

        if result.backupPath:
            print(f"Backup: {result.backupPath}")
        if not result.changed:
            print("No existing entry was found.")

        return True

    def _applySkills(
        self,
        backend: AgentBackend,
        skills,
        handledPaths: set[pathlib.Path],
    ) -> None:
        results = backend.installSkills(
            skills,
            self.args.scope,
            self.homePath,
            self.projectPath,
            handledPaths,
            overwrite=self.args.overwrite,
            uninstall=self.args.uninstall,
            printOnly=self.args.printOnly,
        )

        for result in results:
            if self.args.printOnly:
                print(f"Skill {result.name}: {result.source} -> {result.target}: {result.destination}")
                continue

            action = "Removed" if self.args.uninstall else "Installed"
            if self.args.uninstall and not result.changed:
                action = "Not found"

            print(f"{action} skill {result.name} at {result.destination}")
            if result.backupPath:
                print(f"Backup: {result.backupPath}")

        if results and not self.args.printOnly and not self.args.uninstall and backend.skillNotice:
            print(backend.skillNotice)

    def _printSummary(
        self,
        completedTargets: list[str],
        binaryPath: Optional[str],
        uvxFrom: Optional[str],
    ) -> None:
        if not self.installMCP or self.args.printOnly:
            return

        if any(
            target in completedTargets
            for target in {"claude-desktop", "codex", "grok-build", "openmausbot"}
        ):
            print("\nNext: restart your MCP client or reload its MCP servers.")
        elif "claude-code" in completedTargets:
            print("\nNext: restart Claude Code or reload MCP servers.")

        print(f"Server name: {self.serverName}")
        if binaryPath:
            print(f"Binary: {binaryPath}")
        elif uvxFrom:
            print(f"uvx source: {uvxFrom}")
        else:
            print(f"uvx source: PyPI (uvx {self.entrypoint})")

    def run(self) -> None:
        backends = self._buildBackends()
        self._validate(backends)

        skills = (
            SkillInstaller.prepare(
                self.config.skills,
                self.manifestPath,
                uninstall=self.args.uninstall,
            )
            if self.installSkills
            else []
        )
        entry, binaryPath, uvxFrom = (
            self._buildEntry() if self.installMCP else ({}, None, None)
        )

        if self.args.printOnly and self.installMCP:
            print(json.dumps({self.serverName: entry}, ensure_ascii=True, indent=2))

        completedTargets = []
        handledPaths: set[pathlib.Path] = set()

        for target in self.targets:
            backend = backends[target]
            if self.installMCP and self._applyMCP(backend, entry):
                completedTargets.append(target)

            if self.installSkills:
                self._applySkills(backend, skills, handledPaths)

        if self.installMCP and not self.args.uninstall and not self.args.printOnly:
            warmPyappBinary(binaryPath)

        self._printSummary(completedTargets, binaryPath, uvxFrom)


def main() -> None:
    InstallCommand.fromCLI().run()


if __name__ == "__main__":
    main()
