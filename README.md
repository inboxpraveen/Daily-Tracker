# HabitFlow — Daily Tracker

A local Flask + SQLite habit tracker dashboard.

## Setup & Run

```bash
# 1. Install dependencies
pip install flask

# 2. Run the app
python app.py

# 3. Open in browser
# → http://localhost:5050
```

## Features
- Add / edit / remove habits with emoji + color
- Monthly calendar grid with daily check-ins
- Per-habit and per-day progress bars
- Analysis sidebar with goal vs actual
- Today's snapshot stats
- Navigate between months
- Fully responsive (mobile-friendly)
- Data persists in `habits.db` (SQLite)

## Files
```
habit-tracker/
├── app.py            ← Flask backend + REST API
├── requirements.txt
├── habits.db         ← Created automatically on first run
└── templates/
    └── index.html    ← Full SPA frontend
```
