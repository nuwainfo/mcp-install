"""End-to-end CLI orchestration uses the same Agent backend for MCP and Skills."""

import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from mcp_install.Install import InstallCommand, loadAppConfig


class UnifiedBackendTest(unittest.TestCase):

    def setUp(self):
        self.tempDirectory = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempDirectory.cleanup)

        self.base = pathlib.Path(self.tempDirectory.name)
        self.project = self.base / "project"
        self.project.mkdir()
        self.home = self.base / "home"

        skill = self.project / "skills/hello"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: hello\ndescription: Example\n---\n"
        )
        (skill / "assets").mkdir()
        (skill / "assets/example.txt").write_text("full skill")

        self.manifest = self.project / "install.config.json"
        self.configPath = self.base / "openmausbot.json"

    def runInstall(self, *arguments):
        args = InstallCommand.createParser().parse_args(
            ["--app-config", str(self.manifest), *arguments]
        )
        command = InstallCommand(args, loadAppConfig(str(self.manifest)), self.manifest)
        command.homePath = self.home

        with contextlib.redirect_stdout(io.StringIO()) as output:
            command.run()

        return output.getvalue()

    def testSkillOnlyDoesNotRequireClaudeCLI(self):
        self.manifest.write_text('{"skills": [{"path": "skills/hello"}]}')

        with mock.patch("mcp_install.Install.getClaudeCliPath", return_value=None):
            output = self.runInstall("--target", "claude-code")

        self.assertIn("Installed skill hello", output)
        self.assertTrue((self.home / ".claude/skills/hello/SKILL.md").exists())

    def testMCPAndSkillsUseOneOpenMausBotBackend(self):
        self.manifest.write_text(
            json.dumps({
                "serverName": "example",
                "entrypoint": "example-mcp",
                "skills": [{"path": "skills/hello"}],
            })
        )
        self.configPath.write_text(
            json.dumps({"instances": {"other": {"driver": "codex"}}})
        )

        self.runInstall(
            "--target", "openmausbot",
            "--openmausbot-config", str(self.configPath),
        )

        config = json.loads(self.configPath.read_text())
        self.assertIn("other", config["instances"])
        self.assertEqual(
            "uvx",
            config["mcpServers"]["example"]["command"],
        )
        self.assertTrue(
            (self.home / ".claude/skills/hello/SKILL.md").exists()
        )
        self.assertEqual(
            "full skill",
            (self.home / ".codex/skills/hello/assets/example.txt").read_text(),
        )

        self.runInstall(
            "--target", "openmausbot",
            "--openmausbot-config", str(self.configPath),
            "--uninstall",
        )
        config = json.loads(self.configPath.read_text())
        self.assertNotIn("example", config["mcpServers"])
        self.assertFalse((self.home / ".claude/skills/hello").exists())

    def testOverlappingTargetsDoNotReplaceSameSkillTwice(self):
        self.manifest.write_text('{"skills": [{"path": "skills/hello"}]}')

        self.runInstall("--target", "claude-code,openmausbot")

        self.assertEqual(
            [],
            list((self.home / ".claude/skills").glob("hello.bak_*")),
        )
        self.assertTrue((self.home / ".codex/skills/hello/SKILL.md").exists())

    def testUnsupportedScopeFailsBeforeMCPModification(self):
        self.manifest.write_text(
            json.dumps({
                "serverName": "example",
                "entrypoint": "example-mcp",
                "skills": [{"path": "skills/hello"}],
            })
        )

        with self.assertRaisesRegex(ValueError, "project-scoped"):
            self.runInstall(
                "--target", "openmausbot",
                "--scope", "project",
                "--openmausbot-config", str(self.configPath),
            )

        self.assertFalse(self.configPath.exists())


if __name__ == "__main__":
    unittest.main()
