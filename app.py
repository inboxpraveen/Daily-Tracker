from flask import Flask, jsonify, request, render_template
import sqlite3
import os
import sys
from datetime import date, datetime
import calendar


def _resource(rel):
    """Resolve a bundled-file path for both dev and PyInstaller one-file builds."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def _data_dir():
    """Return a writable directory for user data that survives app updates."""
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


@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')


def _month_summary(conn, year, month):
    """Aggregate counts for one month (same rules as get_stats)."""
    habits = conn.execute('SELECT * FROM habits WHERE active=1').fetchall()
    total_habits = len(habits)
    last_day = calendar.monthrange(year, month)[1]
    today = date.today()
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
        'SELECT COUNT(*) FROM completions c JOIN habits h ON c.habit_id=h.id '
        'WHERE h.active=1 AND completion_date BETWEEN ? AND ?',
        (start, end)
    ).fetchone()[0]
    overall_pct = round((total_done / total_possible * 100) if total_possible > 0 else 0, 1)
    return {
        'total_habits': total_habits,
        'last_day': last_day,
        'days_elapsed': days_elapsed,
        'total_done': total_done,
        'total_possible': total_possible,
        'overall_pct': overall_pct,
    }


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

@app.route('/api/export/<int:year>/<int:month>')
def export_excel(year, month):
    """Generate a fully-formatted, multi-sheet Excel workbook for the given month."""
    import io
    try:
        import xlsxwriter
    except ImportError:
        return jsonify({'error': 'xlsxwriter not installed. Run: pip install xlsxwriter'}), 500

    from flask import send_file

    MONTH_NAMES = ['', 'January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']
    DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

    conn       = get_db()
    habits     = [dict(h) for h in conn.execute('SELECT * FROM habits WHERE active=1 ORDER BY id').fetchall()]
    n_habits   = len(habits)
    last_day   = calendar.monthrange(year, month)[1]
    today_d    = date.today()
    month_name = MONTH_NAMES[month]
    today_str  = today_d.strftime('%Y-%m-%d')

    if today_d.year == year and today_d.month == month:
        days_elapsed = today_d.day
    elif date(year, month, 1) > today_d:
        days_elapsed = 0
    else:
        days_elapsed = last_day

    start = f'{year:04d}-{month:02d}-01'
    end   = f'{year:04d}-{month:02d}-{last_day:02d}'

    # ── raw completions set ───────────────────────────────────────
    completions = {
        (r['habit_id'], r['completion_date'])
        for r in conn.execute(
            'SELECT habit_id, completion_date FROM completions '
            'WHERE completion_date BETWEEN ? AND ?', (start, end)
        ).fetchall()
    }

    # ── per-day stats ─────────────────────────────────────────────
    day_stats = []
    for d in range(1, last_day + 1):
        ds   = f'{year:04d}-{month:02d}-{d:02d}'
        done = conn.execute(
            'SELECT COUNT(*) FROM completions c JOIN habits h ON c.habit_id=h.id '
            'WHERE h.active=1 AND completion_date=?', (ds,)
        ).fetchone()[0]
        pct = round((done / n_habits * 100) if n_habits else 0, 1)
        day_stats.append({'day': d, 'date': ds, 'done': done, 'pct': pct})

    # ── per-habit stats ───────────────────────────────────────────
    habit_stats = []
    for h in habits:
        done = conn.execute(
            'SELECT COUNT(*) FROM completions WHERE habit_id=? AND completion_date BETWEEN ? AND ?',
            (h['id'], start, end)
        ).fetchone()[0]
        pct = round((done / days_elapsed * 100) if days_elapsed else 0, 1)
        habit_stats.append({**h, 'done': done, 'goal': days_elapsed, 'pct': pct})

    total_possible = n_habits * days_elapsed
    total_done     = sum(h['done'] for h in habit_stats)
    overall_pct    = round((total_done / total_possible * 100) if total_possible else 0, 1)

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
    # SHEET 1 — Overview
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
    ws1.merge_range('A7:E7', f'Daily Breakdown  —  {month_name} {year}', f_section)
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
        ws1.write(r, 3, n_habits,   fc)
        ws1.write(r, 4, ds['pct'],  pct_fmt(ds['pct']))

    daily_data_end = 8 + last_day - 1   # 0-indexed last data row

    # ── year summary table ────────────────────────────────────────
    yr_hdr_row = daily_data_end + 2
    ws1.set_row(yr_hdr_row, 18)
    ws1.merge_range(yr_hdr_row, 0, yr_hdr_row, 4, f'Year {year}  —  Monthly Overview', f_section)
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

    # Chart 1 – daily completion % (smooth line + area fill)
    c1 = wb.add_chart({'type': 'area', 'subtype': 'standard'})
    c1.add_series({
        'name': 'Completion %',
        'categories': ['Overview', 8, 1, daily_data_end, 1],
        'values':     ['Overview', 8, 4, daily_data_end, 4],
        'fill':   {'color': CA, 'transparency': 55},
        'line':   {'color': CA, 'width': 2.0},
    })
    base_chart_style(c1, f'Daily Completion Rate — {month_name} {year}')
    c1.set_x_axis({'name': 'Date', 'num_font': {'size': 8}, 'label_position': 'low'})
    c1.set_y_axis({'name': '%', 'min': 0, 'max': 100, 'num_font': {'size': 8},
                   'major_gridlines': {'visible': True, 'line': {'color': CB}}})
    c1.set_size({'width': 560, 'height': 290})
    ws1.insert_chart('G1', c1, {'x_offset': 5, 'y_offset': 5})

    # Chart 2 – daily check-ins count (column)
    c2 = wb.add_chart({'type': 'column'})
    c2.add_series({
        'name': 'Check-ins',
        'categories': ['Overview', 8, 1, daily_data_end, 1],
        'values':     ['Overview', 8, 2, daily_data_end, 2],
        'fill':   {'color': CA},
        'border': {'color': CA2},
        'gap':    60,
    })
    base_chart_style(c2, f'Daily Check-ins — {month_name} {year}')
    c2.set_x_axis({'name': 'Date', 'num_font': {'size': 8}, 'label_position': 'low'})
    c2.set_y_axis({'name': 'Count', 'min': 0, 'num_font': {'size': 8},
                   'major_gridlines': {'visible': True, 'line': {'color': CB}}})
    c2.set_size({'width': 560, 'height': 290})
    ws1.insert_chart('G20', c2, {'x_offset': 5, 'y_offset': 5})

    # Chart 3 – yearly overview (smooth line)
    c3 = wb.add_chart({'type': 'line'})
    c3.add_series({
        'name': f'Completion % by Month',
        'categories': ['Overview', yr_data_r0, 0, yr_data_rN, 0],
        'values':     ['Overview', yr_data_r0, 4, yr_data_rN, 4],
        'line':   {'color': CG, 'width': 2.5, 'smooth': True},
        'marker': {'type': 'circle', 'size': 5,
                   'fill': {'color': CG}, 'border': {'color': CG}},
    })
    base_chart_style(c3, f'Year {year}  —  Monthly Completion Rate')
    c3.set_x_axis({'num_font': {'size': 8},
                   'major_gridlines': {'visible': False}})
    c3.set_y_axis({'name': '%', 'min': 0, 'max': 100, 'num_font': {'size': 8},
                   'major_gridlines': {'visible': True, 'line': {'color': CB}}})
    c3.set_size({'width': 560, 'height': 290})
    ws1.insert_chart('G39', c3, {'x_offset': 5, 'y_offset': 5})

    # ═══════════════════════════════════════════════════════════════
    # SHEET 2 — Habit Tracker Grid
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
                    f'Habit Tracker  —  {month_name} {year}', f_title)

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

        rate = round((done_count / days_elapsed * 100) if days_elapsed else 0, 1)
        ws2.write(r, last_day + 1, done_count, f_ftnum)
        ws2.write(r, last_day + 2, f'{rate}%',  pct_fmt(rate))

    # footer rows — per-day totals
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
    # SHEET 3 — Habit Analysis
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

    ws3.merge_range('A1:E1', f'Habit Analysis  —  {month_name} {year}', f_title)
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

    # Chart 4 – horizontal bar: habit completion rates
    c4 = wb.add_chart({'type': 'bar'})
    c4.add_series({
        'name': 'Completion %',
        'categories': ['Habit Analysis', 2, 0, analysis_rN, 0],
        'values':     ['Habit Analysis', 2, 4, analysis_rN, 4],
        'fill':   {'color': CA},
        'border': {'color': CA2},
        'gap':    50,
    })
    base_chart_style(c4, f'Habit Completion Rates — {month_name} {year}')
    c4.set_x_axis({'name': 'Completion %', 'min': 0, 'max': 100,
                   'num_font': {'size': 8},
                   'major_gridlines': {'visible': True, 'line': {'color': CB}}})
    c4.set_y_axis({'num_font': {'size': 8},
                   'major_gridlines': {'visible': False}})
    chart_h = max(240, n_habits * 32 + 100)
    c4.set_size({'width': 480, 'height': chart_h})
    ws3.insert_chart('G2', c4, {'x_offset': 5, 'y_offset': 5})

    # Chart 5 – pie: done vs missed
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
        base_chart_style(c5, f'Completed vs Missed — {month_name} {year}')
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


if __name__ == '__main__':
    # ── Port configuration ────────────────────────────────────────────────────
    # Tried in order; the first free one wins.  If all are taken, change these.
    PORTS = [8050, 11050, 12050, 13050]
    # ─────────────────────────────────────────────────────────────────────────

    import socket

    def _free_port(candidates):
        for p in candidates:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('127.0.0.1', p)) != 0:
                    return p
        return candidates[0]

    init_db()
    port = _free_port(PORTS)
    _bundled = getattr(sys, 'frozen', False)
    if _bundled:
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()
    app.run(debug=not _bundled, port=port, use_reloader=not _bundled)
