# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for HabitFlow.

Deliberately a **one-folder** build, not one-file. One-file exes unpack
themselves into %TEMP% at every launch, which is exactly the pattern Defender's
ML model flags as `Wacatac.B!ml`. One-folder starts faster, avoids that
heuristic, and is what the Inno Setup installer packages anyway.

Build:
    python packaging/make_icon.py
    python packaging/make_version.py
    pyinstaller packaging/habitflow.spec
    # -> dist/HabitFlow/HabitFlow.exe
"""
import os

ROOT = os.path.abspath(os.getcwd())
ICON = os.path.join(ROOT, 'assets', 'habitflow.ico')
VERSION_FILE = os.path.join(ROOT, 'packaging', 'version_info.txt')

# Hard failure, not a silent fallback: an exe with a blank default icon looks
# untrustworthy to anyone who downloads it, and a missing icon is invisible in
# build logs. assets/habitflow.ico is committed; regenerate with make_icon.py.
if not os.path.exists(ICON):
    raise SystemExit(
        f'Missing {ICON}\nRun: python packaging/make_icon.py')
if not os.path.exists(VERSION_FILE):
    raise SystemExit(
        f'Missing {VERSION_FILE}\nRun: python packaging/make_version.py')

a = Analysis(
    [os.path.join(ROOT, 'app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'templates'), 'templates'),
        (os.path.join(ROOT, 'static'), 'static'),
    ],
    hiddenimports=[
        'flask',
        'jinja2',
        'werkzeug',
        'werkzeug.routing',
        'werkzeug.serving',
        'xlsxwriter',
        'xlsxwriter.workbook',
        'xlsxwriter.worksheet',
        'sqlite3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # HabitFlow needs Flask, xlsxwriter and the stdlib — nothing else. Excluding
    # the rest keeps the download small and stops a developer's fat Anaconda /
    # Jupyter environment from leaking into the build.
    excludes=[
        'tkinter', 'test', 'unittest', 'pydoc_data',
        'numpy', 'pandas', 'scipy', 'matplotlib', 'PIL', 'Pillow',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'shiboken6',
        'IPython', 'jupyter', 'notebook', 'nbformat', 'nbconvert',
        'jedi', 'zmq', 'tornado', 'psutil', 'black', 'yapf', 'pytest',
        'setuptools', 'pip', 'wheel',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,           # one-folder: binaries live in COLLECT
    name='HabitFlow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                       # UPX packing is another AV false-positive magnet
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
    version=VERSION_FILE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='HabitFlow',
)
