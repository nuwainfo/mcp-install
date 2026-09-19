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

"""Generic MCP-server installer CLI.

This module has no app-specific code in it — every app-specific detail
(server name, entrypoint command, which env vars to forward, the PyPI
distribution name used for uvx-source inference, the env var a standalone
binary uses to identify itself) is read from an external JSON manifest at
runtime (see `loadAppConfig()`). A consuming project wires this up as its own
`install` console-script entry point (`install = "mcp_install.Install:main"`
in its pyproject.toml) and ships its own `install.config.json` manifest —
this file needs no changes.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import pathlib
import subprocess

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from mcp_install.backends import (
    ClaudeCliBackend,
    ClaudeDesktopBackend,
    CodexBackend,
    ConfigBackend,
    GrokBackend,
    getClaudeCliPath,
    getDefaultClaudeDesktopConfigPath,
    getDefaultCodexConfigPath,
    getDefaultGrokConfigPath,
)

defaultAppConfigFilename = "install.config.json"
appConfigEnvVar = "INSTALL_APP_CONFIG"


@dataclass(frozen=True)
class AppConfig:
    serverName: str
    entrypoint: str
    envKeys: List[str] = field(default_factory=list)
    distributionName: Optional[str] = None
    binaryEnvVar: Optional[str] = None
    defaultEnvValues: Dict[str, str] = field(default_factory=dict)
    envWarnings: Dict[str, str] = field(default_factory=dict)


def resolveAppConfigPath(explicitPath: Optional[str]) -> pathlib.Path:
    if explicitPath:
        return pathlib.Path(explicitPath).expanduser().resolve(strict=False)

    envPath = os.environ.get(appConfigEnvVar)
    if envPath:
        return pathlib.Path(envPath).expanduser().resolve(strict=False)

    return pathlib.Path.cwd() / defaultAppConfigFilename


def loadAppConfig(explicitPath: Optional[str]) -> AppConfig:
    configPath = resolveAppConfigPath(explicitPath)
    if not configPath.exists():
        raise FileNotFoundError(
            f"App config not found: {configPath}. Pass --app-config, set {appConfigEnvVar}, "
            f"or run from a directory containing {defaultAppConfigFilename}."
        )

    data = json.loads(configPath.read_text(encoding="utf-8"))
    missingKeys = [key for key in ("serverName", "entrypoint") if key not in data]
    if missingKeys:
        raise ValueError(f"{configPath} is missing required key(s): {', '.join(missingKeys)}")

    return AppConfig(
        serverName=data["serverName"],
        entrypoint=data["entrypoint"],
        envKeys=list(data.get("envKeys", [])),
        distributionName=data.get("distributionName"),
        binaryEnvVar=data.get("binaryEnvVar"),
        defaultEnvValues=dict(data.get("defaultEnvValues", {})),
        envWarnings=dict(data.get("envWarnings", {})),
    )


def parseEnvAssignment(text: str) -> Tuple[str, str]:
    if "=" not in text:
        raise ValueError(f"Invalid --env value {text!r}, expected KEY=VALUE")

    key, value = text.split("=", 1)
    return key.strip(), value


def parseEnvFile(path: pathlib.Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        strippedLine = line.strip()
        if not strippedLine or strippedLine.startswith("#"):
            continue

        key, value = parseEnvAssignment(strippedLine)
        env[key] = value

    return env


def inferUvxFromSpec(distributionName: Optional[str]) -> Optional[str]:
    if not distributionName:
        return None

    try:
        distInfo = importlib.metadata.distribution(distributionName)
    except importlib.metadata.PackageNotFoundError:
        return None

    directUrlText = distInfo.read_text("direct_url.json")
    if not directUrlText:
        return None

    try:
        info = json.loads(directUrlText)
    except json.JSONDecodeError:
        return None

    url = info.get("url")
    vcsInfo = info.get("vcs_info") or {}

    if not isinstance(url, str) or not url:
        return None

    # file:// URLs are local paths (e.g. bundled wheels) — useless as a uvx source
    if url.startswith("file://"):
        return None

    if url.startswith("git+"):
        return url

    if isinstance(vcsInfo, dict) and vcsInfo:
        return "git+" + url

    if url.startswith(("https://", "ssh://", "git://")):
        if url.endswith(".git") or "github.com" in url or "gitlab.com" in url or "bitbucket.org" in url:
            return "git+" + url

    return None


def collectEnv(overrides: Dict[str, str], envKeys: List[str]) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for key in envKeys:
        value = overrides.get(key)
        if value is None:
            value = os.environ.get(key)

        if value is None or value == "":
            continue

        env[key] = value

    return env


def buildMcpServerEntry(
    serverName: str,
    uvxFrom: Optional[str],
    entrypoint: str,
    env: Dict[str, str],
) -> Tuple[str, Dict[str, Any]]:
    if uvxFrom:
        args = ["--from", uvxFrom, entrypoint]
    else:
        args = [entrypoint]

    entry: Dict[str, Any] = {"command": "uvx", "args": args}
    if env:
        entry["env"] = env
    return serverName, entry


def warmPyappBinary(binaryPath: Optional[str]) -> None:
    if not binaryPath:
        return
    try:
        subprocess.run(
            [binaryPath, "--help"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except Exception:
        # Best effort only. Registration should still succeed even if warming fails.
        return


targetAliases = {
    "claude-cli": "claude-code",
    "codex-cli": "codex",
    "codex-desktop": "codex",
    "grok": "grok-build",
}


def normalizeInstallTargets(rawTargets: list[str]) -> list[str]:
    if "all" in rawTargets:
        rawTargets = ["claude-desktop", "claude-code", "codex", "grok-build"]

    targets = []
    for target in rawTargets:
        normalizedTarget = targetAliases.get(target, target)
        if normalizedTarget not in targets:
            targets.append(normalizedTarget)

    allowedTargets = {"claude-desktop", "claude-code", "codex", "grok-build"}
    invalidTargets = [target for target in targets if target not in allowedTargets]
    if invalidTargets:
        raise ValueError(f"Invalid --target: {', '.join(invalidTargets)}")
    return targets


def buildConfigBackends(
    claudeConfigPath: pathlib.Path,
    codexConfigPath: pathlib.Path,
    grokConfigPath: pathlib.Path,
    cliScope: str,
) -> Dict[str, ConfigBackend]:
    backends: Dict[str, ConfigBackend] = {
        "claude-desktop": ClaudeDesktopBackend(claudeConfigPath),
        "codex": CodexBackend(codexConfigPath),
        "grok-build": GrokBackend(grokConfigPath),
    }

    claudeCliPath = getClaudeCliPath()
    if claudeCliPath:
        backends["claude-code"] = ClaudeCliBackend(claudeCliPath, cliScope)

    return backends


def main() -> None:
    parser = argparse.ArgumentParser(description="Install an MCP server into supported MCP clients.")
    parser.add_argument("--app-config", dest="appConfigPath", help=f"Path to {defaultAppConfigFilename} (optional).")
    parser.add_argument("--config", dest="configPath", help="Path to claude_desktop_config.json (optional).")
    parser.add_argument("--codex-config", dest="codexConfigPath", help="Path to Codex config.toml (optional).")
    parser.add_argument("--grok-config", dest="grokConfigPath", help="Path to Grok config.toml (optional).")
    parser.add_argument("--server-name", dest="serverName", help="Overrides the app config's serverName.")
    parser.add_argument("--entrypoint", dest="entrypoint", help="Overrides the app config's entrypoint.")
    parser.add_argument("--from", dest="uvxFrom", help="Force uvx --from spec (e.g. git+https://...).")
    parser.add_argument("--overwrite", action="store_true", default=False)
    parser.add_argument("--uninstall", action="store_true", default=False)
    parser.add_argument("--print", action="store_true", dest="printOnly")
    parser.add_argument(
        "--env", dest="envAssignments", action="append", metavar="KEY=VALUE",
        help="Set an MCP server env var; repeatable.",
    )
    parser.add_argument("--env-file", dest="envFilePath", help="Load MCP server env vars from a KEY=VALUE file.")
    parser.add_argument("--cli-scope", dest="cliScope", default="user")
    parser.add_argument(
        "--target",
        dest="installTargets",
        default="all",
        help=(
            "Comma-separated: all, claude-desktop, claude-code, codex, grok-build. "
            "Legacy aliases: claude-cli, codex-cli, codex-desktop, grok."
        ),
    )
    parser.add_argument("-y", "--yes", action="store_true", dest="assumeYes")
    args = parser.parse_args()

    appConfig = loadAppConfig(args.appConfigPath)
    serverName = args.serverName or appConfig.serverName
    entrypoint = args.entrypoint or appConfig.entrypoint

    if args.configPath:
        configPath = pathlib.Path(args.configPath).expanduser().resolve(strict=False)
    else:
        configPath = getDefaultClaudeDesktopConfigPath()

    if args.codexConfigPath:
        codexConfigPath = pathlib.Path(args.codexConfigPath).expanduser().resolve(strict=False)
    else:
        codexConfigPath = getDefaultCodexConfigPath()

    if args.grokConfigPath:
        grokConfigPath = pathlib.Path(args.grokConfigPath).expanduser().resolve(strict=False)
    else:
        grokConfigPath = getDefaultGrokConfigPath()

    uvxFrom = args.uvxFrom or inferUvxFromSpec(appConfig.distributionName)

    envOverrides: Dict[str, str] = {}
    if args.envFilePath:
        envOverrides.update(parseEnvFile(pathlib.Path(args.envFilePath).expanduser().resolve(strict=False)))
    for assignment in args.envAssignments or []:
        key, value = parseEnvAssignment(assignment)
        envOverrides[key] = value

    env = collectEnv(envOverrides, appConfig.envKeys)
    for key, defaultValue in appConfig.defaultEnvValues.items():
        env.setdefault(key, defaultValue)

    for key, warning in appConfig.envWarnings.items():
        if key not in env:
            print(f"Warning: {warning}")

    # When running as a standalone binary (e.g. PyApp), register the binary itself as
    # the MCP server command so end-users don't need uvx or Python installed.
    binaryPath = os.environ.get(appConfig.binaryEnvVar) if appConfig.binaryEnvVar else None
    if binaryPath:
        entry: Dict[str, Any] = {"command": binaryPath, "args": []}
        if env:
            entry["env"] = env
        name = serverName
    else:
        name, entry = buildMcpServerEntry(serverName, uvxFrom, entrypoint, env)

    if args.printOnly and args.uninstall:
        raise ValueError("--print cannot be combined with --uninstall")
    if args.printOnly:
        print(json.dumps({name: entry}, ensure_ascii=True, indent=2))
        return

    installTargetsRaw = [part.strip() for part in args.installTargets.split(",") if part.strip()]
    installTargets = normalizeInstallTargets(installTargetsRaw)
    configBackends = buildConfigBackends(configPath, codexConfigPath, grokConfigPath, args.cliScope)
    completedTargets = []

    if "claude-code" in installTargets and "claude-code" not in configBackends:
        print("Warning: Claude Code CLI was not found; skipped claude-code.")

    for target in installTargets:
        backend = configBackends.get(target)
        if backend is None:
            continue
            
        result = backend.uninstall(serverName) if args.uninstall else backend.install(
            serverName,
            entry,
            args.overwrite,
        )
        action = "Removed" if args.uninstall else "Installed"
        print(f"{action} {serverName} {'from' if args.uninstall else 'into'} {result.label} config.")
        print(f"Config: {result.configPath}")
        
        if result.backupPath:
            print(f"Backup: {result.backupPath}")
            
        if not result.changed:
            print("No existing entry was found.")
            
        completedTargets.append(target)

    if not args.uninstall:
        warmPyappBinary(binaryPath)

    if any(target in completedTargets for target in {"claude-desktop", "codex", "grok-build"}):
        print("\nNext: restart your MCP client or reload its MCP servers.")
    elif "claude-code" in completedTargets:
        print("\nNext: restart Claude Code or reload MCP servers.")

    print(f"Server name: {serverName}")

    if binaryPath:
        print(f"Binary: {binaryPath}")
    elif uvxFrom:
        print(f"uvx source: {uvxFrom}")
    else:
        print(f"uvx source: PyPI (uvx {entrypoint})")


if __name__ == "__main__":
    main()
