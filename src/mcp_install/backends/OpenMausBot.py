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

    def __init__(self, configPath: pathlib.Path):
        super().__init__("openmausbot", "OpenMausBot", configPath)
