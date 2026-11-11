"""Tests for filesystem Skill deployment and safety boundaries."""

import pathlib
import tempfile
import unittest

from mcp_install.skills import SkillInstaller, SkillSpec


class SkillInstallerTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.home = self.base / "home"
        self.project = self.base / "project"
        self.project.mkdir()
        (self.project / "skills" / "hello").mkdir(parents=True)
        (self.project / "skills" / "hello" / "SKILL.md").write_text(
            "---\nname: hello\ndescription: Sample\n---\nHello\n"
        )
        (self.project / "skills" / "hello" / "scripts").mkdir()
        (self.project / "skills" / "hello" / "scripts" / "run.py").write_text("print(1)")
        self.manifest = self.project / "install.config.json"
        self.installer = SkillInstaller(self.home)

    def apply(self, **options):
        return self.installer.apply(
            [SkillSpec("skills/hello")], ["claude-code", "codex", "grok-build"],
            "user", self.manifest, self.project, **options
        )

    def testDeploysWholeDirectoryAndUninstalls(self):
        self.apply()
        for root in (".claude/skills", ".agents/skills", ".grok/skills"):
            path = self.home / root / "hello"
            self.assertEqual("print(1)", (path / "scripts" / "run.py").read_text())
            self.assertTrue((path / ".mcp-install.json").exists())
        self.apply(uninstall=True)
        self.assertFalse((self.home / ".claude/skills/hello").exists())

    def testOverwriteCreatesBackup(self):
        self.apply()
        with self.assertRaises(FileExistsError):
            self.apply()
        (self.project / "skills" / "hello" / "scripts" / "run.py").write_text("print(2)")
        self.apply(overwrite=True)
        self.assertEqual("print(2)", (self.home / ".claude/skills/hello/scripts/run.py").read_text())
        self.assertEqual(1, len(list((self.home / ".claude/skills").glob("hello.bak_*"))))

    def testRejectsTraversalAndSymlinks(self):
        with self.assertRaises(ValueError):
            self.installer.apply(
                [SkillSpec("../outside")], ["codex"], "user",
                self.manifest, self.project
            )
        (self.project / "skills" / "hello" / "bad").symlink_to(self.base)
        with self.assertRaises(ValueError):
            self.apply()

    def testRejectsUnmanagedUninstall(self):
        path = self.home / ".claude/skills/hello"
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text("no")
        with self.assertRaises(ValueError):
            self.installer.apply(
                [SkillSpec("skills/hello")], ["claude-code"], "user",
                self.manifest, self.project, uninstall=True
            )

    def testProjectScope(self):
        self.installer.apply(
            [SkillSpec("skills/hello")], ["codex"], "project",
            self.manifest, self.project
        )
        self.assertTrue((self.project / ".agents/skills/hello/SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
