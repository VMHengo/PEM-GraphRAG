# Local Development Environment

This project is easiest to work on when the local machine has a real project
Python environment instead of relying on the Windows Store Python launcher. The
Store launcher caused process startup issues and missed dependencies such as
`json_repair` during local checks.

## Recommended Local Updates

### 1. Install A Real Python

Use Python 3.12 because the Docker image currently runs Python 3.12.

Recommended Windows install:

```powershell
winget install Python.Python.3.12
```

Then disable the Windows Store aliases:

1. Open Windows Settings.
2. Go to Apps.
3. Open Advanced app settings.
4. Open App execution aliases.
5. Disable `python.exe` and `python3.exe` aliases for the Microsoft Store.

Verify:

```powershell
where.exe python
where.exe py
py -0p
python --version
```

`where.exe python` should point to the Python installation, not only to
`WindowsApps`.

### 2. Create A Project Virtual Environment

From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

If PowerShell blocks activation scripts:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 3. Install Project Dependencies With uv

The repository is configured for `uv`, so prefer it over manual `pip install`
when possible.

```powershell
python -m pip install uv
uv sync --extra api --extra test
```

Use the environment through:

```powershell
.\.venv\Scripts\Activate.ps1
```

or run one-off commands with:

```powershell
uv run python -m pytest tests
```

### 4. Install Ruff

Ruff is used for fast Python linting. Install it either through the project
environment or as a standalone tool.

Project-local:

```powershell
uv sync --extra test
uv run ruff check .
```

Standalone:

```powershell
uv tool install ruff
ruff check .
```

Useful scoped check after backend edits:

```powershell
uv run ruff check lightrag/operate.py lightrag/prompt.py tests/extraction tests/evaluation
```

### 5. Run Focused Tests Locally

After extraction or prompt-related backend edits:

```powershell
uv run python -m pytest tests/extraction/test_relationship_metadata_extraction.py -q
uv run python -m pytest tests/evaluation/test_directed_phase0_fixtures.py -q
```

After API or document route edits:

```powershell
uv run python -m pytest tests/api tests/pipeline -q
```

If a full run is needed:

```powershell
.\scripts\test.sh tests
```

### 6. Install Bun For WebUI Work

The WebUI uses Bun and Vite.

Recommended:

```powershell
winget install Oven-sh.Bun
```

Then restart the terminal and verify:

```powershell
bun --version
```

Build the WebUI:

```powershell
cd lightrag_webui
bun install --frozen-lockfile
bun run build
cd ..
```

### 7. Keep Secrets Out Of Git

Do not commit:

- `.env`
- `.env.staging`
- API keys
- Auth0 client secrets
- SSH private keys
- `data/`
- `data-staging/`
- local backups

Before committing:

```powershell
git status --short
git diff --cached --name-only
```

### 8. Suggested Local Check Routine

For a normal backend-only change:

```powershell
.\.venv\Scripts\Activate.ps1
uv run python -m py_compile lightrag/operate.py lightrag/prompt.py
uv run ruff check lightrag/operate.py lightrag/prompt.py tests/extraction tests/evaluation
uv run python -m pytest tests/extraction/test_relationship_metadata_extraction.py tests/evaluation/test_directed_phase0_fixtures.py -q
git diff --check
```

For a WebUI change:

```powershell
cd lightrag_webui
bun install --frozen-lockfile
bun run build
cd ..
git diff --check
```

