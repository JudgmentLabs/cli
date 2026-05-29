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

### Homebrew

```bash
brew install JudgmentLabs/tap/judgment-cli
```

`brew upgrade judgment-cli` picks up new releases automatically. Formula source: [JudgmentLabs/homebrew-tap](https://github.com/JudgmentLabs/homebrew-tap).

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

## Shell completion

The `curl` installer wires up completions automatically (zsh, bash, fish). Set `NO_COMPLETIONS=1` before piping to `bash` to opt out, or remove the `# >>> judgment cli completion >>>` block from your rc file later.

`brew install` drops the zsh completion script in `$(brew --prefix)/share/zsh/site-functions/`. zsh picks it up once you've followed [Homebrew's one-time shell-completion setup](https://docs.brew.sh/Shell-Completion) — this same setup enables completions for every brew-installed CLI, not just `judgment`.

To install completions manually for any shell:

```bash
# bash (~/.bashrc, or ~/.bash_profile on macOS)
eval "$(judgment completion bash)"

# zsh (~/.zshrc)
autoload -Uz compinit && compinit
eval "$(judgment completion zsh)"

# fish (~/.config/fish/completions/judgment.fish — auto-loaded)
judgment completion fish > ~/.config/fish/completions/judgment.fish
```

## Usage

Run `judgment --help` for the full command list, and `judgment <group> <command> --help` for the flags on a specific command.

### Natural language

`judgment x` translates a Judgment-specific request into the matching CLI command, previews it, and prompts before running it. Configure an OpenAI-compatible LLM first:

```bash
judgment ai configure
judgment ai models --provider openai --search gpt-5
judgment x find me long traces
```

The shortcut is equivalent to `judgment ai x`. You can also configure it with environment variables:

```bash
export JUDGMENT_LLM_BASE_URL=https://api.openai.com/v1
export JUDGMENT_LLM_API_KEY=sk-...
export JUDGMENT_LLM_MODEL=gpt-5.2
# optional: run generated commands without the confirmation prompt
export JUDGMENT_LLM_AUTO_EXECUTE=true
```

For requests that need IDs, the LLM context knows about `JUDGMENT_ORG_ID` and `JUDGMENT_PROJECT_ID` when those variables are set. If they are not set, `judgment x` can use your Judgment API credentials to infer the likely organization and project. For read-only project-scoped requests, it picks the organization with the most projects and the project with the most traces.

For aggregate requests, `judgment x` can compose multiple JSON-producing CLI commands and parse them locally, for example to find the organization with the most projects or the project with the most traces.
The LLM prompt includes the exact JSON output shapes for read-only CLI commands so it can parse fields such as `organizations[].detail.projects[0].count`, `projects[].total_traces`, and trace/session pagination without guessing.

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

# Prompts
judgment prompts list     <PROJECT_ID>
judgment prompts get      <PROJECT_ID> <PROMPT_NAME> [--commit-id <SHA> | --tag <TAG>]
judgment prompts versions <PROJECT_ID> <PROMPT_NAME>
judgment prompts commit   <PROJECT_ID> <PROMPT_NAME> "<PROMPT_TEXT>" [--tags production --tags staging]
judgment prompts tag      <PROJECT_ID> <PROMPT_NAME> <COMMIT_ID> --tags production
judgment prompts untag    <PROJECT_ID> <PROMPT_NAME> --tags production

# Docs
judgment docs search "how do I instrument my app"
judgment docs read   /docs/getting-started
```

## Development

```bash
uv sync --extra dev
uv run python scripts/generate_cli.py
```

`generate_cli.py` rewrites `src/judgment_cli/generated_commands.py` from the OpenAPI spec. Pass `--spec <url-or-file>` to point at a different spec; `--help` for the full usage.
