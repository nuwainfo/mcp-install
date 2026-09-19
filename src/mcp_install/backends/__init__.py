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

"""Native MCP-client configuration backends.

MCP standardizes the protocol between a host and a server, but each host owns
its own registration format and location. ``Base`` holds the generic,
client-agnostic mechanisms (JSON/TOML config-file editing, the
``ConfigBackend`` interface); ``Claude``/``Codex``/``Grok`` hold the thin,
client-specific classes and default-config-path lookups built on top of it.
"""

from .Base import (
    ConfigBackend,
    InstallResult,
    JsonMcpBackend,
    TomlMcpBackend,
    backupFile,
    buildTomlServerConfig,
    readJsonFile,
    removeTomlServerConfig,
    runCommand,
    tomlArray,
    tomlKey,
    tomlString,
    writeJsonAtomic,
    writeTextAtomic,
)
from .Claude import ClaudeCliBackend, ClaudeDesktopBackend, getClaudeCliPath, getDefaultClaudeDesktopConfigPath
from .Codex import CodexBackend, getDefaultCodexConfigPath
from .Grok import GrokBackend, getDefaultGrokConfigPath

__all__ = [
    "ConfigBackend",
    "InstallResult",
    "JsonMcpBackend",
    "TomlMcpBackend",
    "backupFile",
    "buildTomlServerConfig",
    "readJsonFile",
    "removeTomlServerConfig",
    "runCommand",
    "tomlArray",
    "tomlKey",
    "tomlString",
    "writeJsonAtomic",
    "writeTextAtomic",
    "ClaudeCliBackend",
    "ClaudeDesktopBackend",
    "getClaudeCliPath",
    "getDefaultClaudeDesktopConfigPath",
    "CodexBackend",
    "getDefaultCodexConfigPath",
    "GrokBackend",
    "getDefaultGrokConfigPath",
]
