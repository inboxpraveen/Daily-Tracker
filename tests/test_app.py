"""Smoke tests for the HabitFlow API.

Every test runs against a throwaway database via HABITFLOW_DATA_DIR, so your
real %APPDATA%\\HabitFlow\\habits.db is never touched.
"""
import os
import sys
import sqlite3
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TODAY = date.today()


def iso(offset=0):
    return (TODAY + timedelta(days=offset)).isoformat()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('HABITFLOW_DATA_DIR', str(tmp_path))
    for mod in list(sys.modules):
        if mod == 'app':
            del sys.modules[mod]
    import app as app_module
    app_module.DB_PATH = str(tmp_path / 'habits.db')
    app_module.init_db()
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        c.app_module = app_module
        yield c


def add_habit(client, name='Test Habit', created_at=None):
    payload = {'name': name, 'emoji': '🎯', 'color': '#123abc'}
    if created_at:
        payload['created_at'] = created_at
    res = client.post('/api/habits', json=payload)
    assert res.status_code == 201
    return res.get_json()


# ── basics ────────────────────────────────────────────────────────────────

def test_health(client):
    body = client.get('/api/health').get_json()
    assert body['app'] == 'HabitFlow'


def test_pages_render(client):
    assert client.get('/').status_code == 200
    assert client.get('/dashboard').status_code == 200


def test_seeds_default_habits(client):
    assert len(client.get('/api/habits').get_json()) == 8


def test_pages_load_nothing_from_a_third_party(client):
    """The README promises nothing leaves the machine, so no page may pull a font,
    script or stylesheet from another host."""
    import re
    for path in ('/', '/dashboard'):
        html = client.get(path).get_data(as_text=True)
        external = re.findall(r'(?:src|href)\s*=\s*["\']((?:https?:)?//[^"\']+)', html)
        assert external == [], f'{path} loads external resources: {external}'


def test_bundled_fonts_and_chart_library_are_served(client):
    css = client.get('/static/vendor/fonts/fonts.css')
    assert css.status_code == 200
    for name in ('DMSans-latin.woff2', 'DMMono-400-latin.woff2', 'DMMono-500-latin.woff2'):
        assert name in css.get_data(as_text=True)
        assert client.get(f'/static/vendor/fonts/{name}').status_code == 200
    assert client.get('/static/vendor/chart.umd.min.js').status_code == 200


def test_foreign_host_is_rejected(client):
    res = client.get('/api/habits', headers={'Host': 'evil.example.com'})
    assert res.status_code == 403


# ── validation ────────────────────────────────────────────────────────────

def test_add_habit_requires_a_name(client):
    assert client.post('/api/habits', json={'name': '   '}).status_code == 400


def test_add_habit_rejects_junk_colour(client):
    assert add_habit(client, 'Colour test')['color'] == '#123abc'
    res = client.post('/api/habits', json={'name': 'Bad colour', 'color': 'javascript:x'})
    assert res.get_json()['color'] == '#22c55e'


def test_update_missing_habit_is_404_not_500(client):
    assert client.put('/api/habits/9999', json={'name': 'x'}).status_code == 404


def test_update_with_empty_body_keeps_values(client):
    h = add_habit(client, 'Keep me')
    updated = client.put(f"/api/habits/{h['id']}", json={}).get_json()
    assert updated['name'] == 'Keep me'


def test_toggle_rejects_bad_input(client):
    h = add_habit(client)
    assert client.post('/api/completions/toggle', json={}).status_code == 400
    assert client.post('/api/completions/toggle',
                       json={'habit_id': h['id'], 'date': 'yesterday'}).status_code == 400
    assert client.post('/api/completions/toggle',
                       json={'habit_id': h['id'], 'date': iso(1)}).status_code == 400
    assert client.post('/api/completions/toggle',
                       json={'habit_id': 9999, 'date': iso()}).status_code == 404


def test_toggle_is_idempotent_round_trip(client):
    h = add_habit(client)
    body = {'habit_id': h['id'], 'date': iso()}
    assert client.post('/api/completions/toggle', json=body).get_json()['completed'] is True
    assert client.post('/api/completions/toggle', json=body).get_json()['completed'] is False


