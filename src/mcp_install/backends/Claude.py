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

"""Claude Desktop and Claude Code backends."""

from __future__ import annotations

import json
import os
import pathlib
import shutil

from typing import Any, Dict, Optional

from .Base import ConfigBackend, InstallResult, JsonMcpBackend, runCommand


def getDefaultClaudeDesktopConfigPath() -> pathlib.Path:
    homePath = pathlib.Path.home()

    if os.name == "nt":
        appData = os.environ.get("APPDATA")
        if appData:
            return pathlib.Path(appData) / "Claude" / "claude_desktop_config.json"
        return homePath / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"

    if os.sys.platform == "darwin":
        return homePath / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"

    xdgConfigHome = os.environ.get("XDG_CONFIG_HOME")
    if xdgConfigHome:
        return pathlib.Path(xdgConfigHome) / "Claude" / "claude_desktop_config.json"

    return homePath / ".config" / "Claude" / "claude_desktop_config.json"


def getClaudeCliPath() -> Optional[str]:
    envPath = os.environ.get("CLAUDE_CLI_PATH") or os.environ.get("CLAUDE_BIN")
    if envPath and pathlib.Path(envPath).exists():
        return envPath

    whichPath = shutil.which("claude")
    if whichPath:
        return whichPath

    homePath = pathlib.Path.home()
    candidatePaths = [
        homePath / ".local" / "bin" / "claude",
        homePath / ".volta" / "bin" / "claude",
        homePath / ".asdf" / "shims" / "claude",
        pathlib.Path("/usr/local/bin/claude"),
        pathlib.Path("/opt/homebrew/bin/claude"),
        pathlib.Path("/usr/bin/claude"),
    ]
    for candidate in candidatePaths:
        if candidate.exists():
            return str(candidate)

    nvmRoots = [os.environ.get("NVM_DIR"), str(homePath / ".nvm")]
    for nvmRoot in nvmRoots:
        if not nvmRoot:
            continue

        nvmPath = pathlib.Path(nvmRoot)
        if not nvmPath.exists():
            continue

        for candidate in nvmPath.glob("versions/node/*/bin/claude"):
            if candidate.exists():
                return str(candidate)

    return None


class ClaudeDesktopBackend(JsonMcpBackend):
    """Claude Desktop's JSON ``mcpServers`` configuration file."""

    def __init__(self, configPath: pathlib.Path):
        super().__init__("claude-desktop", "Claude Desktop", configPath)


class ClaudeCliBackend(ConfigBackend):
    """Claude Code's CLI-based registration (``claude mcp add-json`` / ``remove``).

    Unlike the file-editing backends, there is no config file for this process
    to read or write directly — the `claude` CLI owns that. `configPath` holds
    the CLI executable's own path instead, purely for the install/uninstall
    summary output; `backupPath` is always None since there is no file to back up.
    """

    def __init__(self, cliPath: str, scope: str):
        super().__init__("claude-code", f"Claude Code CLI (scope: {scope})", pathlib.Path(cliPath))
        self.cliPath = cliPath
        self.scope = scope

    def install(self, serverName: str, entry: Dict[str, Any], overwrite: bool) -> InstallResult:
        command = [
            self.cliPath, "mcp", "add-json", "-s", self.scope, serverName,
            json.dumps(entry, ensure_ascii=True),
        ]

        if overwrite:
            runCommand([self.cliPath, "mcp", "remove", "-s", self.scope, serverName], allowFailure=True)

        runCommand(command)

        return InstallResult(self.target, self.label, self.configPath, None, changed=True)

    def uninstall(self, serverName: str) -> InstallResult:
        runCommand([self.cliPath, "mcp", "remove", "-s", self.scope, serverName], allowFailure=True)

        return InstallResult(self.target, self.label, self.configPath, None, changed=True)
