# Changelog

Notable changes to HabitFlow are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Changed
- The fonts (DM Sans and DM Mono, latin subset) are bundled in `static/vendor/fonts/` instead of loaded from Google Fonts. Opening a page no longer makes any request to another host, which is what the README's privacy claim says. A new test checks both pages for external resources.
- Running from source (`python app.py`) no longer starts Flask's debugger and auto-reloader. Set `HABITFLOW_DEBUG=1` to get them back for development.
- Insight sentences, Excel sheet titles and chart titles, installer prompts and the page titles are punctuated with commas and colons instead of dashes. For example, "19-day streak on 5:30 AM Wake Up, your longest run yet."
- Screenshots in the README are retaken, and the Excel ones are now rendered from a real export.

### Added
- A logo, a banner and a social preview image in `assets/`, and an architecture diagram.
- `docs/ARCHITECTURE.md` (components, startup, data model, the rules behind the numbers, security model, release pipeline) and `docs/API.md` (the local JSON API).
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` and issue and pull request templates.
- README sections on privacy, scripting the local API, and supporting the project.

## [1.1.0] - 2026-09-06

### Added
- A Windows installer (`HabitFlow-Setup-x.y.z.exe`, built with Inno Setup, installs per user with no admin rights) and a portable zip. The exe carries a real icon and version information. Updating over an old install keeps your history, and uninstalling asks before deleting it.
- A dashboard that leads with plain-language insights: the longest current streak, streaks at risk today, your weakest and strongest day of the week, month-over-month movement, and the habit dragging the month down. Per-habit current and best streaks, and a weekday rhythm chart over the last 90 days.
- A Today panel with a progress ring and a streak chip for every habit.
- Backup to and restore from a single JSON file, and a "Where is my data?" menu entry.
- A "Tracking since" date for each habit, so you choose which days it is judged on.
- Tests (`pytest`) that run against a temporary database, and Chart.js bundled so charts work offline.
- A second launch now opens the running copy instead of starting another.
- A host check that rejects requests addressed to any name other than localhost, and JSON errors for every `/api/` call.
- The release workflow runs the tests, smoke-tests the built exe against `/api/health`, builds the installer and publishes both files.

### Changed
- Habits now have a tracking window (`created_at` to `deactivated_at`). Percentages count only the days a habit was being tracked, so adding a habit no longer lowers last month and removing one no longer rewrites history. Removing a habit is a soft delete. Databases from earlier versions are migrated when the app starts.
- The build is a PyInstaller one-folder app instead of a single-file exe.

## v1.0, v1.1 and v1.2 - April 2026

- v1.0: the first release. A habit tracker with a monthly grid, a dashboard, Excel export and light and dark themes, published as a single-file Windows exe built on GitHub Actions.
- v1.1: UPX compression turned off to reduce antivirus false positives.
- v1.2: the app shuts itself down when the browser tab closes, and the README explains how to start fresh.

These releases ship `HabitFlow.exe` only. Install the latest release instead.
