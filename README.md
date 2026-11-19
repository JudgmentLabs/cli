# Judgment CLI

> [!CAUTION]
> **The Judgment CLI has been shut down.** Its backend at
> `cli.judgmentlabs.ai` is being turned off, so existing installations stop
> working and the installer at `https://judgmentlabs.ai/install.sh` no longer
> installs it. The CLI was deprecated on July 9, 2026.

Use one of these instead:

- **Coding agents:** connect the [Judgment MCP
  server](https://docs.judgmentlabs.ai/documentation/start/connect-your-coding-agent)
  so Cursor, Claude Code, Codex or another MCP client can read Issues, traces,
  judge labels and test runs.
- **Code:** use the [Python and TypeScript
  SDKs](https://docs.judgmentlabs.ai/sdk-reference).

## Remove an existing installation

If you installed with the `curl` installer, delete the virtual environment, the
`judgment` symlink and the credentials file, then remove the
`# >>> judgment cli completion >>>` block from your shell rc file:

```bash
rm -rf ~/.local/share/judgment-cli ~/.local/bin/judgment
```

| OS      | Credentials file                                                    |
|---------|---------------------------------------------------------------------|
| macOS   | `~/Library/Application Support/judgment/credentials.json`           |
| Linux   | `$XDG_CONFIG_HOME/judgment/credentials.json` (default `~/.config/...`) |
| Windows | `%APPDATA%\JudgmentLabs\judgment\credentials.json`                  |

If you installed with Homebrew, run `brew uninstall judgment-cli`. If you
installed from source, run `pip uninstall judgment-cli`.

This repository is kept for reference only and is no longer maintained.
