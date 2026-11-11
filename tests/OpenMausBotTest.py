"""OpenMausBot integration tests: config ownership and upstream Skill import paths."""

import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from mcp_install.backends import ClaudeCliBackend, OpenMausBotBackend, getDefaultOpenMausBotConfigPath
from mcp_install.skills import SkillInstaller, SkillSpec
from mcp_install.Install import normalizeInstallTargets


class OpenMausBotTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.home = self.base / "home"
        self.project = self.base / "project"
        self.project.mkdir()
        skill = self.project / "skills" / "hello"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: hello\ndescription: Test\n---\n")
        (skill / "assets").mkdir()
        (skill / "assets" / "sample.txt").write_text("example")
        self.manifest = self.project / "install.config.json"

    def testMCPRegistrationPreservesOtherConfig(self):
        configPath = self.base / "config.json"
        configPath.write_text(json.dumps({"instances": {"custom": {"driver": "codex"}}, "mcpServers": {"other": {"command": "node"}}}))
        configPath.chmod(0o600)
        backend = OpenMausBotBackend(configPath)
        result = backend.install("test", {"command": "uvx", "args": ["demo-mcp"]}, overwrite=False)
        data = json.loads(configPath.read_text())
        self.assertIn("custom", data["instances"])
        self.assertEqual("node", data["mcpServers"]["other"]["command"])
        self.assertEqual("uvx", data["mcpServers"]["test"]["command"])
        self.assertTrue(result.backupPath.exists())
        if os.name != "nt":
            self.assertEqual(0o600, configPath.stat().st_mode & 0o777)
            self.assertEqual(0o600, result.backupPath.stat().st_mode & 0o777)
        backend.uninstall("test")
        self.assertNotIn("test", json.loads(configPath.read_text())["mcpServers"])

    def testDataDirOverride(self):
        with mock.patch.dict(os.environ, {"OMB_DATA_DIR": str(self.base)}):
            self.assertEqual(self.base / "config.json", getDefaultOpenMausBotConfigPath())

    def testOpenMausBotStagingUsesTwoReviewedImportSources(self):
        prepared = SkillInstaller.prepare(
            [SkillSpec("skills/hello")],
            self.manifest,
        )
        backend = OpenMausBotBackend(self.base / "config.json")
        claude = ClaudeCliBackend(None, "user")
        handledPaths = set()

        claude.installSkills(
            prepared,
            "user",
            self.home,
            self.project,
            handledPaths,
        )
        results = backend.installSkills(
            prepared,
            "user",
            self.home,
            self.project,
            handledPaths,
        )

        self.assertEqual(1, len(results))
        self.assertEqual("openmausbot", results[0].target)

        for root in (".claude/skills", ".codex/skills"):
            destination = self.home / root / "hello"
            self.assertTrue((destination / "SKILL.md").is_file())
            self.assertEqual(
                "example",
                (destination / "assets/sample.txt").read_text(),
            )

        self.assertEqual([], list((self.home / ".claude/skills").glob("hello.bak_*")))

        removed = SkillInstaller.prepare(
            [SkillSpec("skills/hello")],
            self.manifest,
            uninstall=True,
        )
        handledPaths.clear()

        claude.installSkills(
            removed, "user", self.home, self.project, handledPaths, uninstall=True
        )
        backend.installSkills(
            removed, "user", self.home, self.project, handledPaths, uninstall=True
        )
        self.assertFalse((self.home / ".codex/skills/hello").exists())

    def testProjectScopeIsRejected(self):
        backend = OpenMausBotBackend(self.base / "config.json")

        with self.assertRaises(ValueError):
            backend.skillRoots("project", self.home, self.project)

    def testAllIncludesOpenMausBot(self):
        self.assertIn("openmausbot", normalizeInstallTargets(["all"]))


if __name__ == "__main__":
    unittest.main()