def test_cannot_tick_a_day_before_the_habit_existed(client):
    h = add_habit(client, 'New habit', created_at=iso(-2))
    res = client.post('/api/completions/toggle', json={'habit_id': h['id'], 'date': iso(-10)})
    assert res.status_code == 400
    assert "wasn't being tracked" in res.get_json()['error']


# ── the denominator fix ───────────────────────────────────────────────────

def test_goal_counts_only_days_the_habit_existed(client):
    """A habit added today must not show up as 0-out-of-a-whole-month."""
    for h in client.get('/api/habits').get_json():
        client.delete(f"/api/habits/{h['id']}")
    fresh = add_habit(client, 'Added today', created_at=iso())
    stats = client.get(f'/api/stats/{TODAY.year}/{TODAY.month}').get_json()
    mine = [h for h in stats['habit_stats'] if h['id'] == fresh['id']][0]
    assert mine['goal'] == 1, 'goal should be one day, not the whole month'

    client.post('/api/completions/toggle', json={'habit_id': fresh['id'], 'date': iso()})
    stats = client.get(f'/api/stats/{TODAY.year}/{TODAY.month}').get_json()
    mine = [h for h in stats['habit_stats'] if h['id'] == fresh['id']][0]
    assert mine['pct'] == 100.0


def test_deleting_a_habit_does_not_rewrite_history(client):
    """Removing a habit today must leave last month's percentage alone."""
    prev = TODAY.replace(day=1) - timedelta(days=1)
    start_of_prev = prev.replace(day=1).isoformat()
    h = add_habit(client, 'Historic', created_at=start_of_prev)

    conn = sqlite3.connect(client.app_module.DB_PATH)
    conn.execute('INSERT INTO completions (habit_id, completion_date) VALUES (?,?)',
                 (h['id'], start_of_prev))
    conn.commit()
    conn.close()

    before = client.get(f'/api/stats/{prev.year}/{prev.month}').get_json()
    client.delete(f"/api/habits/{h['id']}")
    after = client.get(f'/api/stats/{prev.year}/{prev.month}').get_json()
    assert before['overall_pct'] == after['overall_pct']
    assert before['total_possible'] == after['total_possible']


def test_percentage_never_exceeds_one_hundred(client):
    h = add_habit(client, 'Bounded', created_at=iso(-3))
    for d in range(-3, 1):
        client.post('/api/completions/toggle', json={'habit_id': h['id'], 'date': iso(d)})
    stats = client.get(f'/api/stats/{TODAY.year}/{TODAY.month}').get_json()
    for row in stats['habit_stats']:
        assert row['pct'] <= 100.0


def test_month_habits_include_ones_removed_later(client):
    h = add_habit(client, 'Was tracked', created_at=iso(-1))
    client.delete(f"/api/habits/{h['id']}")
    live = client.get('/api/habits').get_json()
    assert h['id'] not in [x['id'] for x in live]
    historic = client.get(f'/api/habits?year={TODAY.year}&month={TODAY.month}').get_json()
    assert h['id'] in [x['id'] for x in historic]


def test_restore_brings_a_habit_back(client):
    h = add_habit(client, 'Comeback')
    client.delete(f"/api/habits/{h['id']}")
    assert client.post(f"/api/habits/{h['id']}/restore").status_code == 200
    assert h['id'] in [x['id'] for x in client.get('/api/habits').get_json()]


# ── insights ──────────────────────────────────────────────────────────────

def test_insights_computes_a_streak(client):
    for h in client.get('/api/habits').get_json():
        client.delete(f"/api/habits/{h['id']}")
    h = add_habit(client, 'Streaky', created_at=iso(-4))
    for d in range(-4, 1):
        client.post('/api/completions/toggle', json={'habit_id': h['id'], 'date': iso(d)})

    body = client.get(f'/api/insights/{TODAY.year}/{TODAY.month}').get_json()
    mine = [s for s in body['streaks'] if s['id'] == h['id']][0]
    assert mine['current'] == 5
    assert mine['best'] == 5
    assert mine['at_risk'] is False
    assert body['today']['done'] == 1 and body['today']['total'] == 1
    assert body['highlights']


