#!/usr/bin/env python3
"""Flask Web UI for Modular CV Generator.

Run:
  python app.py
Then open http://127.0.0.1:5000

Features:
  - Visual checkbox + variant selection
  - Live .tex preview
  - Download .tex / compile PDF
  - Save & load profile YAMLs
"""

import json
import os
import re
import sys
import shutil
import socket
import tempfile
import threading
import traceback
import webbrowser
from datetime import datetime

from flask import (
    Flask, Response, render_template, request, jsonify, send_file, abort
)
import yaml
from werkzeug.exceptions import HTTPException

import generate_cv
from generate_cv import load_yaml, generate_tex, compile_pdf, migrate_periods, ensure_ids

BASE = os.path.dirname(os.path.abspath(__file__))

# 资源目录(templates/static 等只读)：frozen 时由 PyInstaller 提供(sys._MEIPASS)。
RES_BASE = sys._MEIPASS if getattr(sys, "frozen", False) else BASE


def resolve_data_dir():
    """Where cv_data.yaml, profiles, output/ and backups/ live.

    Order: $CV_BUILDER_DATA  ->  source folder (when run as a script)  ->
    folder next to the exe if it already has cv_data.yaml (portable mode)  ->
    the per-user app-data folder (%APPDATA%\\CV Builder, ~/Library/Application Support, ~/.local/share).
    """
    env = os.environ.get("CV_BUILDER_DATA")
    if env:
        return os.path.abspath(env)
    if not getattr(sys, "frozen", False):
        return BASE
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if os.path.exists(os.path.join(exe_dir, "cv_data.yaml")):
        return exe_dir
    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        root = os.path.expanduser("~/Library/Application Support")
    else:
        root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(root, "CV Builder")


DATA_DIR = resolve_data_dir()
DATA_PATH = os.path.join(DATA_DIR, "cv_data.yaml")
OUTPUT_DIR = os.path.join(DATA_DIR, "output")
TEMPLATES_DIR = os.path.join(RES_BASE, "templates")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")


def _attach_log_if_windowed():
    """A windowed PyInstaller exe has no stdout/stderr; prints would raise. Log to app.log instead."""
    if getattr(sys, "frozen", False) and (sys.stdout is None or sys.stderr is None):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            log = open(os.path.join(DATA_DIR, "app.log"), "a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stdout or log
            sys.stderr = sys.stderr or log
        except Exception:
            pass


_attach_log_if_windowed()


def _fatal(msg):
    """Show a startup failure instead of dying silently (the exe has no console)."""
    print(msg, file=sys.stderr)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"{msg}\n\nLog: {os.path.join(DATA_DIR, 'app.log')}", "CV Builder", 0x10)
        except Exception:
            pass


