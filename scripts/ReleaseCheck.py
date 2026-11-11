"""Verify release metadata and installed wheel/sdist artifacts before publication."""

from __future__ import annotations

import argparse
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile
import tomllib
import venv

from typing import Optional


class ReleaseChecker:
    """Ensure a release tag matches a reproducible, importable distribution."""

    def __init__(self, distDirectory: pathlib.Path, tag: Optional[str] = None):
        self.distDirectory = distDirectory
        self.tag = tag

    @staticmethod
    def _projectVersion() -> str:
        with open("pyproject.toml", "rb") as projectFile:
            project = tomllib.load(projectFile)

        return project["project"]["version"]

    @staticmethod
    def _runtimeVersion() -> str:
        import ast

        sourcePath = pathlib.Path("src/mcp_install/__init__.py")
        module = ast.parse(sourcePath.read_text(encoding="utf-8"))
        for statement in module.body:
            if not isinstance(statement, ast.Assign):
                continue

            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id == "__version__":
                    return ast.literal_eval(statement.value)

        raise ValueError("mcp_install.__version__ was not found")

    def _verifyVersions(self) -> str:
        version = self._projectVersion()
        runtimeVersion = self._runtimeVersion()
        if version != runtimeVersion:
            raise ValueError(
                f"Project version {version} does not match runtime {runtimeVersion}"
            )
        if self.tag and self.tag != f"v{version}":
            raise ValueError(
                f"Release tag {self.tag!r} must match project version v{version}"
            )

        return version

    def _distributions(self, version: str) -> list[pathlib.Path]:
        wheels = list(self.distDirectory.glob("*.whl"))
        sources = list(self.distDirectory.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sources) != 1:
            raise ValueError("Expected exactly one wheel and one source distribution")

        wheel = wheels[0]
        source = sources[0]
        if not wheel.name.startswith(f"mcp_install-{version}-"):
            raise ValueError(f"Wheel version mismatch: {wheel.name}")
        if source.name != f"mcp_install-{version}.tar.gz":
            raise ValueError(f"Source distribution version mismatch: {source.name}")

        return [wheel.resolve(), source.resolve()]

    @staticmethod
    def _smokeTest(artifact: pathlib.Path, version: str) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-install-release-") as tempDirectory:
            isolatedDirectory = pathlib.Path(tempDirectory)
            venvPath = isolatedDirectory / "venv"
            venv.EnvBuilder(with_pip=True).create(venvPath)

            executable = (
                venvPath / "Scripts" / "python.exe"
                if os.name == "nt"
                else venvPath / "bin" / "python"
            )
            subprocess.run(
                [
                    str(executable),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    str(artifact),
                ],
                check=True,
            )

            smokeCode = (
                "import importlib.metadata as metadata\n"
                "import mcp_install\n"
                "from mcp_install.Install import InstallCommand\n"
                "from mcp_install.backends import OpenCodeBackend, ClaudeCliBackend\n"
                "from mcp_install.skills import SkillInstaller\n"
                f"assert metadata.version('mcp-install') == {version!r}\n"
                f"assert mcp_install.__version__ == {version!r}\n"
            )
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            subprocess.run(
                [str(executable), "-c", smokeCode],
                cwd=isolatedDirectory,
                env=environment,
                check=True,
            )

    def verify(self) -> None:
        version = self._verifyVersions()
        distributions = self._distributions(version)

        for artifact in distributions:
            print(f"Checking installed distribution: {artifact.name}", flush=True)
            self._smokeTest(artifact, version)

        print(f"Release candidate v{version}: wheel and sdist smoke tests passed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify release distributions.")
    parser.add_argument("--tag", help="GitHub release tag (for example v0.3.0).")
    parser.add_argument("--dist", default="dist", help="Built distribution directory.")
    args = parser.parse_args()

    ReleaseChecker(pathlib.Path(args.dist), args.tag).verify()


if __name__ == "__main__":
    main()
