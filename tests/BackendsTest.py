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
"""Tests for the generic config-backend mechanism and per-client backends."""

import os
import pathlib
import tempfile
import unittest

from mcp_install.backends import TomlMcpBackend, buildTomlServerConfig, getDefaultGrokConfigPath, removeTomlServerConfig
from mcp_install.Install import normalizeInstallTargets


class TomlBackendTest(unittest.TestCase):

    def testBuildTomlServerConfig(self):
        entry = {
            "command": "uvx",
            "args": ["--from", "git+https://github.com/nuwainfo/example-mcp", "example-mcp"],
            "env": {"EXAMPLE_TOKEN": "1"},
        }
        text = buildTomlServerConfig("example", entry)
        self.assertIn("[mcp_servers.example]", text)
        self.assertIn('command = "uvx"', text)
        self.assertIn('args = ["--from", "git+https://github.com/nuwainfo/example-mcp", "example-mcp"]', text)
        self.assertIn("[mcp_servers.example.env]", text)
        self.assertIn('EXAMPLE_TOKEN = "1"', text)

    def testRemoveTomlServerConfigOnlyRemovesTargetServer(self):
        existingText = """
[mcp_servers.other]
command = "npx"

[mcp_servers.example]
command = "uvx"

[mcp_servers.example.env]
EXAMPLE_TOKEN = "1"

[mcp_servers.after]
command = "node"
""".lstrip()
        updatedText, removed = removeTomlServerConfig(existingText, "example")
        self.assertTrue(removed)
        self.assertNotIn("[mcp_servers.example]", updatedText)
        self.assertNotIn("[mcp_servers.example.env]", updatedText)
        self.assertIn("[mcp_servers.other]", updatedText)
        self.assertIn("[mcp_servers.after]", updatedText)

    def testTomlBackendRejectsExistingWithoutOverwrite(self):
        with tempfile.TemporaryDirectory() as tempDir:
            configPath = pathlib.Path(tempDir) / "config.toml"
            installer = TomlMcpBackend("codex", "Codex", configPath)
            entry = {"command": "uvx", "args": ["example-mcp"], "env": {}}
            installer.install("example", entry, overwrite=False)
            with self.assertRaises(RuntimeError):
                installer.install("example", entry, overwrite=False)

    def testGrokInstallerWritesCompatibleMcpServerToml(self):
        with tempfile.TemporaryDirectory() as tempDir:
            configPath = pathlib.Path(tempDir) / "config.toml"
            installer = TomlMcpBackend("grok-build", "Grok Build", configPath)
            entry = {
                "command": "example-mcp.exe",
                "args": [],
                "env": {"EXAMPLE_TOKEN": "1"},
            }
            existingText = '[mcp_servers.other]\ncommand = "npx"\n'

            configPath.write_text(existingText, encoding="utf-8")
            result = installer.install("example", entry, overwrite=False)
            updatedText = configPath.read_text(encoding="utf-8")

            self.assertEqual(result.target, "grok-build")
            self.assertIn('[mcp_servers.other]', updatedText)
            self.assertIn('[mcp_servers.example]', updatedText)
            self.assertIn('command = "example-mcp.exe"', updatedText)
            self.assertIn('[mcp_servers.example.env]', updatedText)
            self.assertIn('EXAMPLE_TOKEN = "1"', updatedText)

    def testDefaultGrokConfigPathHonorsGrokHome(self):
        previousValue = os.environ.get("GROK_HOME")
        try:
            os.environ["GROK_HOME"] = "C:/test/grok-home"
            self.assertEqual(getDefaultGrokConfigPath(), pathlib.Path("C:/test/grok-home/config.toml"))
        finally:
            if previousValue is None:
                os.environ.pop("GROK_HOME", None)
            else:
                os.environ["GROK_HOME"] = previousValue

    def testLegacyTargetsResolveToCanonicalBackends(self):
        targets = normalizeInstallTargets([
            "claude-cli",
            "codex-cli",
            "codex-desktop",
            "grok",
        ])
        self.assertEqual(targets, ["claude-code", "codex", "grok-build"])


if __name__ == "__main__":
    unittest.main()