def ensure_first_run():
    """Create the data dir and a starter cv_data.yaml; seed Tectonic's package cache if one is bundled."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DATA_PATH):
        example = os.path.join(RES_BASE, "cv_data.example.yaml")
        if os.path.exists(example):
            shutil.copyfile(example, DATA_PATH)
    cache = os.path.join(DATA_DIR, "tectonic-cache")
    generate_cv.TECTONIC_CACHE_DIR = cache
    bundled = os.path.join(RES_BASE, "tectonic_cache")
    if os.path.isdir(bundled) and not os.path.isdir(cache):
        try:
            shutil.copytree(bundled, cache)
        except Exception:
            pass


STATIC_DIR = os.path.join(RES_BASE, "static")

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.json.sort_keys = False          # keep YAML order in JSON responses (Flask sorts keys by default)
app.jinja_env.policies["json.dumps_kwargs"] = {"sort_keys": False}   # ...and in the {{ data | tojson }} filter

# Serialise compiles: the live preview can fire overlapping requests.
_compile_lock = threading.Lock()
_preview_gen = 0            # "latest request wins": stale queued previews are skipped, not compiled
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024      # refuse absurdly large request bodies

PREVIEW_TIMEOUT = 60        # seconds; live preview
EXPORT_TIMEOUT = 120        # seconds; Download PDF / Save As


@app.errorhandler(Exception)
def handle_exc(e):
    if isinstance(e, HTTPException):          # 404 etc. are normal responses, not crashes
        if request.path.startswith("/api/"):
            return jsonify({"error": e.description}), e.code
        return e
    tb = traceback.format_exc()
    print(tb, file=sys.stderr, flush=True)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        log_path = os.path.join(DATA_DIR, "error.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} {request.path} ===\n{tb}\n")
    except Exception:
        pass
    msg = f"{type(e).__name__}: {e}"
    if request.path.startswith("/api/"):
        return jsonify({"error": msg, "trace": tb[-2000:]}), 500
    from markupsafe import escape as _esc
    return f"<h3>出错了</h3><pre>{_esc(msg)}</pre>", 500


def list_profiles():
    return sorted(
        f for f in os.listdir(DATA_DIR)
        if f.startswith("cv_profile_") and f.endswith(".yaml")
    )


def profile_to_yaml(profile):
    """Convert profile dict (from frontend) to YAML string."""
    out = {}
    if profile.get("education"):
        out["education"] = profile["education"]
    if profile.get("experiences"):
        out["experiences"] = profile["experiences"]
    if profile.get("projects"):
        out["projects"] = profile["projects"]
    if profile.get("include_skills") is not None:
        out["include_skills"] = bool(profile.get("include_skills", True))
    return yaml.safe_dump(out, allow_unicode=True, sort_keys=False)


def _backup_and_write(fpath, data):
    """Backup cv_data.yaml then write data as YAML."""
    if os.path.exists(fpath):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.splitext(os.path.basename(fpath))[0]
        bak = os.path.join(BACKUP_DIR, f"{base}.{ts}.bak")
        shutil.copy2(fpath, bak)
        print(f"[save_data] backup: {bak}")
    # Preserve existing structure: only replace experiences + projects
    try:
        existing = load_yaml(fpath) if os.path.exists(fpath) else {}
    except Exception:
        existing = {}
    # Keep non-data keys intact
    for key, val in data.items():
        if key in ("experiences", "projects", "education", "skills", "personal", "template"):
            existing[key] = val
    with open(fpath, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            existing, f, allow_unicode=True, sort_keys=False,
            default_flow_style=False, width=120
        )


@app.route("/favicon.ico")
def favicon():
    return send_file(os.path.join(STATIC_DIR, "app.png"), mimetype="image/png")


@app.route("/")
def index():
    ensure_first_run()
    data = ensure_ids(migrate_periods(load_yaml(DATA_PATH)))   # legacy periods -> start/end; every item gets an id
    return render_template(
        "index.html",
        data=data,
        profiles=list_profiles(),
        settings=load_settings(),
    )


SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
DEFAULT_SETTINGS = {"auto_refresh": True}


def load_settings():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    except Exception:
        return dict(DEFAULT_SETTINGS)


@app.route("/api/settings", methods=["POST"])
def save_settings():
    body = request.get_json(force=True) or {}
    cur = load_settings()
    if "auto_refresh" in body:
        cur["auto_refresh"] = bool(body["auto_refresh"])
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(cur, f)
    return jsonify(cur)


@app.route("/api/preview", methods=["POST"])
def preview():
    profile = request.get_json(force=True)
    data = load_yaml(DATA_PATH)
    tex = generate_tex(data, profile)
    return tex, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/preview_pdf", methods=["POST"])
def preview_pdf():
    """Compile the current selection and return the PDF bytes (live preview).

    Success: 200 application/pdf, with X-Pages / X-Cached headers.
    Failure: 422 JSON {error, code, line}; the client keeps showing the last good PDF.
    """
    global _preview_gen
    profile = request.get_json(force=True)
    _preview_gen += 1
    mine = _preview_gen
    data = load_yaml(DATA_PATH)
    tex = generate_tex(data, profile)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tex_path = os.path.join(OUTPUT_DIR, "_preview.tex")
    with _compile_lock:
        if mine != _preview_gen:                      # a newer request arrived while we waited
            return jsonify({"superseded": True}), 409
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex)
        res = compile_pdf(tex_path, OUTPUT_DIR, timeout=PREVIEW_TIMEOUT)
        if res["ok"]:
            with open(res["pdf"], "rb") as f:
                pdf_bytes = f.read()
    if not res["ok"]:
        return jsonify({"error": res["message"], "code": res["code"],
                        "line": res.get("line")}), 422
    return Response(pdf_bytes, mimetype="application/pdf", headers={
        "X-Pages": str(res["pages"] or ""),
        "X-Cached": "1" if res["cached"] else "0",
        "Cache-Control": "no-store",
    })


def _write_tex(profile, name):
    data = load_yaml(DATA_PATH)
    tex = generate_tex(data, profile)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tex_path = os.path.join(OUTPUT_DIR, f"{name}.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex)
    return tex_path, tex


@app.route("/api/generate", methods=["POST"])
def generate():
    body = request.get_json(force=True)
    profile = body.get("profile", {})
    name = body.get("name", "cv").replace("/", "_").replace("\\", "_")
    data = load_yaml(DATA_PATH)
    tex = generate_tex(data, profile)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tex_path = os.path.join(OUTPUT_DIR, f"{name}.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex)
    return jsonify({"path": tex_path, "tex": tex})


def _safe_name(name):
    """Restrict output file names to a safe basename (no path tricks)."""
    name = re.sub(r"[^\w\-. \u4e00-\u9fff]+", "_", str(name or "cv")).strip(" .")
    return name or "cv"


@app.route("/api/compile", methods=["POST"])
def compile():
    body = request.get_json(force=True)
    profile = body.get("profile", {})
    name = _safe_name(body.get("name", "cv"))
    data = load_yaml(DATA_PATH)
    tex = generate_tex(data, profile)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tex_path = os.path.join(OUTPUT_DIR, f"{name}.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex)

    with _compile_lock:
        res = compile_pdf(tex_path, OUTPUT_DIR, timeout=EXPORT_TIMEOUT)
    if res["ok"]:
        return jsonify({"ok": True, "name": name, "pages": res["pages"], "cached": res["cached"]})
    print(res.get("log_tail", ""), file=sys.stderr)
    return jsonify({
        "ok": False,
        "error": res["message"],
        "code": res["code"],
        "line": res.get("line"),
        "log_tail": res.get("log_tail", "")[-800:],
    }), 500


@app.route("/api/download_pdf")
def download_pdf():
    name = _safe_name(request.args.get("name", "cv"))
    pdf_path = os.path.join(OUTPUT_DIR, f"{name}.pdf")
    if not os.path.exists(pdf_path):
        abort(404)
    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=f"{name}.pdf",
        mimetype="application/pdf",
    )


@app.route("/api/save_profile", methods=["POST"])
def save_profile():
    body = request.get_json(force=True)
    name = body.get("name", "profile").replace("/", "_").replace("\\", "_")
    profile = body.get("profile", {})
    fname = f"cv_profile_{name}.yaml"
    fpath = os.path.join(DATA_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(profile_to_yaml(profile))
    return jsonify({"file": fname, "profiles": list_profiles()})


@app.route("/api/load_profile/<name>")
def load_profile(name):
    name = name.replace("/", "_").replace("\\", "_")
    if not name.startswith("cv_profile_"):
        name = f"cv_profile_{name}"
    if not name.endswith(".yaml"):
        name += ".yaml"
    fpath = os.path.join(DATA_DIR, name)
    if not os.path.exists(fpath):
        abort(404)
    profile = load_yaml(fpath)
    return jsonify(profile)

@app.route("/api/delete_profile/<name>", methods=["DELETE"])
def delete_profile(name):
    """Delete a saved cv_profile_*.yaml file."""
    name = name.replace("/", "_").replace("\\", "_")
    if not name.startswith("cv_profile_"):
        name = f"cv_profile_{name}"
    if not name.endswith(".yaml"):
        name += ".yaml"
    fpath = os.path.join(DATA_DIR, name)
    if not os.path.exists(fpath):
        abort(404)
    os.remove(fpath)
    return jsonify({"ok": True, "profiles": list_profiles()})


def _in_order(section, order):
    """Rebuild a dict so its keys follow `order` (ids the user arranged in the Data tab)."""
    if not isinstance(section, dict) or not order:
        return section
    out = {k: section[k] for k in order if k in section}
    out.update({k: v for k, v in section.items() if k not in out})
    return out


@app.route("/api/save_data", methods=["POST"])
def save_data():
    """Save experiences + projects + education + skills + personal back to cv_data.yaml."""
    body = request.get_json(force=True)
    order = body.get("order") or {}
    new_data = {
        "experiences": _in_order(body.get("experiences", {}), order.get("experiences")),
        "projects": _in_order(body.get("projects", {}), order.get("projects")),
        "education": body.get("education", []),
        "skills": body.get("skills", {}),
    }
    if "personal" in body:
        allowed = {"name", "email", "phone", "location"}
        new_data["personal"] = {
            k: str(v).strip() for k, v in body.get("personal", {}).items() if k in allowed
        }
    _backup_and_write(DATA_PATH, new_data)
    return jsonify({"ok": True})


@app.route("/api/shutdown", methods=["POST"])
def shutdown():
    """Terminate the app process (used by the desktop-app 'Quit' button)."""
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return jsonify({"ok": True})


def _find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class DesktopApi:
    """Exposed to the page as window.pywebview.api — native Save dialogs for exports."""

    def __init__(self):
        self._window = None

    def _ask_path(self, filename, label, pattern):
        import webview
        kind = webview.FileDialog.SAVE if hasattr(webview, "FileDialog") else webview.SAVE_DIALOG
        res = self._window.create_file_dialog(
            kind, directory=os.path.expanduser("~/Documents"), save_filename=filename,
            file_types=(f"{label} ({pattern})",))
        if isinstance(res, (list, tuple)):
            res = res[0] if res else None
        return res or None

    def save_pdf(self, profile, name="cv"):
        name = _safe_name(name)
        tex_path, _ = _write_tex(profile, name)
        with _compile_lock:
            res = compile_pdf(tex_path, OUTPUT_DIR, timeout=EXPORT_TIMEOUT)
        if not res["ok"]:
            return {"ok": False, "error": res["message"]}
        dest = self._ask_path(f"{name}.pdf", "PDF", "*.pdf")
        if not dest:
            return {"ok": False, "cancelled": True}
        shutil.copyfile(res["pdf"], dest)
        return {"ok": True, "path": dest}

    def save_tex(self, profile, name="cv"):
        name = _safe_name(name)
        _, tex = _write_tex(profile, name)
        dest = self._ask_path(f"{name}.tex", "LaTeX", "*.tex")
        if not dest:
            return {"ok": False, "cancelled": True}
        with open(dest, "w", encoding="utf-8") as f:
            f.write(tex)
        return {"ok": True, "path": dest}

    def set_titlebar(self, dark, bg, fg):
        """Windows 10/11: make the native title bar follow the app theme (dark mode + colours on Win11)."""
        if os.name != "nt":
            return False
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = 0
            try:
                hwnd = int(self._window.native.Handle.ToInt64())
            except Exception:
                pass
            if not hwnd:
                hwnd = ctypes.windll.user32.FindWindowW(None, "CV Builder")
            if not hwnd:
                return False
            dwm = ctypes.windll.dwmapi

            def put(attr, value):
                v = ctypes.c_int(value)
                dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))

            def colorref(hex_):                      # "#rrggbb" -> 0x00BBGGRR
                h = hex_.lstrip("#")
                return int(h[4:6] + h[2:4] + h[0:2], 16)

            put(19, 1 if dark else 0)               # immersive dark mode (older Win10 builds)
            put(20, 1 if dark else 0)               # immersive dark mode (Win10 20H1+ / Win11)
            put(35, colorref(bg))                   # caption colour   (Win11 only; ignored elsewhere)
            put(36, colorref(fg))                   # caption text colour
            put(34, colorref(bg))                   # window border colour
            return True
        except Exception:
            return False

    def quit(self):
        threading.Timer(0.2, lambda: os._exit(0)).start()


def _run_server(port):
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


def main():
    ensure_first_run()
    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=_run_server, args=(port,), daemon=True).start()
    if os.environ.get("CV_BUILDER_BROWSER") != "1":
        try:
            import webview
        except Exception as e:                      # pywebview / WebView2 not available
            print(f"[window] pywebview unavailable ({e}); opening in the browser instead", file=sys.stderr)
        else:
            api = DesktopApi()
            api._window = webview.create_window(
                "CV Builder", url, js_api=api, width=1380, height=900, min_size=(1000, 640))
            try:
                webview.start()                      # blocks until the window is closed
                os._exit(0)
            except Exception as e:                  # e.g. WebView2 runtime missing
                print(f"[window] could not open a native window ({e}); using the browser", file=sys.stderr)
    webbrowser.open(url)
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _fatal("CV Builder failed to start:\n" + traceback.format_exc()[-1200:])
        raise