def test_streak_survives_an_unfinished_today_but_is_flagged(client):
    for h in client.get('/api/habits').get_json():
        client.delete(f"/api/habits/{h['id']}")
    h = add_habit(client, 'At risk', created_at=iso(-3))
    for d in range(-3, 0):
        client.post('/api/completions/toggle', json={'habit_id': h['id'], 'date': iso(d)})

    mine = client.get(f'/api/insights/{TODAY.year}/{TODAY.month}').get_json()['streaks'][0]
    assert mine['current'] == 3
    assert mine['at_risk'] is True
    assert mine['done_today'] is False


def test_insights_on_an_empty_month_still_answers(client):
    body = client.get('/api/insights/2019/1').get_json()
    assert body['highlights']
    assert body['overall_pct'] == 0


def test_insights_rejects_a_silly_month(client):
    assert client.get('/api/insights/2025/13').status_code == 400


# ── backup / restore ──────────────────────────────────────────────────────

def test_backup_then_restore_round_trips(client):
    h = add_habit(client, 'Round trip', created_at=iso(-1))
    client.post('/api/completions/toggle', json={'habit_id': h['id'], 'date': iso(-1)})
    dump = client.get('/api/backup').get_json()
    assert dump['habits'] and dump['completions']

    client.delete(f"/api/habits/{h['id']}")
    res = client.post('/api/restore', json=dump)
    assert res.status_code == 200
    assert 'Round trip' in [x['name'] for x in client.get('/api/habits').get_json()]


def test_restore_rejects_a_random_file(client):
    assert client.post('/api/restore', json={'hello': 'world'}).status_code == 400


# ── export ────────────────────────────────────────────────────────────────

def test_excel_export_builds(client):
    h = add_habit(client, 'Exported')
    client.post('/api/completions/toggle', json={'habit_id': h['id'], 'date': iso()})
    res = client.get(f'/api/export/{TODAY.year}/{TODAY.month}')
    assert res.status_code == 200
    assert res.data[:2] == b'PK'  # xlsx is a zip


def test_excel_export_handles_an_empty_month(client):
    assert client.get('/api/export/2019/2').status_code == 200


def test_year_stats_returns_twelve_months(client):
    body = client.get(f'/api/stats/year/{TODAY.year}').get_json()
    assert len(body['months']) == 12


# ── error handling ────────────────────────────────────────────────────────

def test_unknown_page_is_a_plain_404(client):
    assert client.get('/nope').status_code == 404


def test_wrong_method_is_405_not_500(client):
    assert client.post('/').status_code == 405


def test_unknown_api_path_returns_json_404(client):
    res = client.get('/api/nope')
    assert res.status_code == 404
    assert res.is_json


# ── migration from a pre-1.1 database ─────────────────────────────────────

def test_migration_backfills_deactivated_at_from_last_use(tmp_path, monkeypatch):
    """A habit deleted under the old schema keeps the history it earned."""
    monkeypatch.setenv('HABITFLOW_DATA_DIR', str(tmp_path))
    db = tmp_path / 'habits.db'

    # Build a database exactly as version 1.0 left it: no deactivated_at column.
    conn = sqlite3.connect(db)
    conn.executescript('''
        CREATE TABLE habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, emoji TEXT, color TEXT,
            created_at TEXT, active INTEGER DEFAULT 1
        );
        CREATE TABLE completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL, completion_date TEXT NOT NULL,
            UNIQUE(habit_id, completion_date)
        );
    ''')
    conn.execute("INSERT INTO habits (id, name, emoji, color, created_at, active) "
                 "VALUES (1,'Old habit','x','#22c55e',?,0)", (iso(-30),))
    for d in (-30, -20, -10):
        conn.execute('INSERT INTO completions (habit_id, completion_date) VALUES (1,?)', (iso(d),))
    conn.commit()
    conn.close()

    sys.modules.pop('app', None)
    import app as app_module
    app_module.DB_PATH = str(db)
    app_module.init_db()

    conn = sqlite3.connect(db)
    row = conn.execute('SELECT created_at, deactivated_at FROM habits WHERE id=1').fetchone()
    conn.close()
    assert row[0] == iso(-30)
    assert row[1] == iso(-10), 'should stop counting after the last day it was used'
