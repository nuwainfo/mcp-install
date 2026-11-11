"""OpenCode's MCP V2 JSONC format and native Agent Skill directories."""

import contextlib
import io
import json
import os
import pathlib
import tempfile
import unittest

from unittest import mock

from mcp_install.Install import InstallCommand, loadAppConfig, normalizeInstallTargets
from mcp_install.backends import OpenCodeBackend, getDefaultOpenCodeConfigPath
from mcp_install.backends.Jsonc import JsoncDocument
from mcp_install.skills import SkillInstaller, SkillSpec


class OpenCodeTest(unittest.TestCase):

    def setUp(self):
        self.tempDirectory = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempDirectory.cleanup)

        self.base = pathlib.Path(self.tempDirectory.name)
        self.home = self.base / "home"
        self.project = self.base / "project"
        self.project.mkdir()
        self.configPath = self.base / "opencode.jsonc"

        source = self.project / "skills" / "sample"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text(
            "---\nname: sample\ndescription: Example\n---\n",
            encoding="utf-8",
        )
        (source / "assets").mkdir()
        (source / "assets" / "example.txt").write_text("example asset")

        self.manifest = self.project / "install.config.json"
        xdgPatch = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": ""})
        xdgPatch.start()
        self.addCleanup(xdgPatch.stop)

        self.entry = {
            "command": "uvx",
            "args": ["--from", "git+https://example.com/repo", "example-mcp"],
            "env": {"API_TOKEN": "secret"},
        }

    def testExistingJsoncRetainsCommentsAndOtherServers(self):
        self.configPath.write_text(
            '{\n'
            '  // Keep this comment\n'
            '  "model": "provider/model",\n'
            '  "url": "https://example.com/x",\n'
            '  "mcp": {\n'
            '    "timeout": {"catalog": 4000,},\n'
            '    "servers": {\n'
            '      // Existing MCP must be preserved\n'
            '      "other": {"type": "local", "command": ["node", "a"],},\n'
            '    },\n'
            '  },\n'
            '}\n',
            encoding="utf-8",
        )
        installer = OpenCodeBackend(self.configPath)
        result = installer.install("sample", self.entry, overwrite=False)

        savedText = self.configPath.read_text(encoding="utf-8")
        saved = JsoncDocument(savedText).data

        self.assertIn("// Keep this comment", savedText)
        self.assertIn("// Existing MCP must be preserved", savedText)
        self.assertEqual("provider/model", saved["model"])
        self.assertEqual("https://example.com/x", saved["url"])

        self.assertEqual(4000, saved["mcp"]["timeout"]["catalog"])
        self.assertEqual(["node", "a"], saved["mcp"]["servers"]["other"]["command"])

        server = saved["mcp"]["servers"]["sample"]
        self.assertEqual("local", server["type"])
        self.assertEqual(
            ["uvx", "--from", "git+https://example.com/repo", "example-mcp"],
            server["command"],
        )
        self.assertEqual({"API_TOKEN": "secret"}, server["environment"])
        self.assertNotIn("enabled", server)

        self.assertTrue(result.backupPath.exists())
        self.assertEqual(
            result.backupPath.read_text(encoding="utf-8"),
            '{\n'
            '  // Keep this comment\n'
            '  "model": "provider/model",\n'
            '  "url": "https://example.com/x",\n'
            '  "mcp": {\n'
            '    "timeout": {"catalog": 4000,},\n'
            '    "servers": {\n'
            '      // Existing MCP must be preserved\n'
            '      "other": {"type": "local", "command": ["node", "a"],},\n'
            '    },\n'
            '  },\n'
            '}\n',
        )

    def testOverwriteAndUninstallOnlySelectedServer(self):
        initial = {
            "mcp": {
                "servers": {
                    "other": {"type": "local", "command": ["node", "other"]},
                    "sample": {"type": "local", "command": ["node", "old"]},
                }
            },
            "theme": "light",
        }
        self.configPath.write_text(json.dumps(initial))

        backend = OpenCodeBackend(self.configPath)
        with self.assertRaises(RuntimeError):
            backend.install("sample", self.entry, overwrite=False)

        self.assertEqual(initial, JsoncDocument(self.configPath.read_text()).data)

        backend.install("sample", self.entry, overwrite=True)
        updated = JsoncDocument(self.configPath.read_text()).data
        self.assertEqual("uvx", updated["mcp"]["servers"]["sample"]["command"][0])

        removed = backend.uninstall("sample")
        cleaned = JsoncDocument(self.configPath.read_text()).data
        self.assertTrue(removed.changed)
        self.assertNotIn("sample", cleaned["mcp"]["servers"])
        self.assertEqual(initial["mcp"]["servers"]["other"], cleaned["mcp"]["servers"]["other"])
        self.assertEqual("light", cleaned["theme"])

        missing = backend.uninstall("not-registered")
        self.assertFalse(missing.changed)
        self.assertIsNone(missing.backupPath)

    def testCreatesV2StructureInEmptyConfig(self):
        backend = OpenCodeBackend(self.configPath)

        installed = backend.install("sample", {"command": "sample", "args": []}, False)
        self.assertIsNone(installed.backupPath)

        saved = JsoncDocument(self.configPath.read_text()).data
        self.assertEqual(
            {"type": "local", "command": ["sample"]},
            saved["mcp"]["servers"]["sample"],
        )

        backend.uninstall("sample")
        self.assertEqual({}, JsoncDocument(self.configPath.read_text()).data["mcp"]["servers"])

    def testExistingSingleServerWithTrailingCommaIsRemoved(self):
        self.configPath.write_text(
            '{\n'
            '  "mcp": {\n'
            '    "servers": {\n'
            '      "sample": {"type": "local", "command": ["uvx", "a"]},\n'
            '    },\n'
            '  },\n'
            '}\n'
        )
        backend = OpenCodeBackend(self.configPath)
        self.assertTrue(backend.uninstall("sample").changed)

        saved = JsoncDocument(self.configPath.read_text()).data
        self.assertEqual({}, saved["mcp"]["servers"])

    def testInvalidConfigFailsWithoutWriting(self):
        invalidText = '{"mcp": {"servers": []}}'
        self.configPath.write_text(invalidText)
        backend = OpenCodeBackend(self.configPath)

        with self.assertRaisesRegex(ValueError, "mcp.servers"):
            backend.install("sample", self.entry, overwrite=False)

        self.assertEqual(invalidText, self.configPath.read_text())
        self.assertEqual([], list(self.base.glob("opencode.jsonc.bak_*")))

    def testDefaultPathHonorsXdgAndExistingJson(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.base)}):
            directory = self.base / "opencode"
            directory.mkdir()

            self.assertEqual(
                directory / "opencode.jsonc",
                getDefaultOpenCodeConfigPath(),
            )

            jsonPath = directory / "opencode.json"
            jsonPath.write_text("{}")
            self.assertEqual(jsonPath, getDefaultOpenCodeConfigPath())

            jsoncPath = directory / "opencode.jsonc"
            jsoncPath.write_text("{}")
            with self.assertRaisesRegex(ValueError, "Both OpenCode"):
                getDefaultOpenCodeConfigPath()

    def testNativeSkillRootsAndFullDirectoryCopy(self):
        prepared = SkillInstaller.prepare(
            [SkillSpec("skills/sample")],
            self.manifest,
        )
        backend = OpenCodeBackend(self.configPath)

        result = backend.installSkills(
            prepared,
            "user",
            self.home,
            self.project,
            set(),
        )
        self.assertEqual(1, len(result))
        self.assertEqual("opencode", result[0].target)

        userSkill = self.home / ".config/opencode/skills/sample"
        self.assertEqual("example asset", (userSkill / "assets/example.txt").read_text())

        backend.installSkills(
            prepared,
            "project",
            self.home,
            self.project,
            set(),
        )
        projectSkill = self.project / ".opencode/skills/sample"
        self.assertTrue((projectSkill / "SKILL.md").is_file())

    def testXdgSkillRootUsesConfiguredDirectory(self):
        backend = OpenCodeBackend(self.configPath)

        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.base)}):
            self.assertEqual(
                [self.base / "opencode/skills"],
                backend.skillRoots("user", self.home, self.project),
            )

            self.assertEqual(
                [self.project / ".opencode/skills"],
                backend.skillRoots("project", self.home, self.project),
            )

    def testUnifiedCLIInstallsBothComponents(self):
        self.manifest.write_text(json.dumps({
            "serverName": "sample",
            "entrypoint": "sample-mcp",
            "skills": [{"path": "skills/sample"}],
        }))
        args = InstallCommand.createParser().parse_args([
            "--app-config", str(self.manifest),
            "--target", "opencode",
            "--opencode-config", str(self.configPath),
        ])
        command = InstallCommand(args, loadAppConfig(str(self.manifest)), self.manifest)
        command.homePath = self.home

        with contextlib.redirect_stdout(io.StringIO()):
            command.run()

        servers = JsoncDocument(self.configPath.read_text()).data["mcp"]["servers"]
        self.assertEqual(["uvx", "sample-mcp"], servers["sample"]["command"])
        self.assertTrue((self.home / ".config/opencode/skills/sample/SKILL.md").is_file())

        args.uninstall = True
        with contextlib.redirect_stdout(io.StringIO()):
            command.run()

        self.assertNotIn(
            "sample",
            JsoncDocument(self.configPath.read_text()).data["mcp"]["servers"],
        )
        self.assertFalse((self.home / ".config/opencode/skills/sample").exists())

    def testSkillOnlyIgnoresAmbiguousMcpConfiguration(self):
        self.manifest.write_text(
            json.dumps({"skills": [{"path": "skills/sample"}]})
        )
        args = InstallCommand.createParser().parse_args([
            "--app-config", str(self.manifest),
            "--component", "skill",
            "--target", "opencode",
        ])
        command = InstallCommand(args, loadAppConfig(str(self.manifest)), self.manifest)
        command.homePath = self.home

        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.base)}):
            configDirectory = self.base / "opencode"
            configDirectory.mkdir()
            (configDirectory / "opencode.json").write_text("{}")
            (configDirectory / "opencode.jsonc").write_text("{}")

            with contextlib.redirect_stdout(io.StringIO()):
                command.run()

            self.assertTrue(
                (configDirectory / "skills/sample/SKILL.md").is_file()
            )

    def testAllTargetsIncludeOpenCode(self):
        self.assertIn("opencode", normalizeInstallTargets(["all"]))


if __name__ == "__main__":
    unittest.main()
