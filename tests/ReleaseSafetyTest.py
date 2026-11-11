"""Release-critical regressions for preview, scope, YAML and CLI failures."""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

from unittest import mock

from mcp_install.Install import InstallCommand, loadAppConfig
from mcp_install.backends import ClaudeCliBackend
from mcp_install.skills import SkillInstaller, SkillSpec


class ReleaseSafetyTest(unittest.TestCase):

    def setUp(self):
        self.tempDirectory = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempDirectory.cleanup)

        self.base = pathlib.Path(self.tempDirectory.name)
        self.home = self.base / "home"
        self.project = self.base / "project"
        self.project.mkdir()

        self.manifest = self.project / "install.config.json"
        self.skillFile = self.project / "skills" / "hello" / "SKILL.md"
        self.skillFile.parent.mkdir(parents=True)
        self.skillFile.write_text(
            "---\nname: hello\ndescription: A valid example.\n---\nInstructions.\n"
        )

    def _runCLI(self, *arguments) -> str:
        args = InstallCommand.createParser().parse_args([
            "--app-config",
            str(self.manifest),
            *arguments,
        ])
        command = InstallCommand(
            args,
            loadAppConfig(str(self.manifest)),
            self.manifest,
        )
        command.homePath = self.home

        with contextlib.redirect_stdout(io.StringIO()) as output:
            command.run()

        return output.getvalue()

    def _prepareSkill(self) -> None:
        SkillInstaller.prepare(
            [SkillSpec("skills/hello")],
            self.manifest,
        )

    def testProjectScopeWithDefaultAllSkipsUnsupportedBackends(self):
        self.manifest.write_text(
            json.dumps({"skills": [{"path": "skills/hello"}]})
        )

        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": ""}):
            self._runCLI(
                "--component",
                "skill",
                "--scope",
                "project",
                "--project-dir",
                str(self.project),
            )

        for relativePath in (
            ".claude/skills",
            ".agents/skills",
            ".grok/skills",
            ".opencode/skills",
        ):
            self.assertTrue(
                (self.project / relativePath / "hello" / "SKILL.md").exists()
            )

        self.assertFalse(self.home.exists())

    def testExplicitUnsupportedProjectScopeStillFailsBeforeWriting(self):
        self.manifest.write_text(
            json.dumps({"skills": [{"path": "skills/hello"}]})
        )

        with self.assertRaisesRegex(ValueError, "project-scoped skills"):
            self._runCLI(
                "--component",
                "skill",
                "--scope",
                "project",
                "--target",
                "openmausbot",
            )

        self.assertFalse(self.home.exists())

    def testPrintRedactsMCPEnvironmentByDefault(self):
        self.manifest.write_text(
            json.dumps({
                "serverName": "example",
                "entrypoint": "demo-mcp",
                "envKeys": ["API_TOKEN", "SECOND_TOKEN"],
                "defaultEnvValues": {"SECOND_TOKEN": "another-secret"},
            })
        )

        with mock.patch.dict(os.environ, {"API_TOKEN": ""}):
            preview = self._runCLI(
                "--component",
                "mcp",
                "--target",
                "codex",
                "--print",
                "--env",
                "API_TOKEN=super-secret-value",
            )

        data = json.loads(preview)
        self.assertEqual(
            {"API_TOKEN": "<redacted>", "SECOND_TOKEN": "<redacted>"},
            data["example"]["env"],
        )
        self.assertNotIn("super-secret-value", preview)
        self.assertNotIn("another-secret", preview)

    def testShowingSecretsRequiresExplicitPrintOptIn(self):
        self.manifest.write_text(
            json.dumps({
                "serverName": "example",
                "entrypoint": "demo-mcp",
                "envKeys": ["API_TOKEN"],
            })
        )

        with self.assertRaisesRegex(ValueError, "requires --print"):
            self._runCLI("--target", "codex", "--show-secrets")

        preview = self._runCLI(
            "--print",
            "--show-secrets",
            "--target",
            "codex",
            "--env",
            "API_TOKEN=explicit-value",
        )
        self.assertEqual(
            "explicit-value",
            json.loads(preview)["example"]["env"]["API_TOKEN"],
        )

    def testInvalidAndIncompleteSkillFrontmatterFailsFast(self):
        invalidValues = [
            ("---\nname: hello\n---\n", "description"),
            ("---\nname: other\ndescription: A test\n---\n", "must match"),
            ("---\nname: hello\ndescription: \n---\n", "description"),
            ("---\nname: hello\ndescription: [bad\n---\n", "Invalid YAML"),
            ("---\nname: hello\ndescription: A test\n", "unclosed"),
            ("---\nname: hello\ndescription: " + "x" * 1025 + "\n---\n", "description"),
        ]

        for content, expectedMessage in invalidValues:
            with self.subTest(expectedMessage=expectedMessage, content=content[:45]):
                self.skillFile.write_text(content)
                with self.assertRaisesRegex(ValueError, expectedMessage):
                    self._prepareSkill()

    def testMultilineYamlAndValidScalarName(self):
        self.skillFile.write_text(
            "---\nname: hello\ndescription: >\n"
            "  Runs a sample workflow.\n"
            "  Use for integration tests.\n"
            "---\nInstructions.\n"
        )

        self._prepareSkill()

        with self.assertRaisesRegex(ValueError, "Invalid skill name"):
            SkillInstaller.prepare(
                [SkillSpec("skills/hello", name="X" * 65)],
                self.manifest,
            )

    def testClaudeUninstallPropagatesFailure(self):
        backend = ClaudeCliBackend("claude", "user")
        failed = subprocess.CompletedProcess(
            args=["claude"],
            returncode=1,
            stdout="",
            stderr="Permission denied",
        )

        with mock.patch("mcp_install.backends.Base.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "Permission denied"):
                backend.uninstall("example")

    def testClaudeUninstallDoesNotTreatMissingAsSuccess(self):
        backend = ClaudeCliBackend("claude", "user")
        missing = subprocess.CompletedProcess(
            args=["claude"],
            returncode=1,
            stdout="",
            stderr="No MCP server found with name: example",
        )

        with mock.patch("mcp_install.backends.Base.subprocess.run", return_value=missing):
            with self.assertRaisesRegex(RuntimeError, "No MCP server found"):
                backend.uninstall("example")

    def testClaudeOverwriteIgnoresOnlyConfirmedMissingServer(self):
        backend = ClaudeCliBackend("claude", "user")
        missing = subprocess.CompletedProcess(
            args=["claude"],
            returncode=1,
            stdout="No MCP server found with name: example",
            stderr="",
        )
        success = subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout="Added",
            stderr="",
        )

        with mock.patch(
            "mcp_install.backends.Base.subprocess.run",
            side_effect=[missing, success],
        ) as run:
            backend.install("example", {"command": "uvx", "args": ["demo"]}, True)

        self.assertEqual(2, run.call_count)

    def testClaudeOverwriteDoesNotIgnoreUnexpectedRemoveError(self):
        backend = ClaudeCliBackend("claude", "user")
        failed = subprocess.CompletedProcess(
            args=["claude"],
            returncode=1,
            stdout="",
            stderr="Permission denied",
        )

        with mock.patch(
            "mcp_install.backends.Base.subprocess.run",
            return_value=failed,
        ) as run:
            with self.assertRaisesRegex(RuntimeError, "Permission denied"):
                backend.install(
                    "example",
                    {"command": "uvx", "args": ["demo"]},
                    True,
                )

        self.assertEqual(1, run.call_count)


if __name__ == "__main__":
    unittest.main()
