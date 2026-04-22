# Judgment CLI

Command-line interface for the [Judgment API](https://docs.judgmentlabs.ai). Commands are auto-generated from the API's OpenAPI spec, so the CLI surface always matches the server.

## Installation

### Quick install (curl)

```bash
curl -fsSL https://judgmentlabs.ai/install.sh | bash
```

Pin a specific version:

```bash
curl -fsSL https://github.com/JudgmentLabs/cli/releases/download/v0.1.0/install.sh | bash
```

This puts an isolated venv at `~/.local/share/judgment-cli/venv` and symlinks `judgment` into `~/.local/bin`. Override locations with `INSTALL_DIR=...` and `PREFIX=...`. Requires Python ≥ 3.9 — set `PYTHON=...` to pick a specific interpreter.

### Homebrew (coming soon)

```bash
brew tap JudgmentLabs/tap
brew install judgment-cli
```

### From source

```bash
pip install .
```

## Authentication

### Login (recommended)

```bash
judgment login
# API key: ****
# Organization ID (leave blank to skip): org-...
```

Credentials are written atomically with `0600` permissions to a platform-appropriate config dir resolved via [`platformdirs`](https://pypi.org/project/platformdirs/):

| OS      | Path                                                                |
|---------|---------------------------------------------------------------------|
| macOS   | `~/Library/Application Support/judgment/credentials.json`           |
| Linux   | `$XDG_CONFIG_HOME/judgment/credentials.json` (default `~/.config/...`) |
| Windows | `%APPDATA%\JudgmentLabs\judgment\credentials.json`                  |

### Other methods

| Priority | Method      | Example                                                  |
|----------|-------------|----------------------------------------------------------|
| 1        | Env vars    | `JUDGMENT_API_KEY`, `JUDGMENT_ORG_ID`, `JUDGMENT_BASE_URL` |
| 2        | Config file | `judgment login`                                         |

```bash
judgment status   # show resolved sources
judgment logout   # delete the credentials file
```

## Usage

Run `judgment --help` for the full command list, and `judgment <group> <command> --help` for the flags on a specific command.

```bash
# Projects
judgment projects list

# Traces
judgment traces search    <PROJECT_ID> --pagination '{"limit":25,"cursorSortValue":null,"cursorItemId":null}'
judgment traces get       <PROJECT_ID> <TRACE_ID>
judgment traces spans     <PROJECT_ID> <TRACE_ID>
judgment traces tags      <PROJECT_ID> <TRACE_ID>
judgment traces behaviors <PROJECT_ID> <TRACE_ID>
judgment traces span      <PROJECT_ID> --spans '[{"trace_id":"...","span_id":"..."}]'

# Sessions
judgment sessions search          <PROJECT_ID> --pagination '{"limit":25,"cursorSortValue":null,"cursorItemId":null}'
judgment sessions get             <PROJECT_ID> <SESSION_ID>
judgment sessions trace-ids       <PROJECT_ID> <SESSION_ID>
judgment sessions trace-behaviors <PROJECT_ID> <SESSION_ID>

# Behaviors / judges / automations
judgment behaviors list   <PROJECT_ID>
judgment behaviors get    <PROJECT_ID> <BEHAVIOR_ID>
judgment judges settings  <PROJECT_ID> <JUDGE_ID>
judgment automations list <PROJECT_ID>

# Docs
judgment docs search "how do I instrument my app"
judgment docs read   /docs/getting-started
```

## Development

### Regenerating commands

```bash
make generate                                                # uses prod
make generate SPEC_URL=http://localhost:10006/openapi/json   # local dev
```

This rewrites `src/judgment_cli/generated_commands.py` from the OpenAPI spec at `SPEC_URL`.

### Releasing a new version

Releases are cut automatically by `.github/workflows/release.yaml` on every merge to `main`. The bump type defaults to **patch**; prefix the merge commit message with `[Bump Minor Version]` or `[Bump Major Version]` to override. The workflow rewrites the version files, tags `vX.Y.Z`, and creates a GitHub Release whose tarball backs the `latest` curl installer.

### Homebrew formula updates

The Homebrew formula in `Formula/judgment-cli.rb` is mirrored to a separate [tap repo](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap) and updated manually after a release:

```bash
new=0.1.4
sha=$(curl -sL https://github.com/JudgmentLabs/cli/archive/refs/tags/v$new.tar.gz | shasum -a 256 | awk '{print $1}')
```

Paste the new `url` + `sha256` into the formula. If any Python dep changed, regenerate the `resource` blocks with [`homebrew-pypi-poet`](https://github.com/tdsmith/homebrew-pypi-poet):

```bash
pip install homebrew-pypi-poet
poet -f judgment-cli
```
