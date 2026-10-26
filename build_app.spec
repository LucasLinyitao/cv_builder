# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the CV Builder desktop app (native window via pywebview).
# Build:  build_windows.bat            (or: pyinstaller build_app.spec --noconfirm --clean)
# Output: dist/CV Builder/CV Builder.exe   (one-folder app: fast start-up, no temp unpacking)
#
# Optional extras picked up automatically when present (build_windows.bat --with-tectonic creates them):
#   vendor/tectonic/tectonic.exe          zero-install LaTeX engine
#   build_cache/tectonic_cache/           pre-downloaded Tectonic packages, so the first PDF works offline

import os
from PyInstaller.utils.hooks import collect_all

datas = [
    ("templates", "templates"),
    ("static", "static"),
    ("cv_data.example.yaml", "."),
]
binaries = []
hiddenimports = ["yaml", "flask", "generate_cv"]

# pywebview + its Windows backend (WebView2 via pythonnet)
for pkg in ("webview", "clr_loader", "pythonnet"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

if os.path.isdir("vendor/tectonic"):
    datas.append(("vendor/tectonic", "tectonic"))
if os.path.isdir("build_cache/tectonic_cache"):
    datas.append(("build_cache/tectonic_cache", "tectonic_cache"))

a = Analysis(
    ["app.py"],
    pathex=[os.getcwd()],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CV Builder",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/app.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CV Builder",
)
