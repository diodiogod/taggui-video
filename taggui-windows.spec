# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
import os

datas = [('clip-vit-base-patch32', 'clip-vit-base-patch32'),
         ('images/icon.ico', 'images')]
datas += collect_data_files('xformers')

# Optional bundled mpv runtime files (for experimental mpv backend).
if os.path.isdir('third_party/mpv'):
    for root, _, files in os.walk('third_party/mpv'):
        for filename in files:
            src = os.path.join(root, filename)
            dst = os.path.relpath(root, '.')
            datas.append((src, dst))

# Optional bundled vlc runtime files (for experimental vlc backend).
if os.path.isdir('third_party/vlc'):
    for root, _, files in os.walk('third_party/vlc'):
        for filename in files:
            src = os.path.join(root, filename)
            dst = os.path.relpath(root, '.')
            datas.append((src, dst))

hiddenimports = [
    'timm.models.layers',
    'xformers._C',
]

block_cipher = None


a = Analysis(
    ['taggui/run_gui.py'],
    pathex=['taggui'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    module_collection_mode={
        'xformers': 'pyz+py',
    },
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='taggui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['images/icon.ico'],
    contents_directory='_taggui',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='taggui',
)
