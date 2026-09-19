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
"""Tests for the external app-manifest mechanism (`install.config.json`)."""

import pathlib
import tempfile
import unittest

from mcp_install.Install import collectEnv, inferUvxFromSpec, loadAppConfig, parseEnvAssignment, parseEnvFile


class AppConfigTest(unittest.TestCase):

    def testLoadAppConfigReadsManifest(self):
        with tempfile.TemporaryDirectory() as tempDir:
            configPath = pathlib.Path(tempDir) / "install.config.json"
            configPath.write_text(
                '{"serverName": "demo", "entrypoint": "demo-mcp", "distributionName": "demo-mcp", '
                '"envKeys": ["DEMO_TOKEN"], "binaryEnvVar": "DEMO_BINARY", '
                '"defaultEnvValues": {"DEMO_TOKEN": "fallback"}, "envWarnings": {"DEMO_TOKEN": "set a token"}}',
                encoding="utf-8",
            )
            appConfig = loadAppConfig(str(configPath))

        self.assertEqual(appConfig.serverName, "demo")
        self.assertEqual(appConfig.entrypoint, "demo-mcp")
        self.assertEqual(appConfig.distributionName, "demo-mcp")
        self.assertEqual(appConfig.envKeys, ["DEMO_TOKEN"])
        self.assertEqual(appConfig.binaryEnvVar, "DEMO_BINARY")
        self.assertEqual(appConfig.defaultEnvValues, {"DEMO_TOKEN": "fallback"})
        self.assertEqual(appConfig.envWarnings, {"DEMO_TOKEN": "set a token"})

    def testLoadAppConfigMissingFileRaises(self):
        with self.assertRaises(FileNotFoundError):
            loadAppConfig("/nonexistent/install.config.json")

    def testLoadAppConfigRequiresServerNameAndEntrypoint(self):
        with tempfile.TemporaryDirectory() as tempDir:
            configPath = pathlib.Path(tempDir) / "install.config.json"
            configPath.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                loadAppConfig(str(configPath))

    def testParseEnvAssignmentSplitsOnFirstEquals(self):
        self.assertEqual(parseEnvAssignment("KEY=a=b"), ("KEY", "a=b"))
        with self.assertRaises(ValueError):
            parseEnvAssignment("NO_EQUALS_SIGN")

    def testParseEnvFileSkipsBlankLinesAndComments(self):
        with tempfile.TemporaryDirectory() as tempDir:
            envPath = pathlib.Path(tempDir) / ".env"
            envPath.write_text("# comment\n\nALLOWED_BASE_DIR=/tmp/shared\nEXAMPLE_TOKEN=1\n", encoding="utf-8")
            self.assertEqual(
                parseEnvFile(envPath),
                {"ALLOWED_BASE_DIR": "/tmp/shared", "EXAMPLE_TOKEN": "1"},
            )

    def testCollectEnvOnlyForwardsConfiguredKeys(self):
        env = collectEnv({"ALLOWED_BASE_DIR": "/tmp", "UNRELATED": "ignored"}, ["ALLOWED_BASE_DIR", "EXAMPLE_TOKEN"])
        self.assertEqual(env, {"ALLOWED_BASE_DIR": "/tmp"})

    def testInferUvxFromSpecReturnsNoneWithoutDistributionName(self):
        self.assertIsNone(inferUvxFromSpec(None))


if __name__ == "__main__":
    unittest.main()
