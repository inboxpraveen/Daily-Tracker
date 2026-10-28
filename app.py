from flask import Flask, jsonify, request, render_template
from werkzeug.exceptions import HTTPException
import sqlite3
import os
import sys
import time
import threading
from datetime import date, datetime, timedelta
import calendar

APP_NAME = 'HabitFlow'
APP_VERSION = '1.1.1'


def _resource(rel):
    """Resolve a bundled-file path for both dev and PyInstaller builds."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def _data_dir():
    """Return a writable directory for user data that survives app updates."""
    override = os.environ.get('HABITFLOW_DATA_DIR')
    if override:
        path = os.path.abspath(override)
    else:
        if sys.platform == 'win32':
            base = os.environ.get('APPDATA', os.path.expanduser('~'))
        else:
            base = os.path.expanduser('~/.local/share')
        path = os.path.join(base, 'HabitFlow')
    os.makedirs(path, exist_ok=True)
    return path


app = Flask(__name__,
            template_folder=_resource('templates'),
            static_folder=_resource('static'))
DB_PATH = os.path.join(_data_dir(), 'habits.db')
LOG_PATH = os.path.join(_data_dir(), 'habitflow.log')

# ── Auto-shutdown when browser tab is closed (exe mode only) ─────────────────
_last_seen = time.time()
_IDLE_TIMEOUT = 120  # seconds; the browser sends a heartbeat every 10s


@app.before_request
def _refresh_last_seen():
    global _last_seen
    _last_seen = time.time()


@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    return '', 204


def _idle_watchdog():
    while True:
        time.sleep(10)
        if time.time() - _last_seen > _IDLE_TIMEOUT:
            os._exit(0)
# ─────────────────────────────────────────────────────────────────────────────


# ── Local-only guard ─────────────────────────────────────────────────────────
# The server binds to 127.0.0.1, but a hostile web page could still reach it via
# a rebound DNS name. Only serve requests that arrived addressed to localhost.
_ALLOWED_HOSTS = {'127.0.0.1', 'localhost', '[::1]', '::1'}


@app.before_request
def _reject_foreign_host():
    host = (request.host or '').rsplit(':', 1)[0]
    if host and host not in _ALLOWED_HOSTS:
        return jsonify({'error': 'HabitFlow only serves localhost'}), 403


@app.errorhandler(Exception)
def _json_errors(err):
    """Never hand the browser an HTML error page for an /api call.

    Pages keep Flask's normal behaviour: a stray /favicon.ico should be an
    ordinary 404, not a logged traceback.
    """
    if not request.path.startswith('/api/'):
        if isinstance(err, HTTPException):
            return err
        raise err
    code = err.code if isinstance(err, HTTPException) else 500
    if code == 500:
        app.logger.exception('Unhandled error on %s', request.path)
    message = getattr(err, 'description', None) or str(err) or 'Server error'
    return jsonify({'error': message}), code


@app.route('/api/health')
def health():
    return jsonify({'app': APP_NAME, 'version': APP_VERSION, 'db': DB_PATH})


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=15000')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def _add_column(conn, table, column, ddl):
    """Idempotent ALTER TABLE for databases created by an older version."""
    cols = {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
    if column not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')
        return True
    return False


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            emoji TEXT DEFAULT '✅',
            color TEXT DEFAULT '#22c55e',
            created_at TEXT DEFAULT (date('now')),
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            completion_date TEXT NOT NULL,
            UNIQUE(habit_id, completion_date),
            FOREIGN KEY (habit_id) REFERENCES habits(id)
        );
        CREATE INDEX IF NOT EXISTS idx_completions_date ON completions(completion_date);
        CREATE INDEX IF NOT EXISTS idx_completions_habit ON completions(habit_id, completion_date);
    ''')

    # ── migration: remember *when* a habit stopped being tracked ─────────────
    # Without this, deleting a habit today silently rewrote every past month's
    # completion rate. Existing soft-deleted habits are backfilled to the last
    # day they were actually used, which preserves their real history.
    if _add_column(conn, 'habits', 'deactivated_at', 'TEXT'):
        conn.execute('''
            UPDATE habits SET deactivated_at = COALESCE(
                (SELECT MAX(completion_date) FROM completions WHERE habit_id = habits.id),
                created_at, date('now'))
            WHERE active = 0
        ''')
    # Older rows can carry a NULL created_at; stats need a real start date.
    conn.execute('''
        UPDATE habits SET created_at = COALESCE(
            (SELECT MIN(completion_date) FROM completions WHERE habit_id = habits.id),
            date('now'))
        WHERE created_at IS NULL OR created_at = ''
    ''')

    # Seed some default habits if empty
    cur = conn.execute('SELECT COUNT(*) FROM habits')
    if cur.fetchone()[0] == 0:
        defaults = [
            ('5:30 AM Wake Up', '🌅', '#f59e0b'),
            ('Exercise', '💪', '#ef4444'),
            ('Read 10 Pages', '📖', '#3b82f6'),
            ('Drink 8 Glasses Water', '💧', '#06b6d4'),
            ('Meditate', '🧘', '#8b5cf6'),
            ('No Social Media', '📵', '#ec4899'),
            ('Budget Tracking', '💰', '#10b981'),
            ('Deep Work Session', '🎯', '#f97316'),
        ]
        conn.executemany('INSERT INTO habits (name, emoji, color) VALUES (?,?,?)', defaults)
    conn.commit()
    conn.close()


# ── Date / eligibility helpers ───────────────────────────────────────────────
# A habit only "counts" on days it was actually being tracked: from the day it
# was created until the day it was removed. Everything below shares these rules
# so the tracker, dashboard and Excel export can never disagree.

def _month_bounds(year, month):
    last_day = calendar.monthrange(year, month)[1]
    return (f'{year:04d}-{month:02d}-01', f'{year:04d}-{month:02d}-{last_day:02d}', last_day)


def _period_habits(conn, start, end, include_inactive=True):
    """Habits that were being tracked at any point between start and end."""
    if include_inactive:
        rows = conn.execute(
            'SELECT * FROM habits '
            'WHERE COALESCE(created_at, ?) <= ? '
            '  AND (deactivated_at IS NULL OR deactivated_at >= ?) '
            'ORDER BY id', (start, end, start)
        ).fetchall()
    else:
        rows = conn.execute('SELECT * FROM habits WHERE active=1 ORDER BY id').fetchall()
    return [dict(r) for r in rows]


def _habit_window(habit, start, end):
    """The (first, last) date this habit counts for inside start..end."""
    lo = max(start, habit.get('created_at') or start)
    hi = end
    if habit.get('deactivated_at'):
        hi = min(hi, habit['deactivated_at'])
    return lo, hi


def _days_between(lo, hi):
    if lo > hi:
        return 0
    a = datetime.strptime(lo, '%Y-%m-%d').date()
    b = datetime.strptime(hi, '%Y-%m-%d').date()
    return (b - a).days + 1


def _habit_goal(habit, start, end):
    """How many days this habit could have been checked off in the range."""
    lo, hi = _habit_window(habit, start, end)
    return _days_between(lo, hi)


def _counts_on(habit, day):
    lo = habit.get('created_at') or day
    if day < lo:
        return False
    if habit.get('deactivated_at') and day > habit['deactivated_at']:
        return False
    return True


def _elapsed_end(year, month):
    """Last day of the month that has actually happened yet ('' if it is future)."""
    start, end, _ = _month_bounds(year, month)
    today = date.today().isoformat()
    if today < start:
        return ''
    return min(end, today)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')


def _month_detail(conn, year, month):
    """Everything the tracker, dashboard and export need for one month.

    Percentages are per-habit aware: a habit only contributes days between the
    date it was created and the date it was removed, so adding a habit today
    does not retroactively ruin last month.
    """
    start, end, last_day = _month_bounds(year, month)
    elapsed_end = _elapsed_end(year, month)
    habits = _period_habits(conn, start, end)

    done_rows = conn.execute(
        'SELECT habit_id, completion_date FROM completions '
        'WHERE completion_date BETWEEN ? AND ?', (start, end)
    ).fetchall()
    done_set = {(r['habit_id'], r['completion_date']) for r in done_rows}

    habit_stats = []
    total_done = 0
    total_possible = 0
    for h in habits:
        goal = _habit_goal(h, start, elapsed_end) if elapsed_end else 0
        lo, hi = _habit_window(h, start, elapsed_end or start)
        actual = sum(1 for (hid, d) in done_set
                     if hid == h['id'] and (elapsed_end and lo <= d <= hi))
        total_done += actual
        total_possible += goal
        habit_stats.append({
            'id': h['id'], 'name': h['name'], 'emoji': h['emoji'], 'color': h['color'],
            'created_at': h['created_at'], 'deactivated_at': h.get('deactivated_at'),
            'active': h['active'],
            'goal': goal, 'actual': actual,
            'pct': round((actual / goal * 100) if goal else 0, 1),
        })

    day_stats = []
    for d in range(1, last_day + 1):
        day_str = f'{year:04d}-{month:02d}-{d:02d}'
        eligible = [h for h in habits if _counts_on(h, day_str)]
        done = sum(1 for h in eligible if (h['id'], day_str) in done_set)
        day_stats.append({
            'day': d, 'date': day_str, 'done': done, 'total': len(eligible),
            'pct': round((done / len(eligible) * 100) if eligible else 0, 1),
        })

    days_elapsed = _days_between(start, elapsed_end) if elapsed_end else 0
    return {
        'total_habits': len(habits),
        'last_day': last_day,
        'days_elapsed': days_elapsed,
        'total_done': total_done,
        'total_possible': total_possible,
        'overall_pct': round((total_done / total_possible * 100) if total_possible else 0, 1),
        'habit_stats': habit_stats,
        'day_stats': day_stats,
        'habits': habits,
    }


def _month_summary(conn, year, month):
    """Headline numbers for one month, without the per-day/per-habit detail."""
    d = _month_detail(conn, year, month)
    return {k: d[k] for k in ('total_habits', 'last_day', 'days_elapsed',
                              'total_done', 'total_possible', 'overall_pct')}


@app.route('/api/stats/year/<int:year>', methods=['GET'])
def get_year_stats(year):
    conn = get_db()
    months = []
    names = [
        '', 'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December',
    ]
    for m in range(1, 13):
        s = _month_summary(conn, year, m)
        months.append({
            'month': m,
            'month_name': names[m],
            **s,
        })
    conn.close()
    return jsonify({'year': year, 'months': months})

def _payload():
    """Request body as a dict, whatever the client sent."""
    return request.get_json(silent=True) or {}


_ISO = '%Y-%m-%d'


def _valid_date(s):
    try:
        datetime.strptime(s, _ISO)
        return True
    except (TypeError, ValueError):
        return False


def _clean_color(value, fallback='#22c55e'):
    v = str(value or '').strip()
    if len(v) == 7 and v[0] == '#':
        try:
            int(v[1:], 16)
            return v.lower()
        except ValueError:
            pass
    return fallback


@app.route('/api/habits', methods=['GET'])
def get_habits():
    """Active habits, or everything tracked during ?year=&month= if given.

    Passing a month matters for history: a habit you removed in March should
    still show up when you look back at February.
    """
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    conn = get_db()
    if year and month and 1 <= month <= 12:
        start, end, _ = _month_bounds(year, month)
        habits = _period_habits(conn, start, end)
    else:
        habits = _period_habits(conn, '', '', include_inactive=False)
    conn.close()
    return jsonify(habits)


@app.route('/api/habits', methods=['POST'])
def add_habit():
    data = _payload()
    name = str(data.get('name', '')).strip()
    if not name:
        return jsonify({'error': 'Please give the habit a name'}), 400
    emoji = str(data.get('emoji') or '✅')[:8]
    color = _clean_color(data.get('color'))
    created = data.get('created_at')
    if not _valid_date(created):
        created = date.today().isoformat()
    conn = get_db()
    cur = conn.execute(
        'INSERT INTO habits (name, emoji, color, created_at) VALUES (?,?,?,?)',
        (name[:80], emoji, color, created))
    conn.commit()
    habit = conn.execute('SELECT * FROM habits WHERE id=?', (cur.lastrowid,)).fetchone()
    conn.close()
    return jsonify(dict(habit)), 201


@app.route('/api/habits/<int:habit_id>', methods=['DELETE'])
def delete_habit(habit_id):
    """Stop tracking a habit from today on, keeping its history intact."""
    conn = get_db()
    row = conn.execute('SELECT id FROM habits WHERE id=?', (habit_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({'error': 'Habit not found'}), 404
    conn.execute('UPDATE habits SET active=0, deactivated_at=? WHERE id=?',
                 (date.today().isoformat(), habit_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/habits/<int:habit_id>', methods=['PUT'])
def update_habit(habit_id):
    data = _payload()
    conn = get_db()
    habit = conn.execute('SELECT * FROM habits WHERE id=?', (habit_id,)).fetchone()
    if habit is None:
        conn.close()
        return jsonify({'error': 'Habit not found'}), 404

    name = str(data.get('name', habit['name'])).strip() or habit['name']
    emoji = str(data.get('emoji') or habit['emoji'])[:8]
    color = _clean_color(data.get('color'), habit['color'])
    created = data.get('created_at')
    if not _valid_date(created):
        created = habit['created_at']
    if created > date.today().isoformat():
        created = date.today().isoformat()

    conn.execute('UPDATE habits SET name=?, emoji=?, color=?, created_at=? WHERE id=?',
                 (name[:80], emoji, color, created, habit_id))
    conn.commit()
    habit = conn.execute('SELECT * FROM habits WHERE id=?', (habit_id,)).fetchone()
    conn.close()
    return jsonify(dict(habit))


@app.route('/api/habits/<int:habit_id>/restore', methods=['POST'])
def restore_habit(habit_id):
    """Bring a removed habit back into daily tracking."""
    conn = get_db()
    row = conn.execute('SELECT id FROM habits WHERE id=?', (habit_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({'error': 'Habit not found'}), 404
    conn.execute('UPDATE habits SET active=1, deactivated_at=NULL WHERE id=?', (habit_id,))
    conn.commit()
    habit = conn.execute('SELECT * FROM habits WHERE id=?', (habit_id,)).fetchone()
    conn.close()
    return jsonify(dict(habit))


@app.route('/api/completions/<int:year>/<int:month>', methods=['GET'])
def get_completions(year, month):
    conn = get_db()
    start, end, _ = _month_bounds(year, month)
    rows = conn.execute(
        'SELECT habit_id, completion_date FROM completions WHERE completion_date BETWEEN ? AND ?',
        (start, end)
    ).fetchall()
    conn.close()
    return jsonify({f"{r['habit_id']}_{r['completion_date']}": True for r in rows})


@app.route('/api/completions/toggle', methods=['POST'])
def toggle_completion():
    data = _payload()
    try:
        habit_id = int(data.get('habit_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'habit_id must be a number'}), 400
    comp_date = str(data.get('date', ''))
    if not _valid_date(comp_date):
        return jsonify({'error': 'date must look like YYYY-MM-DD'}), 400
    if comp_date > date.today().isoformat():
        return jsonify({'error': "You can't check off a day that hasn't happened yet"}), 400

    conn = get_db()
    habit = conn.execute('SELECT * FROM habits WHERE id=?', (habit_id,)).fetchone()
    if habit is None:
        conn.close()
        return jsonify({'error': 'Habit not found'}), 404
    habit = dict(habit)
    if not _counts_on(habit, comp_date):
        conn.close()
        return jsonify({'error': f"{habit['name']} wasn't being tracked on that day"}), 400

    existing = conn.execute(
        'SELECT id FROM completions WHERE habit_id=? AND completion_date=?',
        (habit_id, comp_date)
    ).fetchone()
    if existing:
        conn.execute('DELETE FROM completions WHERE habit_id=? AND completion_date=?',
                     (habit_id, comp_date))
        completed = False
    else:
        conn.execute('INSERT INTO completions (habit_id, completion_date) VALUES (?,?)',
                     (habit_id, comp_date))
        completed = True
    conn.commit()
    conn.close()
    return jsonify({'completed': completed, 'habit_id': habit_id, 'date': comp_date})


@app.route('/api/stats/<int:year>/<int:month>', methods=['GET'])
def get_stats(year, month):
    conn = get_db()
    detail = _month_detail(conn, year, month)
    conn.close()
    detail.pop('habits', None)
    return jsonify(detail)

# ═══════════════════════════════════════════════════════════════════════════
# INSIGHTS: turn the raw ticks into things worth acting on
# ═══════════════════════════════════════════════════════════════════════════

WEEKDAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                 'Friday', 'Saturday', 'Sunday']
MONTH_NAMES = ['', 'January', 'February', 'March', 'April', 'May', 'June',
               'July', 'August', 'September', 'October', 'November', 'December']

STREAK_WINDOW_DAYS = 90   # how far back the weekday/rhythm analysis looks


def _streaks(habit, done_dates, today):
    """Current and best run of consecutive days for one habit.

    The current streak survives a missing tick for *today*, because the day is not
    over yet. It is reported as `at_risk` instead, which is what actually
    nudges someone to open the app and finish the day.
    """
    if not done_dates:
        return {'current': 0, 'best': 0, 'at_risk': False, 'done_today': False}

    done_today = today.isoformat() in done_dates
    anchor = today if done_today else today - timedelta(days=1)
    current = 0
    if anchor.isoformat() in done_dates:
        d = anchor
        while d.isoformat() in done_dates:
            current += 1
            d -= timedelta(days=1)

    best = run = 0
    prev = None
    for ds in sorted(done_dates):
        d = datetime.strptime(ds, _ISO).date()
        run = run + 1 if prev is not None and (d - prev).days == 1 else 1
        best = max(best, run)
        prev = d

    return {
        'current': current,
        'best': max(best, current),
        'at_risk': current > 0 and not done_today,
        'done_today': done_today,
    }


def _weekday_rhythm(habits, done_by_habit, today):
    """Completion rate per day of the week over the recent window."""
    done = [0] * 7
    possible = [0] * 7
    start = today - timedelta(days=STREAK_WINDOW_DAYS - 1)
    for i in range(STREAK_WINDOW_DAYS):
        d = start + timedelta(days=i)
        ds = d.isoformat()
        wd = d.weekday()
        for h in habits:
            if not _counts_on(h, ds):
                continue
            possible[wd] += 1
            if ds in done_by_habit.get(h['id'], ()):
                done[wd] += 1
    rows = [{
        'weekday': WEEKDAY_NAMES[i],
        'short': WEEKDAY_NAMES[i][:3],
        'done': done[i],
        'possible': possible[i],
        'pct': round((done[i] / possible[i] * 100) if possible[i] else 0, 1),
    } for i in range(7)]
    rated = [r for r in rows if r['possible'] >= 2]
    best = max(rated, key=lambda r: r['pct']) if rated else None
    worst = min(rated, key=lambda r: r['pct']) if rated else None
    return {'days': rows, 'best': best, 'worst': worst,
            'window_days': STREAK_WINDOW_DAYS}


@app.route('/api/insights/<int:year>/<int:month>')
def get_insights(year, month):
    if not 1 <= month <= 12:
        return jsonify({'error': 'Month must be 1-12'}), 400

    today = date.today()
    today_str = today.isoformat()
    conn = get_db()

    detail = _month_detail(conn, year, month)
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    prev = _month_summary(conn, prev_year, prev_month)

    all_habits = [dict(r) for r in conn.execute('SELECT * FROM habits ORDER BY id')]
    done_by_habit = {}
    for r in conn.execute('SELECT habit_id, completion_date FROM completions'):
        done_by_habit.setdefault(r['habit_id'], set()).add(r['completion_date'])
    conn.close()

    live = [h for h in all_habits if h['active']]

    # ── streaks ──────────────────────────────────────────────────────────
    streaks = []
    for h in live:
        s = _streaks(h, done_by_habit.get(h['id'], set()), today)
        streaks.append({
            'id': h['id'], 'name': h['name'], 'emoji': h['emoji'], 'color': h['color'],
            **s,
        })
    streaks.sort(key=lambda s: (-s['current'], -s['best'], s['name']))

    # ── today ────────────────────────────────────────────────────────────
    due = [h for h in live if _counts_on(h, today_str)]
    done_today = [h for h in due if today_str in done_by_habit.get(h['id'], ())]
    remaining = [{'id': h['id'], 'name': h['name'], 'emoji': h['emoji'], 'color': h['color']}
                 for h in due if today_str not in done_by_habit.get(h['id'], ())]
    today_block = {
        'date': today_str,
        'done': len(done_today),
        'total': len(due),
        'pct': round((len(done_today) / len(due) * 100) if due else 0, 1),
        'remaining': remaining,
    }

    rhythm = _weekday_rhythm(all_habits, done_by_habit, today)

    # ── habit standouts for the viewed month (ignore barely-tracked ones) ──
    rated = [h for h in detail['habit_stats'] if h['goal'] >= 3]
    top = max(rated, key=lambda h: h['pct']) if rated else None
    weak = min(rated, key=lambda h: h['pct']) if rated else None

    perfect_days = sum(1 for d in detail['day_stats']
                       if d['total'] and d['done'] == d['total'])
    active_days = sum(1 for d in detail['day_stats'] if d['done'] > 0)
    momentum = round(detail['overall_pct'] - prev['overall_pct'], 1)

    # ── plain-language highlights ────────────────────────────────────────
    highlights = []
    leader = streaks[0] if streaks else None
    if leader and leader['current'] >= 2:
        if leader['current'] >= leader['best']:
            highlights.append({
                'icon': '🔥', 'tone': 'good',
                'text': f"{leader['current']}-day streak on {leader['name']}, "
                        f"your longest run yet. Don't break it today.",
            })
        else:
            gap = leader['best'] - leader['current']
            highlights.append({
                'icon': '🔥', 'tone': 'good',
                'text': f"{leader['current']}-day streak on {leader['name']}, "
                        f"{gap} day{'s' if gap != 1 else ''} off your record of {leader['best']}.",
            })

    at_risk = [s for s in streaks if s['at_risk']]
    if at_risk:
        names = ', '.join(s['name'] for s in at_risk[:3])
        more = f" (+{len(at_risk) - 3} more)" if len(at_risk) > 3 else ''
        highlights.append({
            'icon': '⏳', 'tone': 'warn',
            'text': f"Streaks on the line today: {names}{more}. "
                    f"One tick each keeps them alive.",
        })
    elif today_block['total'] and today_block['done'] == today_block['total']:
        highlights.append({
            'icon': '🏅', 'tone': 'good',
            'text': f"Every habit is checked off today. That is a perfect day, "
                    f"number {perfect_days} this month.",
        })
    elif today_block['remaining']:
        left = len(today_block['remaining'])
        highlights.append({
            'icon': '📌', 'tone': 'info',
            'text': f"{left} habit{'s' if left != 1 else ''} still open today: "
                    + ', '.join(h['name'] for h in today_block['remaining'][:3]) + '.',
        })

    if rhythm['best'] and rhythm['worst'] and rhythm['best']['weekday'] != rhythm['worst']['weekday']:
        spread = rhythm['best']['pct'] - rhythm['worst']['pct']
        if spread >= 15:
            highlights.append({
                'icon': '📅', 'tone': 'info',
                'text': f"{rhythm['worst']['weekday']}s are your weak spot "
                        f"({rhythm['worst']['pct']}%) versus {rhythm['best']['weekday']}s "
                        f"({rhythm['best']['pct']}%). Plan a lighter {rhythm['worst']['weekday']} routine.",
            })

    if prev['total_possible'] and detail['total_possible']:
        if momentum >= 5:
            highlights.append({
                'icon': '📈', 'tone': 'good',
                'text': f"{MONTH_NAMES[month]} is running {momentum} points ahead of "
                        f"{MONTH_NAMES[prev_month]} ({detail['overall_pct']}% vs {prev['overall_pct']}%).",
            })
        elif momentum <= -5:
            highlights.append({
                'icon': '📉', 'tone': 'warn',
                'text': f"{MONTH_NAMES[month]} is {abs(momentum)} points behind "
                        f"{MONTH_NAMES[prev_month]} ({detail['overall_pct']}% vs {prev['overall_pct']}%). "
                        f"Pick one habit to defend.",
            })

    if weak and weak['pct'] < 50 and (not top or weak['id'] != top['id']):
        highlights.append({
            'icon': '🎯', 'tone': 'warn',
            'text': f"{weak['name']} is the one dragging the month down "
                    f"({weak['actual']}/{weak['goal']}, {weak['pct']}%). "
                    f"Make it smaller rather than dropping it.",
        })
    if top and top['pct'] >= 80:
        highlights.append({
            'icon': '⭐', 'tone': 'good',
            'text': f"{top['name']} is locked in at {top['pct']}% "
                    f"({top['actual']}/{top['goal']} days). It is basically automatic now.",
        })

    if not highlights:
        highlights.append({
            'icon': '🌱', 'tone': 'info',
            'text': 'Check off a few days and HabitFlow will start pointing out '
                    'your streaks, strong days and weak spots here.',
        })

    return jsonify({
        'year': year,
        'month': month,
        'month_name': MONTH_NAMES[month],
        'today': today_block,
        'streaks': streaks,
        'rhythm': rhythm,
        'top_habit': top,
        'weak_habit': weak,
        'perfect_days': perfect_days,
        'active_days': active_days,
        'overall_pct': detail['overall_pct'],
        'prev_pct': prev['overall_pct'],
        'momentum': momentum,
        'highlights': highlights,
    })


# ═══════════════════════════════════════════════════════════════════════════
# BACKUP / RESTORE: your data should never be trapped in one .db file
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/api/backup')
def backup():
    from flask import send_file
    import io
    import json

    conn = get_db()
    habits = [dict(r) for r in conn.execute('SELECT * FROM habits ORDER BY id')]
    completions = [dict(r) for r in conn.execute(
        'SELECT habit_id, completion_date FROM completions ORDER BY completion_date, habit_id')]
    conn.close()

    payload = {
        'app': APP_NAME,
        'version': APP_VERSION,
        'exported_at': datetime.now().isoformat(timespec='seconds'),
        'habits': habits,
        'completions': completions,
    }
    buf = io.BytesIO(json.dumps(payload, indent=2, ensure_ascii=False).encode('utf-8'))
    buf.seek(0)
    return send_file(buf, mimetype='application/json', as_attachment=True,
                     download_name=f'habitflow-backup-{date.today().isoformat()}.json')


@app.route('/api/restore', methods=['POST'])
def restore():
    """Replace everything with a previously downloaded backup file."""
    data = _payload()
    habits = data.get('habits')
    completions = data.get('completions')
    if not isinstance(habits, list) or not isinstance(completions, list):
        return jsonify({'error': 'That does not look like a HabitFlow backup file'}), 400

    conn = get_db()
    try:
        with conn:
            conn.execute('DELETE FROM completions')
            conn.execute('DELETE FROM habits')
            for h in habits:
                created = h.get('created_at')
                conn.execute(
                    'INSERT INTO habits (id, name, emoji, color, created_at, active, deactivated_at) '
                    'VALUES (?,?,?,?,?,?,?)',
                    (h.get('id'), str(h.get('name', 'Habit'))[:80], str(h.get('emoji') or '✅')[:8],
                     _clean_color(h.get('color')),
                     created if _valid_date(created) else date.today().isoformat(),
                     1 if h.get('active', 1) else 0,
                     h.get('deactivated_at') if _valid_date(h.get('deactivated_at')) else None))
            for c in completions:
                if _valid_date(c.get('completion_date')):
                    conn.execute('INSERT OR IGNORE INTO completions (habit_id, completion_date) '
                                 'VALUES (?,?)', (c.get('habit_id'), c['completion_date']))
    except sqlite3.Error as exc:
        conn.close()
        return jsonify({'error': f'Restore failed: {exc}'}), 400
    conn.close()
    return jsonify({'success': True, 'habits': len(habits), 'completions': len(completions)})


@app.route('/api/export/<int:year>/<int:month>')
def export_excel(year, month):
    """Generate a fully-formatted, multi-sheet Excel workbook for the given month."""
    import io
    try:
        import xlsxwriter
    except ImportError:
        return jsonify({'error': 'xlsxwriter not installed. Run: pip install xlsxwriter'}), 500

    from flask import send_file

    if not 1 <= month <= 12:
        return jsonify({'error': 'Month must be 1-12'}), 400

    DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

    conn       = get_db()
    detail     = _month_detail(conn, year, month)
    habits     = detail['habits']
    n_habits   = len(habits)
    last_day   = detail['last_day']
    today_d    = date.today()
    month_name = MONTH_NAMES[month]
    today_str  = today_d.strftime('%Y-%m-%d')
    days_elapsed = detail['days_elapsed']

    start, end, _ = _month_bounds(year, month)

    # ── raw completions set ───────────────────────────────────────
    completions = {
        (r['habit_id'], r['completion_date'])
        for r in conn.execute(
            'SELECT habit_id, completion_date FROM completions '
            'WHERE completion_date BETWEEN ? AND ?', (start, end)
        ).fetchall()
    }

    day_stats   = detail['day_stats']
    habit_stats = [{**h, 'done': h['actual']} for h in detail['habit_stats']]

    total_possible = detail['total_possible']
    total_done     = detail['total_done']
    overall_pct    = detail['overall_pct']

    # ── full-year monthly data ────────────────────────────────────
    year_data = []
    for m in range(1, 13):
        s = _month_summary(conn, year, m)
        year_data.append({'month': m, 'name': MONTH_NAMES[m], **s})
    conn.close()

    # ═══════════════════════════════════════════════════════════════
    # BUILD WORKBOOK
    # ═══════════════════════════════════════════════════════════════
    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {'in_memory': True, 'strings_to_urls': False})

    # ── colour palette ────────────────────────────────────────────
    CA  = '#6366F1'   # accent (indigo)
    CA2 = '#4F46E5'   # accent dark
    CL  = '#EEF2FF'   # accent light
    CL2 = '#E0E7FF'   # accent lighter
    CW  = '#FFFFFF'
    CBG = '#F8FAFC'
    CT  = '#0F172A'   # text
    CT2 = '#5C6B7A'   # text-2
    CB  = '#E4E9F0'   # border
    CG  = '#10B981'   # green
    CGL = '#D1FAE5'
    CAM = '#F59E0B'   # amber
    CAL = '#FEF3C7'
    CR  = '#EF4444'   # red
    CRL = '#FEE2E2'

    BASE = {'font_name': 'Calibri', 'font_size': 10, 'valign': 'vcenter'}

    def F(**kw):
        return wb.add_format({**BASE, **kw})

    # ── reusable formats ──────────────────────────────────────────
    f_title     = F(bold=True, font_size=20, font_color=CT,  bottom=3, bottom_color=CA)
    f_subtitle  = F(font_size=10, font_color=CT2, italic=True)
    f_section   = F(bold=True, font_size=10, font_color=CW, bg_color=CA,
                    top=1, top_color=CA2, bottom=1, bottom_color=CA2,
                    left=1, left_color=CA2, right=1, right_color=CA2)

    f_th        = F(bold=True, font_size=9, font_color=CW, bg_color=CA,
                    border=1, border_color=CA2, align='center', text_wrap=True)
    f_th_left   = F(bold=True, font_size=9, font_color=CW, bg_color=CA,
                    border=1, border_color=CA2, align='left')

    f_day_hdr   = F(bold=True, font_size=8, font_color=CT,       bg_color=CL,  border=1, border_color=CB,  align='center')
    f_day_today = F(bold=True, font_size=8, font_color=CA,       bg_color=CL2, border=1, border_color=CA,  align='center')
    f_day_wknd  = F(bold=True, font_size=8, font_color='#94A3B8', bg_color='#F1F5F9', border=1, border_color=CB, align='center')
    f_dow       = F(font_size=7, font_color=CT2,      bg_color=CL,         border=1, border_color=CB, align='center', italic=True)
    f_dow_today = F(font_size=7, font_color=CA, bold=True, bg_color=CL2, border=1, border_color=CA, align='center', italic=True)
    f_dow_wknd  = F(font_size=7, font_color='#94A3B8', bg_color='#F1F5F9', border=1, border_color=CB, align='center', italic=True)

    f_hlabel    = F(bold=True, font_size=9, font_color=CT,  bg_color=CW,  border=1, border_color=CB, align='left')
    f_hlabel_a  = F(bold=True, font_size=9, font_color=CT,  bg_color=CBG, border=1, border_color=CB, align='left')

    f_empty     = F(font_size=8, font_color='#CBD5E1', bg_color=CW,         border=1, border_color=CB)
    f_empty_a   = F(font_size=8, font_color='#CBD5E1', bg_color=CBG,        border=1, border_color=CB)
    f_empty_fut = F(font_size=8, font_color='#F0F0F0', bg_color='#F8FAFC',  border=1, border_color='#F0F0F0', align='center')
    f_today_mt  = F(font_size=8, font_color='#A5B4FC', bg_color=CL,         border=1, border_color=CA, align='center')

    f_ftlbl     = F(bold=True, font_size=9, font_color='#312E81', bg_color=CL, border=1, border_color='#C7D2FE', align='left')
    f_ftnum     = F(bold=True, font_size=9, font_color='#312E81', bg_color=CL, border=1, border_color='#C7D2FE', align='center')

    f_pg        = F(bold=True, font_size=9, font_color='#065F46', bg_color=CGL, border=1, border_color='#A7F3D0', align='center')
    f_pm        = F(bold=True, font_size=9, font_color='#92400E', bg_color=CAL, border=1, border_color='#FDE68A', align='center')
    f_pb        = F(bold=True, font_size=9, font_color='#991B1B', bg_color=CRL, border=1, border_color='#FECACA', align='center')

    f_cell      = F(font_size=9, font_color=CT, bg_color=CW,  border=1, border_color=CB, align='center')
    f_cell_a    = F(font_size=9, font_color=CT, bg_color=CBG, border=1, border_color=CB, align='center')
    f_cell_l    = F(font_size=9, font_color=CT, bg_color=CW,  border=1, border_color=CB, align='left')
    f_cell_la   = F(font_size=9, font_color=CT, bg_color=CBG, border=1, border_color=CB, align='left')

    f_sv_g  = F(bold=True, font_size=22, font_color=CG,  align='center')
    f_sv_a  = F(bold=True, font_size=22, font_color=CAM, align='center')
    f_sv_ac = F(bold=True, font_size=22, font_color=CA,  align='center')
    f_sv_r  = F(bold=True, font_size=22, font_color=CR,  align='center')
    f_slbl  = F(font_size=8, font_color=CT2, align='center', text_wrap=True)

    # per-habit done-cell formats (custom bg per habit colour)
    habit_fmt = {}
    for h in habits:
        c = h['color'] if h['color'].startswith('#') else '#' + h['color']
        habit_fmt[h['id']] = wb.add_format({
            'font_name': 'Calibri', 'font_size': 9, 'bold': True,
            'font_color': CW, 'bg_color': c,
            'border': 1, 'border_color': c,
            'align': 'center', 'valign': 'vcenter',
        })

    def pct_fmt(v):
        return f_pg if v >= 80 else (f_pm if v >= 50 else f_pb)

    # ═══════════════════════════════════════════════════════════════
    # SHEET 1: Overview
    # ═══════════════════════════════════════════════════════════════
    ws1 = wb.add_worksheet('Overview')
    ws1.set_zoom(100)
    ws1.hide_gridlines(2)
    ws1.set_tab_color(CA)
    ws1.set_column('A:A', 22)
    ws1.set_column('B:E', 14)
    ws1.set_column('F:F', 2)    # spacer
    ws1.set_column('G:P', 9)    # chart area columns
    ws1.set_row(0, 38)
    ws1.set_row(1, 18)
    ws1.set_row(2, 8)           # spacer
    ws1.set_row(3, 52)          # stat values
    ws1.set_row(4, 26)          # stat labels
    ws1.set_row(5, 10)          # spacer

    # title
    ws1.merge_range('A1:E1', f'HabitFlow  ·  Monthly Report', f_title)
    ws1.merge_range('A2:E2',
        f'{month_name} {year}   ·   Generated {today_d.strftime("%B %d, %Y")}', f_subtitle)

    # stat cards (row 4/5 = index 3/4)
    for col_i, (val, lbl, fmt) in enumerate([
        (total_done,                    'Completed\nCheck-ins',   f_sv_g),
        (n_habits,                      'Active\nHabits',         f_sv_a),
        (days_elapsed,                  'Days\nTracked',          f_sv_ac),
        (total_possible - total_done,   'Missed\nCheck-ins',      f_sv_r),
        (f'{overall_pct}%',             'Overall\nCompletion',    f_sv_ac),
    ]):
        ws1.write(3, col_i, val, fmt)
        ws1.write(4, col_i, lbl, f_slbl)

    # ── daily data table (provides chart data source) ─────────────
    ws1.set_row(6, 18)
    ws1.merge_range('A7:E7', f'Daily Breakdown: {month_name} {year}', f_section)
    for ci, hdr in enumerate(['Day', 'Date', 'Completed', 'Total Habits', 'Completion %']):
        ws1.write(7, ci, hdr, f_th if ci else f_th_left)

    for i, ds in enumerate(day_stats):
        r   = 8 + i
        alt = i % 2 == 1
        fl  = f_cell_la if alt else f_cell_l
        fc  = f_cell_a  if alt else f_cell
        ws1.write(r, 0, ds['day'],  fc)
        ws1.write(r, 1, ds['date'], fl)
        ws1.write(r, 2, ds['done'], fc)
        ws1.write(r, 3, ds['total'], fc)
        ws1.write(r, 4, ds['pct'],  pct_fmt(ds['pct']))

    daily_data_end = 8 + last_day - 1   # 0-indexed last data row

    # ── year summary table ────────────────────────────────────────
    yr_hdr_row = daily_data_end + 2
    ws1.set_row(yr_hdr_row, 18)
    ws1.merge_range(yr_hdr_row, 0, yr_hdr_row, 4, f'Year {year}: Monthly Overview', f_section)
    yr_col_hdrs = ['Month', 'Completed', 'Possible', 'Habits', 'Rate %']
    for ci, h in enumerate(yr_col_hdrs):
        ws1.write(yr_hdr_row + 1, ci, h, f_th if ci else f_th_left)

    yr_data_r0 = yr_hdr_row + 2
    for i, m in enumerate(year_data):
        r   = yr_data_r0 + i
        alt = i % 2 == 1
        star = ' ★' if m['month'] == month else ''
        ws1.write(r, 0, m['name'] + star, f_cell_la if alt else f_cell_l)
        ws1.write(r, 1, m['total_done'],     f_cell_a if alt else f_cell)
        ws1.write(r, 2, m['total_possible'], f_cell_a if alt else f_cell)
        ws1.write(r, 3, m['total_habits'],   f_cell_a if alt else f_cell)
        ws1.write(r, 4, m['overall_pct'],    pct_fmt(m['overall_pct']))

    yr_data_rN = yr_data_r0 + 11

    # ── CHARTS ───────────────────────────────────────────────────
    def base_chart_style(ch, title):
        ch.set_title({'name': title, 'name_font': {'size': 11, 'bold': True, 'color': CT}})
        ch.set_chartarea({'border': {'color': CB},         'fill': {'color': CW}})
        ch.set_plotarea({'border': {'color': CB, 'width': 0.5}, 'fill': {'color': CBG}})
        ch.set_legend({'none': True})

    # Chart 1: daily completion % (smooth line + area fill)
    c1 = wb.add_chart({'type': 'area', 'subtype': 'standard'})
    c1.add_series({
        'name': 'Completion %',
        'categories': ['Overview', 8, 1, daily_data_end, 1],
        'values':     ['Overview', 8, 4, daily_data_end, 4],
        'fill':   {'color': CA, 'transparency': 55},
        'line':   {'color': CA, 'width': 2.0},
    })
    base_chart_style(c1, f'Daily Completion Rate, {month_name} {year}')
    c1.set_x_axis({'name': 'Date', 'num_font': {'size': 8}, 'label_position': 'low'})
    c1.set_y_axis({'name': '%', 'min': 0, 'max': 100, 'num_font': {'size': 8},
                   'major_gridlines': {'visible': True, 'line': {'color': CB}}})
    c1.set_size({'width': 560, 'height': 290})
    ws1.insert_chart('G1', c1, {'x_offset': 5, 'y_offset': 5})

    # Chart 2: daily check-ins count (column)
    c2 = wb.add_chart({'type': 'column'})
    c2.add_series({
        'name': 'Check-ins',
        'categories': ['Overview', 8, 1, daily_data_end, 1],
        'values':     ['Overview', 8, 2, daily_data_end, 2],
        'fill':   {'color': CA},
        'border': {'color': CA2},
        'gap':    60,
    })
    base_chart_style(c2, f'Daily Check-ins, {month_name} {year}')
    c2.set_x_axis({'name': 'Date', 'num_font': {'size': 8}, 'label_position': 'low'})
    c2.set_y_axis({'name': 'Count', 'min': 0, 'num_font': {'size': 8},
                   'major_gridlines': {'visible': True, 'line': {'color': CB}}})
    c2.set_size({'width': 560, 'height': 290})
    ws1.insert_chart('G20', c2, {'x_offset': 5, 'y_offset': 5})

    # Chart 3: yearly overview (smooth line)
    c3 = wb.add_chart({'type': 'line'})
    c3.add_series({
        'name': f'Completion % by Month',
        'categories': ['Overview', yr_data_r0, 0, yr_data_rN, 0],
        'values':     ['Overview', yr_data_r0, 4, yr_data_rN, 4],
        'line':   {'color': CG, 'width': 2.5, 'smooth': True},
        'marker': {'type': 'circle', 'size': 5,
                   'fill': {'color': CG}, 'border': {'color': CG}},
    })
    base_chart_style(c3, f'Year {year}: Monthly Completion Rate')
    c3.set_x_axis({'num_font': {'size': 8},
                   'major_gridlines': {'visible': False}})
    c3.set_y_axis({'name': '%', 'min': 0, 'max': 100, 'num_font': {'size': 8},
                   'major_gridlines': {'visible': True, 'line': {'color': CB}}})
    c3.set_size({'width': 560, 'height': 290})
    ws1.insert_chart('G39', c3, {'x_offset': 5, 'y_offset': 5})

    # ═══════════════════════════════════════════════════════════════
    # SHEET 2: Habit Tracker Grid
    # ═══════════════════════════════════════════════════════════════
    ws2 = wb.add_worksheet('Habit Tracker')
    ws2.set_zoom(100)
    ws2.hide_gridlines(2)
    ws2.set_tab_color(CG)
    ws2.freeze_panes(3, 1)       # freeze habit col + first 2 header rows

    SUMCOLS = 2                  # Done + Rate columns after the days
    ws2.set_row(0, 34)
    ws2.set_row(1, 17)
    ws2.set_row(2, 14)
    ws2.set_column(0, 0, 28)     # habit name col
    for c in range(1, last_day + 1):
        ws2.set_column(c, c, 4.2)
    ws2.set_column(last_day + 1, last_day + SUMCOLS, 9)

    # title
    ws2.merge_range(0, 0, 0, last_day + SUMCOLS,
                    f'Habit Tracker: {month_name} {year}', f_title)

    # column headers: row 1 = day numbers, row 2 = day-of-week
    ws2.write(1, 0, 'Habit', f_th_left)
    ws2.write(2, 0, '',      f_dow)
    for d in range(1, last_day + 1):
        ds  = f'{year:04d}-{month:02d}-{d:02d}'
        dow = date(year, month, d).weekday()   # 0=Mon
        is_today   = ds == today_str
        is_weekend = dow >= 5
        if is_today:
            ws2.write(1, d, d,          f_day_today)
            ws2.write(2, d, DOW[dow],   f_dow_today)
        elif is_weekend:
            ws2.write(1, d, d,          f_day_wknd)
            ws2.write(2, d, DOW[dow],   f_dow_wknd)
        else:
            ws2.write(1, d, d,          f_day_hdr)
            ws2.write(2, d, DOW[dow],   f_dow)

    # summary column headers
    ws2.write(1, last_day + 1, 'Done',   f_th)
    ws2.write(1, last_day + 2, 'Rate %', f_th)
    ws2.write(2, last_day + 1, '',       f_dow)
    ws2.write(2, last_day + 2, '',       f_dow)

    # habit rows
    for ri, h in enumerate(habits):
        r   = ri + 3
        alt = ri % 2 == 1
        ws2.set_row(r, 18)
        ws2.write(r, 0, f'{h["emoji"]}  {h["name"]}',
                  f_hlabel_a if alt else f_hlabel)

        done_count = 0
        dfmt = habit_fmt[h['id']]
        for d in range(1, last_day + 1):
            ds        = f'{year:04d}-{month:02d}-{d:02d}'
            is_done   = (h['id'], ds) in completions
            is_future = ds > today_str
            is_today  = ds == today_str
            dow       = date(year, month, d).weekday()
            is_wknd   = dow >= 5

            if is_done:
                ws2.write(r, d, '✓', dfmt)
                done_count += 1
            elif is_future:
                ws2.write(r, d, '', f_empty_fut)
            elif is_today:
                ws2.write(r, d, '·', f_today_mt)
            else:
                ws2.write(r, d, '', f_empty_a if alt else f_empty)

        goal = h.get('goal', days_elapsed)
        rate = round((done_count / goal * 100) if goal else 0, 1)
        ws2.write(r, last_day + 1, done_count, f_ftnum)
        ws2.write(r, last_day + 2, f'{rate}%',  pct_fmt(rate))

    # footer rows: per-day totals
    ftr_done = n_habits + 3
    ftr_pct  = ftr_done + 1
    ws2.set_row(ftr_done, 16)
    ws2.set_row(ftr_pct,  16)
    ws2.write(ftr_done, 0, 'Done / Day',  f_ftlbl)
    ws2.write(ftr_pct,  0, 'Rate / Day',  f_ftlbl)
    ws2.write(ftr_done, last_day + 1, '', f_ftnum)
    ws2.write(ftr_done, last_day + 2, '', f_ftnum)
    ws2.write(ftr_pct,  last_day + 1, '', f_ftnum)
    ws2.write(ftr_pct,  last_day + 2, '', f_ftnum)
    for d in range(1, last_day + 1):
        ds = day_stats[d - 1]
        ws2.write(ftr_done, d, ds['done'],       f_ftnum)
        ws2.write(ftr_pct,  d, f'{ds["pct"]}%',  pct_fmt(ds['pct']))

    # ═══════════════════════════════════════════════════════════════
    # SHEET 3: Habit Analysis
    # ═══════════════════════════════════════════════════════════════
    ws3 = wb.add_worksheet('Habit Analysis')
    ws3.set_zoom(100)
    ws3.hide_gridlines(2)
    ws3.set_tab_color(CAM)
    ws3.set_column('A:A', 30)
    ws3.set_column('B:E', 14)
    ws3.set_column('F:F', 2)
    ws3.set_column('G:P', 9)
    ws3.set_row(0, 34)
    ws3.set_row(1, 18)

    ws3.merge_range('A1:E1', f'Habit Analysis: {month_name} {year}', f_title)
    for ci, hdr in enumerate(['Habit', 'Completed', 'Target Days', 'Missed', 'Completion %']):
        ws3.write(1, ci, hdr, f_th if ci else f_th_left)

    for i, h in enumerate(habit_stats):
        r   = 2 + i
        alt = i % 2 == 1
        ws3.set_row(r, 18)
        ws3.write(r, 0, f'{h["emoji"]}  {h["name"]}', f_cell_la if alt else f_cell_l)
        ws3.write(r, 1, h['done'],             f_cell_a if alt else f_cell)
        ws3.write(r, 2, h['goal'],             f_cell_a if alt else f_cell)
        ws3.write(r, 3, h['goal'] - h['done'], f_cell_a if alt else f_cell)
        ws3.write(r, 4, h['pct'],              pct_fmt(h['pct']))

    analysis_rN = 2 + n_habits - 1

    # summary totals row
    sum_row = analysis_rN + 1
    ws3.set_row(sum_row, 18)
    ws3.write(sum_row, 0, 'TOTAL / AVERAGE', f_ftlbl)
    ws3.write(sum_row, 1, total_done,         f_ftnum)
    ws3.write(sum_row, 2, total_possible,     f_ftnum)
    ws3.write(sum_row, 3, total_possible - total_done, f_ftnum)
    ws3.write(sum_row, 4, f'{overall_pct}%',  pct_fmt(overall_pct))

    # Chart 4: horizontal bar: habit completion rates
    c4 = wb.add_chart({'type': 'bar'})
    c4.add_series({
        'name': 'Completion %',
        'categories': ['Habit Analysis', 2, 0, analysis_rN, 0],
        'values':     ['Habit Analysis', 2, 4, analysis_rN, 4],
        'fill':   {'color': CA},
        'border': {'color': CA2},
        'gap':    50,
    })
    base_chart_style(c4, f'Habit Completion Rates, {month_name} {year}')
    c4.set_x_axis({'name': 'Completion %', 'min': 0, 'max': 100,
                   'num_font': {'size': 8},
                   'major_gridlines': {'visible': True, 'line': {'color': CB}}})
    c4.set_y_axis({'num_font': {'size': 8},
                   'major_gridlines': {'visible': False}})
    chart_h = max(240, n_habits * 32 + 100)
    c4.set_size({'width': 480, 'height': chart_h})
    ws3.insert_chart('G2', c4, {'x_offset': 5, 'y_offset': 5})

    # Chart 5: pie: done vs missed
    if total_possible > 0:
        pie_row = sum_row + 2
        ws3.write(pie_row,     0, 'Category',  f_th_left)
        ws3.write(pie_row,     1, 'Count',      f_th)
        ws3.write(pie_row + 1, 0, 'Completed',  f_cell_l)
        ws3.write(pie_row + 1, 1, total_done,   f_cell)
        ws3.write(pie_row + 2, 0, 'Missed',     f_cell_l)
        ws3.write(pie_row + 2, 1, total_possible - total_done, f_cell)

        c5 = wb.add_chart({'type': 'pie'})
        c5.add_series({
            'name': 'Distribution',
            'categories': ['Habit Analysis', pie_row + 1, 0, pie_row + 2, 0],
            'values':     ['Habit Analysis', pie_row + 1, 1, pie_row + 2, 1],
            'points': [
                {'fill': {'color': CG}},
                {'fill': {'color': CR}},
            ],
            'data_labels': {'percentage': True, 'category': True,
                            'font': {'size': 9, 'bold': True}},
        })
        base_chart_style(c5, f'Completed vs Missed, {month_name} {year}')
        c5.set_size({'width': 340, 'height': 280})
        anchor_col = 'G' if n_habits <= 8 else 'M'
        ws3.insert_chart(f'{anchor_col}{chart_h // 20 + 4}', c5, {'x_offset': 5, 'y_offset': 5})

    # ═══════════════════════════════════════════════════════════════
    # Finalize & stream
    # ═══════════════════════════════════════════════════════════════
    wb.close()
    output.seek(0)

    filename = f'HabitFlow-{year}-{month:02d}-{month_name}.xlsx'
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename,
    )


# ═══════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════

# Tried in order; the first usable one wins.
PORTS = [8050, 11050, 12050, 13050]


def _probe(port):
    """Is HabitFlow already serving on this port? -> 'ours' | 'busy' | 'free'."""
    import socket
    import json
    from urllib.request import urlopen
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        if s.connect_ex(('127.0.0.1', port)) != 0:
            return 'free'
    try:
        with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1.5) as resp:
            if json.loads(resp.read().decode('utf-8')).get('app') == APP_NAME:
                return 'ours'
    except Exception:
        pass
    return 'busy'


def _choose_port():
    """Reuse a running HabitFlow instead of starting a second copy."""
    for p in PORTS:
        state = _probe(p)
        if state == 'ours':
            return p, True
        if state == 'free':
            return p, False
    return PORTS[0], False


def _report_fatal(exc):
    """A windowed exe fails silently otherwise, so leave a trail the user can find."""
    import traceback
    detail = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as fh:
            fh.write(f'\n===== {datetime.now().isoformat(timespec="seconds")} =====\n{detail}')
    except OSError:
        pass
    try:
        sys.stderr.write(detail)
    except Exception:
        pass
    if sys.platform == 'win32' and getattr(sys, 'frozen', False):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                f'{APP_NAME} could not start.\n\n{exc}\n\n'
                f'Details were written to:\n{LOG_PATH}',
                f'{APP_NAME} {APP_VERSION}', 0x10)
        except Exception:
            pass


def main():
    bundled = getattr(sys, 'frozen', False)
    open_browser = os.environ.get('HABITFLOW_NO_BROWSER') != '1'

    init_db()
    port, already_running = _choose_port()
    url = f'http://127.0.0.1:{port}'

    if already_running:
        # A second double-click should raise the window you already have.
        print(f'{APP_NAME} is already running at {url}, opening it.')
        if open_browser:
            import webbrowser
            webbrowser.open(url)
        return

    print(f'{APP_NAME} {APP_VERSION} running at {url}')
    print(f'Your data: {DB_PATH}')
    if bundled:
        threading.Thread(target=_idle_watchdog, daemon=True).start()
    if open_browser:
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    # The Werkzeug debugger is a code-execution console, so it is opt-in.
    debug = not bundled and os.environ.get('HABITFLOW_DEBUG') == '1'
    app.run(host='127.0.0.1', port=port, debug=debug, use_reloader=debug)


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception as _exc:   # noqa: BLE001 - last line of defence
        _report_fatal(_exc)
        sys.exit(1)
