# -*- mode: python ; coding: utf-8 -*-
# Optional PyInstaller spec for hub-gui.
# Build example: pyinstaller build.spec --noconfirm

from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=[],
    datas=[('web', 'web')],
    hiddenimports=collect_submodules('hub_gui'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='hub-gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='hub-gui',
)
