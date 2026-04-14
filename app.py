from flask import Flask, jsonify, request, render_template
import sqlite3
import os
from datetime import date, datetime
import calendar

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), 'habits.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/habits', methods=['GET'])
def get_habits():
    conn = get_db()
    habits = conn.execute('SELECT * FROM habits WHERE active=1 ORDER BY id').fetchall()
    conn.close()
    return jsonify([dict(h) for h in habits])

@app.route('/api/habits', methods=['POST'])
def add_habit():
    data = request.json
    name = data.get('name', '').strip()
    emoji = data.get('emoji', '✅')
    color = data.get('color', '#22c55e')
    if not name:
        return jsonify({'error': 'Name required'}), 400
    conn = get_db()
    cur = conn.execute('INSERT INTO habits (name, emoji, color) VALUES (?,?,?)', (name, emoji, color))
    conn.commit()
    habit_id = cur.lastrowid
    habit = conn.execute('SELECT * FROM habits WHERE id=?', (habit_id,)).fetchone()
    conn.close()
    return jsonify(dict(habit)), 201

@app.route('/api/habits/<int:habit_id>', methods=['DELETE'])
def delete_habit(habit_id):
    conn = get_db()
    conn.execute('UPDATE habits SET active=0 WHERE id=?', (habit_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/habits/<int:habit_id>', methods=['PUT'])
def update_habit(habit_id):
    data = request.json
    conn = get_db()
    conn.execute('UPDATE habits SET name=?, emoji=?, color=? WHERE id=?',
                 (data['name'], data['emoji'], data['color'], habit_id))
    conn.commit()
    habit = conn.execute('SELECT * FROM habits WHERE id=?', (habit_id,)).fetchone()
    conn.close()
    return jsonify(dict(habit))

@app.route('/api/completions/<int:year>/<int:month>', methods=['GET'])
def get_completions(year, month):
    conn = get_db()
    # Get all completions for this month
    start = f'{year:04d}-{month:02d}-01'
    last_day = calendar.monthrange(year, month)[1]
    end = f'{year:04d}-{month:02d}-{last_day:02d}'
    rows = conn.execute(
        'SELECT habit_id, completion_date FROM completions WHERE completion_date BETWEEN ? AND ?',
        (start, end)
    ).fetchall()
    conn.close()
    result = {}
    for row in rows:
        key = f"{row['habit_id']}_{row['completion_date']}"
        result[key] = True
    return jsonify(result)

@app.route('/api/completions/toggle', methods=['POST'])
def toggle_completion():
    data = request.json
    habit_id = data['habit_id']
    comp_date = data['date']  # YYYY-MM-DD
    conn = get_db()
    existing = conn.execute(
        'SELECT id FROM completions WHERE habit_id=? AND completion_date=?',
        (habit_id, comp_date)
    ).fetchone()
    if existing:
        conn.execute('DELETE FROM completions WHERE habit_id=? AND completion_date=?', (habit_id, comp_date))
        completed = False
    else:
        conn.execute('INSERT INTO completions (habit_id, completion_date) VALUES (?,?)', (habit_id, comp_date))
        completed = True
    conn.commit()
    conn.close()
    return jsonify({'completed': completed, 'habit_id': habit_id, 'date': comp_date})

@app.route('/api/stats/<int:year>/<int:month>', methods=['GET'])
def get_stats(year, month):
    conn = get_db()
    habits = conn.execute('SELECT * FROM habits WHERE active=1').fetchall()
    total_habits = len(habits)
    last_day = calendar.monthrange(year, month)[1]
    today = date.today()
    
    # Days elapsed in month (up to today)
    if today.year == year and today.month == month:
        days_elapsed = today.day
    elif date(year, month, 1) > today:
        days_elapsed = 0
    else:
        days_elapsed = last_day

    start = f'{year:04d}-{month:02d}-01'
    end = f'{year:04d}-{month:02d}-{last_day:02d}'
    
    total_possible = total_habits * days_elapsed
    total_done = conn.execute(
        'SELECT COUNT(*) FROM completions c JOIN habits h ON c.habit_id=h.id WHERE h.active=1 AND completion_date BETWEEN ? AND ?',
        (start, end)
    ).fetchone()[0]
    
    overall_pct = round((total_done / total_possible * 100) if total_possible > 0 else 0, 1)
    
    # Per-habit stats
    habit_stats = []
    for h in habits:
        done = conn.execute(
            'SELECT COUNT(*) FROM completions WHERE habit_id=? AND completion_date BETWEEN ? AND ?',
            (h['id'], start, end)
        ).fetchone()[0]
        habit_stats.append({
            'id': h['id'],
            'name': h['name'],
            'emoji': h['emoji'],
            'color': h['color'],
            'goal': days_elapsed,
            'actual': done,
            'pct': round((done / days_elapsed * 100) if days_elapsed > 0 else 0, 1)
        })
    
    # Per-day stats
    day_stats = []
    for d in range(1, last_day + 1):
        day_str = f'{year:04d}-{month:02d}-{d:02d}'
        done = conn.execute(
            'SELECT COUNT(*) FROM completions c JOIN habits h ON c.habit_id=h.id WHERE h.active=1 AND completion_date=?',
            (day_str,)
        ).fetchone()[0]
        day_stats.append({'day': d, 'done': done, 'total': total_habits,
                          'pct': round((done / total_habits * 100) if total_habits > 0 else 0)})
    
    conn.close()
    return jsonify({
        'overall_pct': overall_pct,
        'total_done': total_done,
        'total_possible': total_possible,
        'days_elapsed': days_elapsed,
        'habit_stats': habit_stats,
        'day_stats': day_stats
    })

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5050)
