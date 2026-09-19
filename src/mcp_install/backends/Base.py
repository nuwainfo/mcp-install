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

"""Generic, client-agnostic MCP install-backend mechanisms.

MCP standardizes the protocol between a host and a server, but each host owns
its own registration format and location. This module holds the two shared
mechanisms every file-editing client reuses — a JSON ``mcpServers`` file and a
TOML ``mcp_servers`` file — plus the ``ConfigBackend`` interface both
implement and the raw file/TOML helpers they're built on. Nothing in this
module names a specific client (Claude, Codex, ...); that lives in its own
sibling module (``Claude.py``, ``Codex.py``, ``Grok.py``, ...) which imports
from here.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import re
import subprocess

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


def runCommand(command: list[str], allowFailure: bool = False) -> None:
    """Run a CLI-based backend's command; raise with its output on failure."""
    result = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode == 0:
        return

    if allowFailure:
        return

    stderrText = result.stderr.strip()
    stdoutText = result.stdout.strip()
    detailParts = [part for part in [stderrText, stdoutText] if part]
    detail = detailParts[0] if detailParts else "Unknown error"
    raise RuntimeError(f"Command failed: {' '.join(command)}: {detail}")


def readJsonFile(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    rawText = path.read_text(encoding="utf-8").strip()
    if not rawText:
        return {}

    try:
        data = json.loads(rawText)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(data).__name__}")

    return data


def writeJsonAtomic(path: pathlib.Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tempPath = path.with_suffix(path.suffix + ".tmp")
    tempPath.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tempPath.replace(path)


def writeTextAtomic(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tempPath = path.with_suffix(path.suffix + ".tmp")
    tempPath.write_text(text, encoding="utf-8")
    tempPath.replace(path)


def backupFile(path: pathlib.Path) -> Optional[pathlib.Path]:
    if not path.exists():
        return None

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backupPath = path.with_suffix(path.suffix + f".bak_{timestamp}")
    backupPath.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backupPath


def tomlString(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def tomlArray(values: list[str]) -> str:
    return "[" + ", ".join(tomlString(value) for value in values) + "]"


def tomlKey(key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key

    return tomlString(key)


def buildTomlServerConfig(serverName: str, entry: Dict[str, Any]) -> str:
    key = tomlKey(serverName)
    lines = [
        f"[mcp_servers.{key}]",
        f"command = {tomlString(str(entry['command']))}",
    ]

    args = entry.get("args")
    if args:
        lines.append(f"args = {tomlArray([str(arg) for arg in args])}")

    env = entry.get("env")
    if env:
        lines.append("")
        lines.append(f"[mcp_servers.{key}.env]")
        for envKey in sorted(env.keys()):
            lines.append(f"{tomlKey(envKey)} = {tomlString(str(env[envKey]))}")

    return "\n".join(lines) + "\n"


def removeTomlServerConfig(existingText: str, serverName: str) -> Tuple[str, bool]:
    key = tomlKey(serverName)
    sectionPrefixes = [f"mcp_servers.{key}", f"mcp_servers.{tomlString(serverName)}"]
    lines = existingText.splitlines(keepends=True)
    keptLines = []
    skipping = False
    removed = False

    for line in lines:
        match = re.match(r"\s*\[([^\]]+)\]\s*(?:#.*)?$", line)
        if match:
            sectionName = match.group(1).strip()
            skipping = any(
                sectionName == prefix or sectionName.startswith(prefix + ".")
                for prefix in sectionPrefixes
            )
            if skipping:
                removed = True
                continue
        if skipping:
            continue
        keptLines.append(line)

    return "".join(keptLines).rstrip() + ("\n" if keptLines else ""), removed


@dataclass(frozen=True)
class InstallResult:
    target: str
    label: str
    configPath: pathlib.Path
    backupPath: Optional[pathlib.Path]
    changed: bool


class ConfigBackend:
    """A client-owned config file (or CLI) that can register one stdio MCP server."""

    def __init__(self, target: str, label: str, configPath: pathlib.Path):
        self.target = target
        self.label = label
        self.configPath = configPath

    def install(self, serverName: str, entry: Dict[str, Any], overwrite: bool) -> InstallResult:
        raise NotImplementedError

    def uninstall(self, serverName: str) -> InstallResult:
        raise NotImplementedError


class JsonMcpBackend(ConfigBackend):
    """A client's JSON ``mcpServers`` configuration file (e.g. Claude Desktop)."""

    def install(self, serverName: str, entry: Dict[str, Any], overwrite: bool) -> InstallResult:
        config = readJsonFile(self.configPath)
        mcpServers = config.get("mcpServers")
        if mcpServers is None:
            mcpServers = {}
            config["mcpServers"] = mcpServers
        if not isinstance(mcpServers, dict):
            raise ValueError(f"mcpServers in {self.configPath} must be a JSON object")
        if serverName in mcpServers and not overwrite:
            raise RuntimeError(
                f"mcpServers['{serverName}'] already exists in {self.configPath}. "
                "Re-run with --overwrite to replace it."
            )

        mcpServers[serverName] = entry
        backupPath = backupFile(self.configPath)
        writeJsonAtomic(self.configPath, config)
        return InstallResult(self.target, self.label, self.configPath, backupPath, changed=True)

    def uninstall(self, serverName: str) -> InstallResult:
        config = readJsonFile(self.configPath)
        mcpServers = config.get("mcpServers")
        if not isinstance(mcpServers, dict) or serverName not in mcpServers:
            return InstallResult(self.target, self.label, self.configPath, None, changed=False)

        del mcpServers[serverName]
        backupPath = backupFile(self.configPath)
        writeJsonAtomic(self.configPath, config)
        return InstallResult(self.target, self.label, self.configPath, backupPath, changed=True)


class TomlMcpBackend(ConfigBackend):
    """A client's ``mcp_servers`` TOML configuration file (e.g. Codex, Grok Build)."""

    def install(self, serverName: str, entry: Dict[str, Any], overwrite: bool) -> InstallResult:
        configText = self.configPath.read_text(encoding="utf-8") if self.configPath.exists() else ""
        configWithoutServer, removed = removeTomlServerConfig(configText, serverName)
        if removed and not overwrite:
            raise RuntimeError(
                f"mcp_servers['{serverName}'] already exists in {self.configPath}. "
                "Re-run with --overwrite to replace it."
            )

        serverText = buildTomlServerConfig(serverName, entry)
        updatedText = configWithoutServer.rstrip() + "\n\n" + serverText if configWithoutServer.strip() else serverText
        backupPath = backupFile(self.configPath)
        writeTextAtomic(self.configPath, updatedText)
        return InstallResult(self.target, self.label, self.configPath, backupPath, changed=True)

    def uninstall(self, serverName: str) -> InstallResult:
        configText = self.configPath.read_text(encoding="utf-8") if self.configPath.exists() else ""
        updatedText, removed = removeTomlServerConfig(configText, serverName)
        if not removed:
            return InstallResult(self.target, self.label, self.configPath, None, changed=False)

        backupPath = backupFile(self.configPath)
        writeTextAtomic(self.configPath, updatedText)
        return InstallResult(self.target, self.label, self.configPath, backupPath, changed=True)
