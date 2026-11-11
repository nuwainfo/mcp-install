# mcp-install

A reusable, app-agnostic installer for registering stdio MCP servers and deploying
Agent Skills to Claude Code, Codex, Grok Build, and OpenMausBot. MCP registration also supports Claude Desktop.

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

## Wiring it into your project

1. Add `mcp-install` as a dependency of your MCP server or Skill project.
2. Add your own `install` console-script entry point in your `pyproject.toml`:

   ```toml
   [project.scripts]
   install = "mcp_install.Install:main"
   ```

3. Ship an `install.config.json` manifest at your project root. For an MCP server, for example:

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
   | `serverName` | for MCP | Default key the server is registered under in each client's config (overridable with `--server-name`). |
   | `entrypoint` | for MCP | Command run via `uvx <entrypoint>` (overridable with `--entrypoint`). |
   | `distributionName` | no | PyPI/installed distribution name used to infer a `uvx --from <git-url>` source from the running install's metadata. |
   | `binaryEnvVar` | no | Env var name checked for a pre-built standalone binary path; when set, `install` registers that binary directly instead of a `uvx` command. |
   | `envKeys` | no | Which env vars get forwarded into the registered MCP entry's `env` block, from `--env`/`--env-file`/the process environment. |
   | `defaultEnvValues` | no | Values applied to `envKeys` that end up unset after collection. |
   | `envWarnings` | no | Printed once per key still unset after defaults are applied — use this for security-relevant env vars you want to nudge users toward setting. |
   | `skills` | no | List of Skill directories; enough on its own for Skill-only projects. See [Agent Skills](#agent-skills). |

4. If you also ship a standalone binary (e.g. via PyApp), bundle
   `install.config.json` into it too, and pass `--app-config <path>` (resolved
   relative to your own binary/module, not `cwd`) before dispatching into
   `mcp_install.Install:main` — see `ffl-mcp`'s `src/Entrypoint.py` for a
   worked example.

## CLI

```bash
install --print                                    # preview the entry, no writes
install --target claude-desktop,claude-code,codex,grok-build,openmausbot
install --env ALLOWED_BASE_DIR=~/Downloads          # repeatable KEY=VALUE
install --env-file .env.install                     # KEY=VALUE per line
install --overwrite
install --config /path/to/claude_desktop_config.json
install --codex-config /path/to/codex/config.toml
install --grok-config /path/to/grok/config.toml
install --openmausbot-config /path/to/openmausbot/config.json
install --uninstall --target claude-code
install --app-config /path/to/install.config.json   # override manifest lookup
```

`install.config.json` is auto-discovered from the current working directory;
override its location with `--app-config` or the `INSTALL_APP_CONFIG` env var.

`--target` accepts `all` (default), `claude-desktop`, `claude-code`, `codex`,
`grok-build`, `openmausbot`. Legacy aliases `claude-cli`, `codex-cli`,
`codex-desktop`, and
`grok` are accepted and normalized. `claude-code` registers via the Claude
Code CLI (`claude mcp add-json`); `claude-desktop` writes JSON; `codex`/
`grok-build` write TOML; `openmausbot` writes JSON to `~/.openmausbot/config.json`
(or `$OMB_DATA_DIR/config.json`). Use `--openmausbot-config` to override the path.
Existing configuration files are backed up before changes.

## Testing

```bash
python -m unittest discover -s tests -p "*Test.py" -v
```

## Agent Skills

Each Agent backend handles both its MCP registration and its Skill destinations.
Skill directory validation and file operations are shared across backends,
rather than maintained in a separate Skill backend registry.

A consuming project may ship just Skills, just an MCP server, or both. Skills
are copied as complete directories (including `scripts/`, `references/`, and
`assets/`) from paths **relative to the manifest directory**. Every Skill
must include a UTF-8 `SKILL.md` with YAML frontmatter.

Skill-only manifest:

```json
{
  "skills": [
    {"path": "skills/my-skill"}
  ]
}
```

Add the same `skills` array to the existing MCP manifest to install both.
The `name` field is optional and defaults to the Skill directory's basename.
Skill names use lowercase letters, numbers and hyphens.

```bash
install --component auto --target all                 # default: install whatever the manifest provides
install --component skill --target claude-code,codex  # only Skills
install --component mcp --target claude-code          # only MCP
install --component all --target codex                # require both
install --component skill --scope project --project-dir .
install --component skill --print                      # preview destinations without writing
install --component skill --uninstall --target codex  # remove owned Skill directories
```

| Target | User-level Skills | Project-level Skills |
|---|---|---|
| `claude-code` | `~/.claude/skills` | `.claude/skills` |
| `codex` | `~/.agents/skills` | `.agents/skills` |
| `grok-build` | `~/.grok/skills` | `.grok/skills` |
| `openmausbot` | `~/.claude/skills` and `~/.codex/skills` (staging for import) | Not supported |
| `claude-desktop` | Not supported by filesystem installer; use Claude Desktop's Skill importer | — |

Existing directories are preserved unless `--overwrite` is passed; overwrites
receive a timestamped backup. `--uninstall` only deletes directories marked as
managed by mcp-install. Symbolic links and paths escaping the manifest root are
rejected. The standalone Skills flow does not require `uvx`, an MCP server, or a Claude Code CLI.

For `openmausbot`, staged Skills must be imported via **Settings → Replay welcome
tour → Bring what you already use** and reviewed/enabled in OpenMausBot. This
uses its built-in security checks rather than modifying its internal Skill index.

