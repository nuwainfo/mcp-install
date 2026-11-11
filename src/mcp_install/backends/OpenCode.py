"""OpenCode backend for local MCP servers and native Agent Skills."""

from __future__ import annotations

import os
import pathlib

from typing import Any, Dict

from .Base import AgentBackend, InstallResult, backupFile, writeTextAtomic
from .Jsonc import JsoncDocument


def getDefaultOpenCodeConfigPath() -> pathlib.Path:
    configHome = os.environ.get("XDG_CONFIG_HOME")
    root = (
        pathlib.Path(configHome).expanduser()
        if configHome
        else pathlib.Path.home() / ".config"
    )
    directory = root / "opencode"

    jsonPath = directory / "opencode.json"
    jsoncPath = directory / "opencode.jsonc"
    if jsonPath.exists() and jsoncPath.exists():
        raise ValueError(
            "Both OpenCode configuration files exist. "
            "Choose one explicitly with --opencode-config."
        )

    if jsonPath.exists():
        return jsonPath
    if jsoncPath.exists():
        return jsoncPath

    return jsoncPath


class OpenCodeBackend(AgentBackend):
    """Owns OpenCode's MCP registrations and per-scope Skill directories."""

    _userSkillPaths = (".config/opencode/skills",)
    _projectSkillPaths = (".opencode/skills",)

    def __init__(self, configPath: pathlib.Path):
        super().__init__("opencode", "OpenCode", configPath)

    def skillRoots(
        self,
        scope: str,
        homePath: pathlib.Path,
        projectPath: pathlib.Path,
    ) -> list[pathlib.Path]:
        if scope == "user":
            configHome = os.environ.get("XDG_CONFIG_HOME")
            if configHome:
                return [pathlib.Path(configHome).expanduser() / "opencode" / "skills"]

        return super().skillRoots(scope, homePath, projectPath)

    @staticmethod
    def _buildLocalServer(entry: Dict[str, Any]) -> Dict[str, Any]:
        command = [entry["command"], *entry.get("args", [])]
        server: Dict[str, Any] = {
            "type": "local",
            "command": command,
        }

        if entry.get("env"):
            server["environment"] = entry["env"]

        return server

    def _readDocument(self) -> JsoncDocument:
        text = (
            self.configPath.read_text(encoding="utf-8")
            if self.configPath.exists()
            else "{}\n"
        )

        return JsoncDocument(text)

    @staticmethod
    def _serverMap(document: JsoncDocument) -> dict:
        config = document.data
        mcp = config.get("mcp", {})
        if not isinstance(mcp, dict):
            raise ValueError("OpenCode 'mcp' configuration must be an object")

        servers = mcp.get("servers", {})
        if not isinstance(servers, dict):
            raise ValueError("OpenCode 'mcp.servers' configuration must be an object")

        return servers

    def install(self, serverName: str, entry: Dict[str, Any], overwrite: bool) -> InstallResult:
        document = self._readDocument()
        servers = self._serverMap(document)

        if serverName in servers and not overwrite:
            raise RuntimeError(
                f"OpenCode mcp.servers[{serverName!r}] already exists in "
                f"{self.configPath}; use --overwrite to replace it."
            )

        document.set(("mcp", "servers", serverName), self._buildLocalServer(entry))
        backupPath = backupFile(self.configPath)
        writeTextAtomic(self.configPath, document.text)

        return InstallResult(
            self.target, self.label, self.configPath, backupPath, changed=True
        )

    def uninstall(self, serverName: str) -> InstallResult:
        document = self._readDocument()
        self._serverMap(document)

        if not document.remove(("mcp", "servers", serverName)):
            return InstallResult(
                self.target, self.label, self.configPath, None, changed=False
            )

        backupPath = backupFile(self.configPath)
        writeTextAtomic(self.configPath, document.text)

        return InstallResult(
            self.target, self.label, self.configPath, backupPath, changed=True
        )
