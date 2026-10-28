# HTTP API

HabitFlow's pages are built on a small JSON API, and you can call it yourself. It listens on `127.0.0.1` only, on the first free port of `8050`, `11050`, `12050`, `13050`. The examples use `8050`. `GET /api/health` tells you which copy you reached.

All request bodies are JSON and need `Content-Type: application/json`. Errors on any `/api/` path look like this, with a matching status code:

```json
{"error": "Habit not found"}
```

Requests addressed to any host other than `127.0.0.1`, `localhost` or `::1` get a `403`. Dates are `YYYY-MM-DD`; months are `1` to `12`.

## Health

| Method and path | Result |
| --- | --- |
| `GET /api/health` | `{"app": "HabitFlow", "version": "1.1.0", "db": "<path to habits.db>"}` |
| `POST /api/heartbeat` | `204`. The pages call this every 10 seconds so the packaged app knows a tab is open |

## Habits

A habit looks like this:

```json
{"id": 1, "name": "5:30 AM Wake Up", "emoji": "🌅", "color": "#f59e0b",
 "created_at": "2026-03-02", "active": 1, "deactivated_at": null}
```

| Method and path | Body | Result |
| --- | --- | --- |
| `GET /api/habits` | | Active habits |
| `GET /api/habits?year=2026&month=2` | | Every habit that was tracked at any point in that month, including ones removed later |
| `POST /api/habits` | `name` (required, up to 80 characters), `emoji`, `color` (`#rrggbb`), `created_at` | `201` and the new habit. `created_at` defaults to today |
| `PUT /api/habits/<id>` | any of `name`, `emoji`, `color`, `created_at` | The updated habit. Omitted or invalid fields keep their value. `created_at` cannot be in the future |
| `DELETE /api/habits/<id>` | | Stops tracking from today. History is kept. `{"success": true}` |
| `POST /api/habits/<id>/restore` | | Brings a removed habit back into daily tracking |

## Check-ins

| Method and path | Body | Result |
| --- | --- | --- |
| `GET /api/completions/<year>/<month>` | | An object keyed `"<habit_id>_<date>"` with the value `true` for every tick that month |
| `POST /api/completions/toggle` | `habit_id`, `date` | `{"completed": true, "habit_id": 1, "date": "2026-10-28"}` |

The toggle endpoint flips the state, so calling it twice on the same day removes the tick. Read the month first if your script must not untick. It answers `400` for a bad date, a day that has not happened yet, or a day before the habit's `created_at` or after its `deactivated_at`, and `404` for an unknown habit.

## Stats and insights

| Method and path | Result |
| --- | --- |
| `GET /api/stats/<year>/<month>` | `total_done`, `total_possible`, `total_habits`, `overall_pct`, `days_elapsed`, `last_day`, `habit_stats` (per habit: `actual`, `goal`, `pct`) and `day_stats` (per day: `done`, `total`, `pct`) |
| `GET /api/stats/year/<year>` | `{"year": 2026, "months": [...]}` with the same summary fields for each of the 12 months |
| `GET /api/insights/<year>/<month>` | `highlights` (the plain-language sentences, each with `icon`, `tone`, `text`), `streaks`, `today`, `rhythm`, `top_habit`, `weak_habit`, `perfect_days`, `active_days`, `overall_pct`, `prev_pct`, `momentum` |

Percentages count only the days a habit was tracked. See [ARCHITECTURE.md](ARCHITECTURE.md#the-rules-behind-the-numbers).

## Backup, restore and export

| Method and path | Result |
| --- | --- |
| `GET /api/backup` | A JSON download, `habitflow-backup-<date>.json`, with `app`, `version`, `exported_at`, `habits` and `completions` |
| `POST /api/restore` | Body is a backup file. **Replaces** all habits and completions, in one transaction. `{"success": true, "habits": 8, "completions": 630}`. A file that is not a HabitFlow backup gets `400` and changes nothing |
| `GET /api/export/<year>/<month>` | An `.xlsx` download with the Overview, Habit Tracker and Habit Analysis sheets |

```bash
# take a backup, then restore it later
curl -OJ http://127.0.0.1:8050/api/backup
curl -X POST http://127.0.0.1:8050/api/restore \
  -H "Content-Type: application/json" --data-binary @habitflow-backup-2026-10-28.json
```

## Stability

The API exists to serve the bundled pages, and it is not versioned. The backup file format is the more stable contract: restore fills in any missing field with a default. If you build on the API, pin the version you tested against and check `GET /api/health`.
