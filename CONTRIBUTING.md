# Contributing to HabitFlow

Thanks for taking the time. This page covers how to run the project locally, where things live and what a good pull request looks like.

## Set up a development environment

```bash
git clone https://github.com/inboxpraveen/Daily-Tracker.git
cd Daily-Tracker
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt               # runtime + pytest, PyInstaller, Pillow
```

A conda environment works the same way: create one with Python 3.9 or newer and run the `pip install` line.

Run the app against a throwaway database so your own habits are never touched:

```bash
# macOS / Linux
HABITFLOW_DATA_DIR=./.dev-data HABITFLOW_NO_BROWSER=1 HABITFLOW_DEBUG=1 python app.py

# Windows PowerShell
$env:HABITFLOW_DATA_DIR = ".dev-data"; $env:HABITFLOW_NO_BROWSER = "1"; $env:HABITFLOW_DEBUG = "1"; python app.py
```

`HABITFLOW_DEBUG=1` turns on Flask's auto-reloader and debugger. Templates and static files are read from disk, so UI changes show up on refresh.

## Run the checks

```bash
python -m pytest tests -q
```

The tests take about a second. Every test runs against a temporary database through `HABITFLOW_DATA_DIR`, so `%APPDATA%\HabitFlow` is never touched.

## Where things live

| Area | Path | Notes |
| --- | --- | --- |
| Server, API, rules | `app.py` | One file on purpose. The helpers near the top decide which days a habit counts on; the tracker, dashboard and Excel export all use them |
| Pages | `templates/index.html`, `templates/dashboard.html` | Plain HTML, CSS and JavaScript. No framework, no bundler, no build step |
| Static assets | `static/` | Chart.js and the fonts are vendored. Do not add a CDN link |
| Installer | `packaging/` | PyInstaller spec and Inno Setup script. `make_icon.py` and `make_version.py` run before the build |
| Release | `.github/workflows/release.yml` | Runs on `v*` tags |
| Docs | `README.md`, `docs/` | [ARCHITECTURE.md](docs/ARCHITECTURE.md) and [API.md](docs/API.md) |

## Guidelines

- **Changes come with tests.** New behaviour needs a test, and a bug fix needs one that would have caught the bug. Look at the `client` fixture in `tests/test_app.py`.
- **Nothing leaves the machine.** The app must not call out to any other host, and no page may load a font, script or stylesheet from one. A test enforces the pages part. Add a dependency to `static/vendor/` instead of linking to a CDN.
- **Keep the numbers honest.** Anything that counts days goes through the helpers in `app.py` (`_counts_on`, `_habit_goal`, `_habit_window`), so the tracker, dashboard and Excel export can never disagree. Do not change what a percentage means without saying so in `CHANGELOG.md`.
- **Never lose history.** Removing a habit is a soft delete. A migration must be idempotent and safe on an old database. `test_migration_backfills_deactivated_at_from_last_use` shows the pattern.
- **Validate at the edge.** Dates, colours and ids are checked before they reach the database, and request values are always SQL bound parameters.
- **Match the existing style.** Keep comments to the why, keep the UI free of dependencies and keep user-facing text plain. Errors should say what to do next.
- **If you change the API,** update [docs/API.md](docs/API.md).

## Pull requests

1. For anything bigger than a bug fix, open an issue first so we can talk the design through.
2. Branch from `main`, keep commits focused and write a clear description. The template has the checklist.
3. Make sure `python -m pytest tests -q` passes.
4. Update the docs and `CHANGELOG.md` (under "Unreleased") when behaviour changes. A screenshot helps for UI changes.

## Reporting bugs

Use the bug template. Include your HabitFlow version (it is in `GET /api/health` and in the installer's version info), how you run it (installer, portable zip or from source), and the end of `habitflow.log` from the data folder if something crashed. Please remove anything private first; the log can contain file paths.

Security problems do not go in a public issue. See [SECURITY.md](SECURITY.md).

## Code of conduct

Be kind and constructive. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
