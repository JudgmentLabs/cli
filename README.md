# Judgment CLI

Command-line interface for the [Judgment API](https://docs.judgmentlabs.ai). Auto-generated from the OpenAPI spec.

## Installation

### From source (pip)

```bash
pip install .
```

### Development mode

```bash
pip install -e ".[dev]"
```

### Homebrew (coming soon)

```bash
brew tap judgment-labs/tap
brew install judgment-cli
```

## Authentication

### Login (recommended)

Run `judgment login` once to store your credentials locally:

```bash
judgment login
# API key: ****
# Organization ID (leave blank to skip): org-...
```

Credentials are saved to `~/.config/judgment/credentials.json` (file permissions set to `0600`).

### Other methods

You can also authenticate via environment variables or flags. The CLI resolves credentials in this order (highest priority first):

| Priority | Method | Example |
|---|---|---|
| 1 | Flags | `--api-key sk-...` |
| 2 | Env vars | `JUDGMENT_API_KEY=sk-...` |
| 3 | Config file | `~/.config/judgment/credentials.json` |

### Check auth status

```bash
judgment status
```

### Logout

```bash
judgment logout
```

## Usage

```bash
# List your organizations
judgment orgs list

# List projects
judgment projects list

# Create a project
judgment projects create -d '{"name": "my-project"}'

# List traces (with default pagination)
judgment traces list <PROJECT_ID>

# List traces with custom filters
judgment traces list <PROJECT_ID> -d '{"pagination": {"limit": 10, "cursorSortValue": null, "cursorItemId": null}}'

# Get trace details
judgment traces get <PROJECT_ID> <TRACE_ID>

# Get spans for a trace
judgment traces spans <PROJECT_ID> <TRACE_ID>

# List judges
judgment judges list <PROJECT_ID>

# List behaviors
judgment behaviors list <PROJECT_ID>

# List prompts
judgment prompts list <PROJECT_ID>

# Get a specific prompt
judgment prompts get <PROJECT_ID> <PROMPT_NAME>
```

## Available Commands

| Group | Command | Description |
|---|---|---|
| `orgs` | `list` | List organizations |
| `orgs` | `get` | Get organization details |
| `orgs` | `usage` | Get organization usage |
| `projects` | `list` | List all projects |
| `projects` | `get` | Get a project by ID |
| `traces` | `list` | List and filter traces |
| `traces` | `get` | Get trace details |
| `traces` | `spans` | Get spans for a trace |
| `traces` | `behaviors` | Get behaviors on a trace |
| `datasets` | `list` | List datasets |
| `judges` | `list` | List judges |
| `judges` | `get` | Get judge details |
| `judges` | `models` | List available models |
| `behaviors` | `list` | List behaviors |
| `behaviors` | `get` | Get behavior details |
| `tests` | `list` | List test runs |
| `prompts` | `list` | List prompts |
| `prompts` | `get` | Get latest prompt version |
| `prompts` | `versions` | List prompt versions |
| `rules` | `list` | List rules |
| `sessions` | `get` | Get session details |

## Regenerating Commands

CLI commands are auto-generated from the Judgment OpenAPI spec. To regenerate after API changes:

```bash
make generate
```

This runs `scripts/generate_cli.py` which reads the OpenAPI spec and updates `src/judgment_cli/generated_commands.py`.

### Adding new commands

Edit the `INCLUDE_OPERATIONS` list in `scripts/generate_cli.py` to add or remove CLI commands. Each entry maps an OpenAPI `operationId` to a CLI group and command name:

```python
{
    "operation_id": "getProjectsByProject_idDatasets",
    "group": "datasets",
    "command": "list",
    "description": "List all datasets in a project",
}
```

Then run `make generate`.

## Homebrew Distribution

The `Formula/judgment-cli.rb` file is a Homebrew formula template. To distribute via Homebrew:

1. Create a [Homebrew tap](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap) repository (e.g. `judgment-labs/homebrew-tap`)
2. Tag a release and create a GitHub release tarball
3. Update the formula's `url` and `sha256` with the release tarball details
4. Copy the formula into the tap repository
5. Users can then install with `brew tap judgment-labs/tap && brew install judgment-cli`
