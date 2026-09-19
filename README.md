# mcp-install

A reusable, app-agnostic installer for registering stdio MCP servers with
Claude Desktop, Claude Code, Codex, and Grok Build.

This package has **no knowledge of any specific MCP server**. Every
app-specific detail — server name, entrypoint command, which env vars to
forward into the registered entry, the PyPI distribution name used for
`uvx --from` inference, the env var a standalone binary uses to identify
itself — is read from a small JSON manifest (`install.config.json`) that each
consuming project ships on its own. Point `mcp_install.Install` at your
manifest and it needs no code changes.

## Installing

```bash
pip install mcp-install
# or, for local development against a sibling checkout:
pip install -e ../mcp-install
```

## Wiring it into your own MCP server project

1. Add `mcp-install` as a dependency of your project.
2. Add your own `install` console-script entry point in your `pyproject.toml`:

   ```toml
   [project.scripts]
   install = "mcp_install.Install:main"
   ```

3. Ship an `install.config.json` manifest at your project root:

   ```json
   {
     "serverName": "my-server",
     "entrypoint": "my-mcp",
     "distributionName": "my-mcp",
     "binaryEnvVar": "MY_MCP_BINARY",
     "envKeys": ["MY_SERVER_TOKEN"],
     "defaultEnvValues": {},
     "envWarnings": {
       "MY_SERVER_TOKEN": "MY_SERVER_TOKEN is not set."
     }
   }
   ```

   | Key | Required | Meaning |
   |---|---|---|
   | `serverName` | yes | Default key the server is registered under in each client's config (overridable with `--server-name`). |
   | `entrypoint` | yes | Command run via `uvx <entrypoint>` (overridable with `--entrypoint`). |
   | `distributionName` | no | PyPI/installed distribution name used to infer a `uvx --from <git-url>` source from the running install's metadata. |
   | `binaryEnvVar` | no | Env var name checked for a pre-built standalone binary path; when set, `install` registers that binary directly instead of a `uvx` command. |
   | `envKeys` | no | Which env vars get forwarded into the registered MCP entry's `env` block, from `--env`/`--env-file`/the process environment. |
   | `defaultEnvValues` | no | Values applied to `envKeys` that end up unset after collection. |
   | `envWarnings` | no | Printed once per key still unset after defaults are applied — use this for security-relevant env vars you want to nudge users toward setting. |

4. If you also ship a standalone binary (e.g. via PyApp), bundle
   `install.config.json` into it too, and pass `--app-config <path>` (resolved
   relative to your own binary/module, not `cwd`) before dispatching into
   `mcp_install.Install:main` — see `ffl-mcp`'s `src/Entrypoint.py` for a
   worked example.

## CLI

```bash
install --print                                    # preview the entry, no writes
install --target claude-desktop,claude-code,codex,grok-build
install --env ALLOWED_BASE_DIR=~/Downloads          # repeatable KEY=VALUE
install --env-file .env.install                     # KEY=VALUE per line
install --overwrite
install --config /path/to/claude_desktop_config.json
install --codex-config /path/to/codex/config.toml
install --grok-config /path/to/grok/config.toml
install --uninstall --target claude-code
install --app-config /path/to/install.config.json   # override manifest lookup
```

`install.config.json` is auto-discovered from the current working directory;
override its location with `--app-config` or the `INSTALL_APP_CONFIG` env var.

`--target` accepts `all` (default), `claude-desktop`, `claude-code`, `codex`,
`grok-build`. Legacy aliases `claude-cli`, `codex-cli`, `codex-desktop`, and
`grok` are accepted and normalized. `claude-code` registers via the Claude
Code CLI (`claude mcp add-json`); `claude-desktop` writes JSON; `codex`/
`grok-build` write TOML. Every write is preceded by a timestamped backup of
the existing config file.

## Package layout

```
mcp-install/
├── src/
│   └── mcp_install/
│       ├── Install.py       # CLI entry point (main()), AppConfig, uvx-source inference
│       └── backends/
│           ├── Base.py      # ConfigBackend, JsonMcpBackend, TomlMcpBackend, TOML/file helpers
│           ├── Claude.py    # ClaudeDesktopBackend, ClaudeCliBackend
│           ├── Codex.py     # CodexBackend
│           └── Grok.py      # GrokBackend
└── tests/                   # unittest-based tests
```

## Testing

```bash
python -m unittest discover -s tests -p "*Test.py" -v
```
