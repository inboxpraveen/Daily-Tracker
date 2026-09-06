# HabitFlow

A habit tracker that runs on your own computer. Tick off what you did today, and it tells you what that adds up to — streaks, the day of the week you keep slipping on, the one habit dragging your month down.

No account. No subscription. No cloud. Your history lives in a single file on your machine.

---

## Install (Windows)

1. Go to [**Releases**](../../releases) and download **`HabitFlow-Setup-x.y.z.exe`**.
2. Double-click it. No admin rights needed — it installs just for you.
3. HabitFlow opens in your browser. Start ticking boxes.

After that, launch it from the Start Menu like any other app. Closing the browser tab shuts the app down on its own.

> **"Windows protected your PC"** — the installer is not code-signed (certificates cost money this project does not take). Click **More info → Run anyway**. Every release is built in the open on GitHub Actions; you can read the build log in the [Actions tab](../../actions) and reproduce it yourself from source.

Prefer no installer? The same release has a **portable `.zip`** — unpack it anywhere (a USB stick works) and run `HabitFlow.exe` from the folder.

**Not on Windows?** Run it from source — see [Running from source](#running-from-source). It works on macOS and Linux; only the packaged installer is Windows-only for now.

---

## What you get

### Today
The screen you actually use daily. Every habit as a tappable chip with its current streak, a ring showing how much of today is done, and one line telling you what matters right now — *"Streaks on the line today: Exercise. One tick each keeps them alive."*

![HabitFlow – Today and the monthly grid](assets/Daily-Tracker-Page.png)

### The monthly grid
Every habit × every day, right under Today. Click any cell to fill in a day you forgot. Days before you started a habit are greyed out, so a habit you added yesterday doesn't make last week look like a failure.

![HabitFlow – Light theme](assets/Daily-Tracker-Page-Light.png)

### Insights, not just charts
The dashboard leads with **What this means** — plain sentences derived from your own data:

- 🔥 *14-day streak on 5:30 AM Wake Up — your longest run yet. Don't break it today.*
- 📅 *Sundays are your weak spot (28%) versus Fridays (69%). Plan a lighter Sunday routine.*
- 📈 *September is running 9 points ahead of August (60% vs 51%).*
- 🎯 *Budget Tracking is the one dragging the month down (0/6). Make it smaller rather than dropping it.*

![HabitFlow – Dashboard insights](assets/Dashboard.png)

Below that: current and best streak per habit, and a weekday rhythm chart over the last 90 days.

![HabitFlow – Streaks and weekly rhythm](assets/Dashboard-Streaks.png)

### Excel export
A formatted, multi-sheet workbook for any month — overview with charts, the full habit grid, and a per-habit analysis sheet. Good for sharing, printing, or doing your own analysis.

![HabitFlow Excel – Overview](assets/Excel-Export-1.png)
![HabitFlow Excel – Grid](assets/Excel-Export-2.png)
![HabitFlow Excel – Analysis](assets/Excel-Export-3.png)

### Backup and restore
The **⤓** menu in the header downloads everything as one JSON file, and restores from one. Use it to move to a new computer, or before you experiment.

![HabitFlow – Backup and restore menu](assets/Data-Menu.png)

### Habits on your terms
Name, emoji, colour — and a **Tracking since** date, so you decide which days a habit is judged on.

![HabitFlow – Adding a habit](assets/Adding-New-Habit.png)

---

## Your data

Everything lives in one SQLite file (plus small `-wal`/`-shm` sidecars SQLite keeps beside it):

```
%APPDATA%\HabitFlow\habits.db
```

To open that folder: press `Win + R`, paste `%APPDATA%\HabitFlow`, press Enter. (The **⤓** menu in the app has a **Where is my data?** entry that shows the exact path too.)

- **Nothing leaves your machine.** The app only listens on `127.0.0.1` and refuses requests that arrive under any other hostname.
- **Updating keeps your history.** Installing a new version over the old one leaves the database alone.
- **Uninstalling asks first** before deleting your history.
- **Starting fresh:** delete `habits.db` and relaunch. You get a clean database with the example habits back.
- **Something went wrong?** Errors are written to `%APPDATA%\HabitFlow\habitflow.log`.

---

## How percentages are calculated

Worth knowing, because most trackers get this wrong and quietly demoralise you:

- A habit only counts on days it was actually being tracked — from the day you created it to the day you stopped. **Adding a habit today does not retroactively ruin last month**, and removing one does not rewrite your history.
- You can move a habit's start date back (**Edit habit → Tracking since**) if you want to fill in history you already have on paper.
- A *perfect day* means everything you were tracking **that day** got done.
- The current month is scored against days that have actually happened, not the whole month.
- A streak survives today being unfinished — the day isn't over. It shows as ⚠ *at risk* instead.

---

## Running from source

```bash
pip install -r requirements.txt
python app.py
```

The terminal prints the URL. Requires Python 3.9+.

Useful environment variables:

| Variable | Effect |
| --- | --- |
| `HABITFLOW_DATA_DIR` | Store the database somewhere else (handy for testing) |
| `HABITFLOW_NO_BROWSER=1` | Don't open a browser on start |

The app tries ports `8050 → 11050 → 12050 → 13050` and takes the first free one. If HabitFlow is already running on one of them, launching again just opens that window instead of starting a second copy.

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

Tests run against a temporary database, so your real history is never touched.

### Building the installer yourself

```bash
pip install -r requirements-dev.txt
python packaging/make_icon.py         # assets/habitflow.ico
python packaging/make_version.py      # exe version resource
pyinstaller --noconfirm packaging/habitflow.spec
iscc /DAppVersion=1.1.0 packaging\habitflow.iss
# -> dist/HabitFlow-Setup-1.1.0.exe
```

[Inno Setup 6](https://jrsoftware.org/isdl.php) is needed for the last step (`winget install JRSoftware.InnoSetup`).

### Cutting a release

```bash
git tag v1.1.0
git push origin v1.1.0
```

GitHub Actions runs the tests, builds the app, smoke-tests the built exe, compiles the installer and attaches both the setup exe and the portable zip to a new Release.

---

## Project layout

```text
Daily-Tracker/
├── app.py                     # Server, database, JSON API, insights
├── requirements.txt           # Runtime dependencies
├── requirements-dev.txt       # + tests and build tooling
├── templates/
│   ├── index.html             # Today + the monthly grid
│   └── dashboard.html         # Insights, streaks, trends
├── static/
│   ├── favicon.svg
│   └── vendor/chart.umd.min.js   # bundled, so charts work offline
├── packaging/
│   ├── habitflow.spec         # PyInstaller (one-folder)
│   ├── habitflow.iss          # Inno Setup installer
│   ├── make_icon.py           # generates assets/habitflow.ico
│   └── make_version.py        # generates the exe version resource
├── tests/test_app.py
└── assets/                    # habitflow.ico + screenshots
```

---

## Why this exists

The idea is to help people stay consistent without paying a subscription to look at their own data. A similar app was doing the rounds on Instagram behind a paywall; this is a free, open alternative with the same goal — track daily habits, feel good about consistency — that you can read, run and change yourself.

## Contributing

Issues and pull requests welcome. Keep changes focused, match the existing style in `app.py` and the templates, and run `python -m pytest tests -q` before opening a PR.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
