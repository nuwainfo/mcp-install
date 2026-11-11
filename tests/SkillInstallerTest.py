"""Agent backends share Skill deployment without a second backend registry."""

import pathlib
import tempfile
import unittest

from mcp_install.backends import ClaudeCliBackend, CodexBackend, GrokBackend
from mcp_install.skills import SkillInstaller, SkillSpec


class SkillInstallerTest(unittest.TestCase):

    def setUp(self):
        self.tempDirectory = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempDirectory.cleanup)

        self.base = pathlib.Path(self.tempDirectory.name)
        self.home = self.base / "home"
        self.project = self.base / "project"
        self.project.mkdir()

        skill = self.project / "skills" / "hello"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: hello\ndescription: Example\n---\nHello\n"
        )
        (skill / "scripts").mkdir()
        (skill / "scripts" / "run.py").write_text("print(1)")

        self.manifest = self.project / "install.config.json"
        self.backends = [
            ClaudeCliBackend(None, "user"),
            CodexBackend(self.base / "codex.toml"),
            GrokBackend(self.base / "grok.toml"),
        ]

    def apply(self, scope="user", **options):
        uninstall = options.get("uninstall", False)
        prepared = SkillInstaller.prepare(
            [SkillSpec("skills/hello")],
            self.manifest,
            uninstall=uninstall,
        )

        handledPaths = set()
        results = []
        for backend in self.backends:
            results.extend(
                backend.installSkills(
                    prepared,
                    scope,
                    self.home,
                    self.project,
                    handledPaths,
                    **options,
                )
            )

        return results

    def testDeploysWholeDirectoryAndUninstalls(self):
        results = self.apply()
        self.assertEqual(3, len(results))

        for root in (".claude/skills", ".agents/skills", ".grok/skills"):
            folder = self.home / root / "hello"
            self.assertEqual("print(1)", (folder / "scripts/run.py").read_text())
            self.assertTrue((folder / ".mcp-install.json").exists())

        self.apply(uninstall=True)
        self.assertFalse((self.home / ".claude/skills/hello").exists())

    def testSkillOnlyWorksWithoutClaudeCLI(self):
        backend = self.backends[0]
        self.assertFalse(backend.mcpAvailable)

        results = backend.installSkills(
            SkillInstaller.prepare([SkillSpec("skills/hello")], self.manifest),
            "user",
            self.home,
            self.project,
            set(),
        )
        self.assertEqual(1, len(results))
        self.assertTrue(results[0].changed)

    def testOverwriteCreatesBackup(self):
        self.apply()
        with self.assertRaises(FileExistsError):
            self.apply()

        sourceFile = self.project / "skills/hello/scripts/run.py"
        sourceFile.write_text("print(2)")

        self.apply(overwrite=True)
        targetFile = self.home / ".claude/skills/hello/scripts/run.py"
        self.assertEqual("print(2)", targetFile.read_text())

        backups = list((self.home / ".claude/skills").glob("hello.bak_*"))
        self.assertEqual(1, len(backups))

    def testRejectsTraversalAndSymlinks(self):
        with self.assertRaises(ValueError):
            SkillInstaller.prepare([SkillSpec("../outside")], self.manifest)

        skill = self.project / "skills/hello"
        (skill / "bad").symlink_to(self.base)
        with self.assertRaises(ValueError):
            self.apply()

    def testRejectsUnmanagedUninstall(self):
        folder = self.home / ".claude/skills/hello"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("unmanaged")

        with self.assertRaises(ValueError):
            self.apply(uninstall=True)

    def testProjectScope(self):
        self.apply(scope="project")

        for root in (".claude/skills", ".agents/skills", ".grok/skills"):
            self.assertTrue((self.project / root / "hello/SKILL.md").is_file())

    def testPreviewDoesNotWriteFiles(self):
        results = self.apply(printOnly=True)

        self.assertEqual(3, len(results))
        self.assertFalse(self.home.exists())

    def testDuplicateSkillNamesAreRejectedBeforeInstallation(self):
        with self.assertRaises(ValueError):
            SkillInstaller.prepare(
                [SkillSpec("skills/hello"), SkillSpec("skills/hello")],
                self.manifest,
            )


if __name__ == "__main__":
    unittest.main()
