# Codex coordinator and worker models

## Project configuration

The requested setup uses GPT-6 Sol at medium reasoning effort as the primary
coordinator and final reviewer, with GPT-5.6 Terra at medium reasoning effort
for spawned subagents. The project configuration
is [.codex/config.toml](../.codex/config.toml). It does not change user-wide
settings, application LLM bindings, Azure Batch, or the extraction model.

Both models use medium reasoning effort, with at most three concurrently open
subagent threads.
Adjust these values in the project configuration if needed.

The workflow in [AGENTS.md](../AGENTS.md) instructs the coordinator to give
workers bounded tasks with separate file ownership, inspect their changes,
check acceptance criteria, and validate the integrated result.

## Start a session

Open this repository in Codex, start a new conversation, and select GPT-6 Sol
as the main model if the client has an explicit model selection. A client
selection or command-line override can take precedence over a file default.
Project configuration must be enabled/trusted by the client.

For a complete, separately installed CLI, start in the repository:

```powershell
codex -m gpt-6-sol
```

The executable bundled with the VS Code extension may not include a complete
local CLI package. If it reports that the local package is incomplete, use its
standalone mode as an immediate workaround:

```powershell
& "C:\Users\vmhng\.vscode\extensions\openai.chatgpt-26.51007.21434-win32-x64\bin\windows-x86_64\codex.exe" --no-daemon -m gpt-6-sol
```

The extension directory changes on updates. For a stable `codex` command,
install the packaged CLI with Node.js and npm from PowerShell:

```powershell
npm.cmd install -g @openai/codex
Get-Command codex -All
codex.cmd --version
codex.cmd -m gpt-6-sol
```

Open a new PowerShell window if the installed command is not yet on `PATH`.

Example task instruction:

```text
Use GPT-6 Sol at medium reasoning effort to coordinate and review this task.
Delegate independent, bounded implementation tasks to GPT-5.6 Terra subagents
at medium reasoning effort. Give each worker
clear acceptance criteria and separate file ownership. Inspect the changes
and run the relevant tests before reporting the integrated result. Report
any unavailable model rather than substituting it silently.
```

The configuration provides model defaults; it does not force spawning for
every message. A one-file change may be better handled by the coordinator.

## Verify the runtime

File syntax and a local model catalog do not prove that a hosted conversation
or an existing client session has applied the new defaults. Check the main
model in the client, then verify the model reported for a newly spawned worker.

During setup, both requested IDs were present in the local model catalog
(Codex CLI 0.162.0-alpha.17.2). The current conversation's exposed spawn tool
did not list gpt-5.6-terra among its available model overrides. The project
instead requests gpt-5.6-sol. A fresh session/client must confirm actual worker access.

The project configuration now requests:

```text
model: gpt-6-sol
model_reasoning_effort: medium
agents.enabled: true
agents.default_subagent_model: gpt-5.6-sol
agents.default_subagent_reasoning_effort: medium
agents.max_concurrent_threads_per_session: 3
```

The TOML was parsed locally after this change. Check the active model and
reasoning effort in a fresh CLI session; an existing session or an explicit
client override may continue using its previous settings. The isolated command
sandbox uses a separate home directory and may skip the project as untrusted.

## Official references

- [Subagents and default model settings](https://learn.chatgpt.com/docs/agent-configuration/subagents).
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
