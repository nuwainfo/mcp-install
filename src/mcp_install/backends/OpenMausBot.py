"""OpenMausBot stores MCP registrations alongside app settings in its own JSON file."""

from __future__ import annotations

import os
import pathlib

from .Base import JsonMcpBackend


def getDefaultOpenMausBotConfigPath() -> pathlib.Path:
    dataDir = os.environ.get("OMB_DATA_DIR")
    if dataDir:
        return pathlib.Path(dataDir).expanduser() / "config.json"
    return pathlib.Path.home() / ".openmausbot" / "config.json"


class OpenMausBotBackend(JsonMcpBackend):
    """Registers stdio MCP servers in OpenMausBot's mcpServers config object."""

    _userSkillPaths = (".claude/skills", ".codex/skills")

    @property
    def skillNotice(self) -> str:
        return (
            "OpenMausBot: Skills are staged in Claude Code/Codex user folders. "
            "To share them with every bot, use Settings > Replay welcome tour > "
            "Bring what you already use, then review/enable imported Skills. "
            "This preserves OpenMausBot's security scanning and index integrity."
        )

    def __init__(self, configPath: pathlib.Path):
        super().__init__("openmausbot", "OpenMausBot", configPath)
