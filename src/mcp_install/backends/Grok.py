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

"""Grok Build backend."""

from __future__ import annotations

import os
import pathlib

from .Base import TomlMcpBackend


def getDefaultGrokConfigPath() -> pathlib.Path:
    grokHome = os.environ.get("GROK_HOME")
    if grokHome:
        return pathlib.Path(grokHome).expanduser() / "config.toml"

    return pathlib.Path.home() / ".grok" / "config.toml"


class GrokBackend(TomlMcpBackend):
    """Grok Build's ``mcp_servers`` TOML configuration file."""

    def __init__(self, configPath: pathlib.Path):
        super().__init__("grok-build", "Grok Build", configPath)
