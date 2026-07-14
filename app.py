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

import os
import re
import shutil
import tempfile
from datetime import datetime

from flask import (
    Flask, render_template, request, jsonify, send_file, abort
)
import yaml

import generate_cv
from generate_cv import load_yaml, generate_tex, compile_pdf, build_preamble

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE, "cv_data.yaml")
OUTPUT_DIR = os.path.join(BASE, "output")
TEMPLATES_DIR = os.path.join(BASE, "templates")
BACKUP_DIR = os.path.join(BASE, "backups")

app = Flask(__name__, template_folder=TEMPLATES_DIR)


def list_profiles():
    return sorted(
        f for f in os.listdir(BASE)
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


def _slugify(text, kind="exp"):
    """Generate a slug from company/title text."""
    if not text:
        kind_map = {"exp": "experience", "proj": "project"}
        return f"new_{kind_map.get(kind, 'item')}"
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9_\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:30] or kind


def _clean_profile_refs(kind, item_id, base_dir):
    """Remove references to item_id from all cv_profile_*.yaml."""
    import glob as _glob
    for fpath in _glob.glob(os.path.join(base_dir, "cv_profile_*.yaml")):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        pattern = rf"{item_id}:[^\s,\]\"]*"
        new_content = re.sub(pattern, "", content)
        # clean up dangling commas / empty lists
        new_content = re.sub(r",\s*\n", "\n", new_content)
        new_content = re.sub(r"\[\s*\]", "[]", new_content)
        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)


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


@app.route("/")
def index():
    data = load_yaml(DATA_PATH)
    return render_template(
        "index.html",
        data=data,
        profiles=list_profiles(),
    )


@app.route("/api/preview", methods=["POST"])
def preview():
    profile = request.get_json(force=True)
    data = load_yaml(DATA_PATH)
    tex = generate_tex(data, profile)
    return tex, 200, {"Content-Type": "text/plain; charset=utf-8"}


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


@app.route("/api/compile", methods=["POST"])
def compile():
    body = request.get_json(force=True)
    profile = body.get("profile", {})
    name = body.get("name", "cv").replace("/", "_").replace("\\", "_")
    data = load_yaml(DATA_PATH)
    tex = generate_tex(data, profile)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tex_path = os.path.join(OUTPUT_DIR, f"{name}.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex)

    ok, xerr = compile_pdf(tex_path, OUTPUT_DIR)
    if ok:
        return jsonify({"ok": True, "name": name})
    xelatex = generate_cv._find_xelatex()
    return jsonify({
        "error": "PDF compilation failed",
        "detail": {
            "xelatex": xelatex,
            "tex_exists": os.path.exists(tex_path),
            "xelatex_error": (xerr or "unknown")[:400],
        },
    }), 500


@app.route("/api/download_pdf")
def download_pdf():
    name = request.args.get("name", "cv").replace("/", "_").replace("\\", "_")
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
    fpath = os.path.join(BASE, fname)
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
    fpath = os.path.join(BASE, name)
    if not os.path.exists(fpath):
        abort(404)
    profile = load_yaml(fpath)
    return jsonify(profile)


@app.route("/api/save_data", methods=["POST"])
def save_data():
    """Save experiences + projects + education + skills + personal back to cv_data.yaml."""
    body = request.get_json(force=True)
    new_data = {
        "experiences": body.get("experiences", {}),
        "projects": body.get("projects", {}),
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


@app.route("/api/experience/<kind>", methods=["POST"])
def create_experience(kind):
    """Create a blank experience/project with auto-generated id."""
    body = request.get_json(force=True)
    data = load_yaml(DATA_PATH)
    section = data.get(kind, {})
    base_name = (body.get("company") or body.get("title") or "").strip()
    slug = _slugify(base_name, "exp" if kind == "experiences" else "proj")
    # Ensure unique id
    orig = slug
    n = 1
    while slug in section:
        slug = f"{orig}_{n}"
        n += 1
    if kind == "experiences":
        section[slug] = {
            "company": body.get("company", ""),
            "role": body.get("role", ""),
            "location": body.get("location", ""),
            "period": body.get("period", ""),
            "variants": {"v1": []},
        }
    elif kind == "projects":
        section[slug] = {
            "title": body.get("title", ""),
            "period": body.get("period", ""),
            "variants": {"v1": []},
        }
    else:
        abort(400, "kind must be 'experiences' or 'projects'")
    data[kind] = section
    _backup_and_write(DATA_PATH, data)
    return jsonify({"id": slug, "data": section[slug]})


@app.route("/api/experience/<kind>/<id>", methods=["DELETE"])
def delete_experience(kind, id):
    """Delete an experience/project and clean profile references."""
    data = load_yaml(DATA_PATH)
    section = data.get(kind, {})
    if id not in section:
        abort(404)
    del section[id]
    data[kind] = section
    _backup_and_write(DATA_PATH, data)
    _clean_profile_refs(kind, id, BASE)
    cleaned = len(
        [f for f in os.listdir(BASE)
         if f.startswith("cv_profile_") and f.endswith(".yaml")]
    )
    return jsonify({"ok": True, "profiles": list_profiles()})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
