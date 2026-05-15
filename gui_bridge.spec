# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['gui_bridge.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['yt_dlp', 'pyatv', 'zeroconf', 'aiohttp', 'win32gui', 'win32con', 'win32process', 'mss', 'PIL'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='gui_bridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
