"""CV generation core: YAML data + a selection (profile) -> LaTeX -> PDF.

Used by app.py; no command-line interface.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    import yaml
except ImportError:
    print("PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)


def build_preamble(data):
    """Build LaTeX preamble, with optional font override from data."""
    font = data.get("template", {}).get("font", "TeX Gyre Termes")
    font_line = f"\\setmainfont{{{font}}}\n" if font else ""
    return r"""\documentclass[11pt,a4paper]{article}
\usepackage{fontspec}
\usepackage{geometry}
\usepackage{enumitem}
\usepackage{xcolor}
\usepackage{titlesec}

\geometry{
    left=0.6in, right=0.6in,
    top=0.6in, bottom=0.6in
}

\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlist[itemize]{nosep, leftmargin=12pt, topsep=2pt}

""" + font_line + r"""
\definecolor{mediumgray}{RGB}{102, 102, 102}

\titleformat{\section}
  {\large\bfseries\raggedright}
  {}{0em}{}[\titlerule]
\titlespacing*{\section}{0pt}{6pt}{4pt}

\newcommand{\subsectiontitle}[4]{%
    \textbf{#1} \hfill \textit{#2}\\
    \textit{#3} \hfill \textit{\color{mediumgray}#4}%
    \vspace{2pt}
}
\newcommand{\projecttitle}[2]{%
    \textbf{#1} \hfill \textit{#2}%
    \vspace{2pt}
}
"""


# ---- Periods: structured (start/end = "YYYY-MM" or "present") <-> display text ----

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_PRESENT_RE = re.compile(r"^(present|now|current|ongoing|至今|现在)$", re.I)


def _month_from_name(name):
    key = name.strip().lower()[:3]
    return MONTH_ABBR.index(key.capitalize()) + 1 if key.capitalize() in MONTH_ABBR else None


def _parse_side(text):
    """-> ('present',) | (month|None, year|None) | None if unrecognised."""
    t = text.strip().strip(".,")
    if _PRESENT_RE.match(t):
        return ("present",)
    m = re.match(r"^([A-Za-z]{3,9})\.?,?\s*(\d{4})?$", t)
    if m and _month_from_name(m.group(1)):
        return (_month_from_name(m.group(1)), int(m.group(2)) if m.group(2) else None)
    m = re.match(r"^(\d{4})\s*[/.-]\s*(\d{1,2})$", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return (int(m.group(2)), int(m.group(1)))
    m = re.match(r"^(\d{1,2})\s*[/.-]\s*(\d{4})$", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return (int(m.group(1)), int(m.group(2)))
    return None


def parse_period(text):
    """Best-effort parse of free text like 'Sept - Oct 2024' or 'Jun 2026 -- Present'.
    Returns (start, end) as ('YYYY-MM', 'YYYY-MM' | 'present'), or None."""
    if not text:
        return None
    parts = re.split(r"\s+(?:--|–|—|-|~|to|至)\s+", str(text).strip())
    if len(parts) != 2:
        parts = re.split(r"\s*(?:--|–|—|~|至)\s*", str(text).strip())
    if len(parts) != 2:
        return None
    left, right = _parse_side(parts[0]), _parse_side(parts[1])
    if not left or not right or left[0] == "present":
        return None
    lm, ly = left
    if right[0] == "present":
        rm, ry, end_present = None, None, True
    else:
        (rm, ry), end_present = right, False
    if ly is None:
        ly = ry                      # "Sept - Oct 2024": start shares the end year
    if lm is None or ly is None or (not end_present and (rm is None or ry is None)):
        return None
    start = f"{ly:04d}-{lm:02d}"
    return start, ("present" if end_present else f"{ry:04d}-{rm:02d}")


def _fmt_ym(ym):
    y, m = ym.split("-")
    return f"{MONTH_ABBR[int(m) - 1]} {y}"


def format_period(item):
    """Display text for an education/experience/project item.
    Prefers structured start/end; falls back to the legacy free-text 'period'."""
    start, end = item.get("start"), item.get("end")
    if start:
        try:
            left = _fmt_ym(str(start))
            right = "Present" if str(end).lower() == "present" else (_fmt_ym(str(end)) if end else "")
            return f"{left} -- {right}" if right else left
        except (ValueError, IndexError):
            pass
    legacy = str(item.get("period", "") or "").strip()
    parsed = parse_period(legacy)             # normalise old free text to the same format
    return format_period({"start": parsed[0], "end": parsed[1]}) if parsed else legacy


def migrate_periods(data):
    """In-memory: fill start/end from legacy 'period' text where it can be parsed."""
    items = list(data.get("education") or [])
    for sec in ("experiences", "projects"):
        items += list((data.get(sec) or {}).values())
    for it in items:
        if isinstance(it, dict) and not it.get("start"):
            parsed = parse_period(it.get("period"))
            if parsed:
                it["start"], it["end"] = parsed
    return data


def ensure_ids(data):
    """In-memory: every education entry needs an internal id (profiles reference items by it)."""
    used = {e.get("id") for e in (data.get("education") or []) if isinstance(e, dict) and e.get("id")}
    n = 1
    for e in (data.get("education") or []):
        if isinstance(e, dict) and not e.get("id"):
            while f"edu{n}" in used:
                n += 1
            e["id"] = f"edu{n}"
            used.add(e["id"])
    return data


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# LaTeX special characters that must be escaped in regular text.
# Order matters: backslash first, then braces, then active chars.
_LATEX_ESCAPE_MAP = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "_": r"\_",
    "%": r"\%",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_latex(text):
    """Escape special LaTeX characters in plain text."""
    if text is None:
        return ""
    s = str(text)
    for ch, repl in _LATEX_ESCAPE_MAP.items():
        s = s.replace(ch, repl)
    return s


def parse_entry(entry):
    """Parse 'id:variant' string or {id: variant} dict into (id, variant)."""
    if isinstance(entry, dict):
        eid = next(iter(entry))
        return eid, entry[eid]
    if ":" in str(entry):
        eid, variant = str(entry).split(":", 1)
        return eid.strip(), variant.strip()
    return str(entry).strip(), None


# ---- Section generators ----

def _itemize(items):
    """LaTeX errors on an empty list, so emit nothing when there are no items."""
    return ["\\begin{itemize}", *items, "\\end{itemize}"] if items else []


def gen_personal(data):
    p = data.get("personal") or {}
    name = str(p.get("name", "")).strip()
    parts = []
    for k in ("email", "phone", "location"):
        v = str(p.get(k, "")).strip()
        if v:
            parts.append(escape_latex(v))
    contact = " $\\cdot$ ".join(parts)
    return (
        "\\begin{center}\n"
        f"    {{\\Large\\bfseries {escape_latex(name)}}}\\\\\n"
        f"    \\vspace{{4pt}}\n"
        f"    {contact}\n"
        "\\end{center}"
    )


def gen_education(data, profile):
    if not profile.get("education"):
        return ""
    lines = ["\\section{Education}", "\\vspace{4pt}"]
    edu_map = {e.get("id"): e for e in (data.get("education") or [])}

    for entry in profile["education"]:
        eid, _ = parse_entry(entry)
        edu = edu_map.get(eid)
        if not edu:
            print(f"  [warn] education '{eid}' not found", file=sys.stderr)
            continue
        institution = str(edu.get("institution", "")).strip()
        period = format_period(edu)
        degree = str(edu.get("degree", "")).strip()
        cgpa = str(edu.get("cgpa", "")).strip()
        # \subsectiontitle takes 4 args: line 1 = institution / period, line 2 = degree / CGA
        cga = "\\textbf{CGA:} " + escape_latex(cgpa) if cgpa else ""
        lines.append(
            f"\\subsectiontitle{{{escape_latex(institution)}}}{{{escape_latex(period)}}}"
            f"{{{escape_latex(degree)}}}{{{cga}}}"
        )
        items = []
        courses = str(edu.get("courses", "")).strip()
        if courses:
            items.append(f"    \\item \\textbf{{Key Courses:}} {escape_latex(courses)}")
        awards = str(edu.get("awards", "")).strip()
        if awards:
            items.append(f"    \\item \\textbf{{Awards \\& Scholarships}} {escape_latex(awards)}")
        lines += _itemize(items)
    return "\n".join(lines)


def gen_experience(data, profile):
    if not profile.get("experiences"):
        return ""
    lines = ["\\section{Professional Experience}", "\\vspace{4pt}"]
    exp_map = data.get("experiences") or {}

    for entry in profile["experiences"]:
        eid, variant = parse_entry(entry)
        exp = exp_map.get(eid)
        if not exp:
            print(f"  [warn] experience '{eid}' not found", file=sys.stderr)
            continue
        variant = variant or "v1"
        variants = exp.get("variants") or {}
        bullets = variants.get(variant)
        if bullets is None:
            print(f"  [warn] variant '{variant}' not found for '{eid}'", file=sys.stderr)
            continue
        company = str(exp.get("company", "")).strip()
        period = format_period(exp)
        role = str(exp.get("role", "")).strip()
        location = str(exp.get("location", "")).strip()
        lines.append(
            f"\\subsectiontitle{{{escape_latex(company)}}}{{{escape_latex(period)}}}"
            f"{{{escape_latex(role)}}}{{{escape_latex(location)}}}"
        )
        lines += _itemize([
            f"    \\item {escape_latex(str(b))}" for b in (bullets or []) if str(b).strip()
        ])
    return "\n".join(lines)


def gen_projects(data, profile):
    if not profile.get("projects"):
        return ""
    lines = ["\\section{Projects \\& Competitions}", "\\vspace{4pt}"]
    proj_map = data.get("projects") or {}

    for entry in profile["projects"]:
        eid, variant = parse_entry(entry)
        proj = proj_map.get(eid)
        if not proj:
            print(f"  [warn] project '{eid}' not found", file=sys.stderr)
            continue
        variant = variant or "v1"
        variants = proj.get("variants") or {}
        bullets = variants.get(variant)
        if bullets is None:
            print(f"  [warn] variant '{variant}' not found for '{eid}'", file=sys.stderr)
            continue
        title = str(proj.get("title", "")).strip()
        period = format_period(proj)
        lines.append(f"\\projecttitle{{{escape_latex(title)}}}{{{escape_latex(period)}}}")
        lines += _itemize([
            f"    \\item {escape_latex(str(b))}" for b in (bullets or []) if str(b).strip()
        ])
    return "\n".join(lines)


def gen_skills(data, profile):
    if not profile.get("include_skills", True):
        return ""
    s = data.get("skills") or {}
    rows = []
    for key, val in s.items():
        val = ("" if val is None else str(val)).strip()
        if not val:
            continue
        label = str(key).strip().replace("_", " ").title()
        rows.append(f"\\textbf{{{escape_latex(label)}:}} {escape_latex(val)}")
    if not rows:
        return ""
    lines = ["\\section{Skills \\& Languages}"]
    lines.append(" \\\\\n".join(rows))
    return "\n".join(lines)


# ---- Main ----

def generate_tex(data, profile):
    parts = [
        build_preamble(data),
        "\\begin{document}\n",
        gen_personal(data),
        "",
        gen_education(data, profile),
        "",
        gen_experience(data, profile),
        "",
        gen_projects(data, profile),
        "",
        gen_skills(data, profile),
        "",
        "\\end{document}",
    ]
    return "\n".join(parts)


# ---- PDF compilation ----

_XELATEX_CACHE = {}


def _candidate_xelatex_paths():
    """Yield possible xelatex locations: env override, PATH, then common install dirs."""
    env = os.environ.get("CV_XELATEX")
    if env:
        yield env
    exe = "xelatex.exe" if os.name == "nt" else "xelatex"
    found = shutil.which("xelatex")
    if found:
        yield found
    home = os.path.expanduser("~")
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        for root in (r"C:\\Program Files\\MiKTeX", os.path.join(local, "Programs", "MiKTeX"),
                     r"C:\\MiKTeX", r"D:\\MiKTeX", r"D:\\Miketex"):
            yield os.path.join(root, "miktex", "bin", "x64", exe)
        for year in range(2030, 2021, -1):
            yield rf"C:\\texlive\\{year}\\bin\\windows\\{exe}"
            yield rf"C:\\texlive\\{year}\\bin\\win64\\{exe}"
    else:
        for d in ("/Library/TeX/texbin", "/usr/local/texlive/bin", "/opt/homebrew/bin",
                  "/usr/local/bin", "/usr/bin", os.path.join(home, "bin")):
            yield os.path.join(d, exe)


def find_xelatex():
    """Return absolute path of a working xelatex, or None."""
    if "path" in _XELATEX_CACHE:
        return _XELATEX_CACHE["path"]
    for p in _candidate_xelatex_paths():
        if p and os.path.isfile(p):
            _XELATEX_CACHE["path"] = p
            return p
    _XELATEX_CACHE["path"] = None
    return None


# Set by the desktop app so Tectonic keeps its downloaded package cache in the user data dir.
TECTONIC_CACHE_DIR = None


def _app_roots():
    """Folders where a bundled helper (e.g. tectonic) may live: next to the exe, PyInstaller dir, source dir."""
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(sys.executable))
        if getattr(sys, "_MEIPASS", None):
            roots.append(sys._MEIPASS)
    roots.append(os.path.dirname(os.path.abspath(__file__)))
    return roots


def find_tectonic():
    """Return path of a Tectonic binary (env override, bundled with the app, or on PATH), else None."""
    env = os.environ.get("CV_TECTONIC")
    if env and os.path.isfile(env):
        return env
    exe = "tectonic.exe" if os.name == "nt" else "tectonic"
    for root in _app_roots():
        for sub in ("tectonic", "vendor", os.path.join("vendor", "tectonic"), ""):
            p = os.path.join(root, sub, exe)
            if os.path.isfile(p):
                return p
    return shutil.which("tectonic")


def find_engine():
    """Pick a TeX engine: ('xelatex'|'tectonic', path) or None.
    A system xelatex wins (offline, fast); Tectonic is the zero-install fallback.
    Set CV_ENGINE=tectonic to force Tectonic."""
    prefer_tectonic = os.environ.get("CV_ENGINE", "").lower() == "tectonic"
    for name in (["tectonic", "xelatex"] if prefer_tectonic else ["xelatex", "tectonic"]):
        path = find_tectonic() if name == "tectonic" else find_xelatex()
        if path:
            return name, path
    return None


# ---- Running helper processes: hidden window + hard timeout that kills the whole process tree ----

class _Result:
    def __init__(self, returncode, stdout, stderr, timed_out=False):
        self.returncode, self.stdout, self.stderr, self.timed_out = returncode, stdout, stderr, timed_out


def _hidden_kwargs():
    """Popen kwargs: no console window on Windows (this is what made MiKTeX windows flash up);
    own process group on POSIX so a timeout can kill grandchildren too."""
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0                                   # SW_HIDE
        return {"startupinfo": si, "creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def _kill_tree(proc):
    try:
        if os.name == "nt":
            k = _hidden_kwargs()
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                           timeout=10, **k)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_hidden(cmd, cwd=None, env=None, timeout=60):
    """Run cmd without a visible window; on timeout kill it and all its children."""
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace", **_hidden_kwargs())
    try:
        out, err = proc.communicate(timeout=timeout)
        return _Result(proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        return _Result(-1, "", "", timed_out=True)


def _is_miktex(xelatex):
    """MiKTeX needs --disable-installer in headless runs; TeX Live rejects that flag."""
    key = ("miktex", xelatex)
    if key not in _XELATEX_CACHE:
        try:
            r = run_hidden([xelatex, "--version"], timeout=20)
            _XELATEX_CACHE[key] = "miktex" in ((r.stdout or "") + (r.stderr or "")).lower()
        except Exception:
            _XELATEX_CACHE[key] = False
    return _XELATEX_CACHE[key]


def parse_latex_log(log_text):
    """Turn a xelatex log into (code, human_message, line_no_or_None)."""
    m = re.search(r"Package fontspec Error: The font \"([^\"]+)\" cannot be found", log_text)
    if m:
        return ("missing_font",
                f"找不到字体 \"{m.group(1)}\"。请安装该字体"
                "(TeX Gyre Termes 属于 tex-gyre 包),或在 Data 里改用已安装的字体。", None)
    m = re.search(r"! LaTeX Error: File `([^']+)' not found", log_text)
    if m:
        return ("missing_package",
                f"缺少 LaTeX 宏包/文件 {m.group(1)}。请用 MiKTeX Console / tlmgr 安装。", None)
    m = re.search(r"^! (.+?)\n(?:.*\n){0,6}?l\.(\d+)", log_text, re.M)
    if m:
        return ("latex_error", f"LaTeX 报错:{m.group(1).strip()}(.tex 第 {m.group(2)} 行)",
                int(m.group(2)))
    m = re.search(r"^! (.+)$", log_text, re.M)
    if m:
        return ("latex_error", f"LaTeX 报错:{m.group(1).strip()}", None)
    return ("unknown", "编译失败,但日志中没有找到明确原因。", None)


def compile_pdf(tex_path, output_dir, timeout=60):
    """Compile .tex -> .pdf with xelatex.

    Builds in a private temp dir (so aux/log files never pollute output/ and a failed
    build never clobbers the last good PDF), then moves the PDF into output_dir.
    Skips work when the .tex content is unchanged since the last successful build.

    Returns a dict:
      ok: bool, pdf: path or None, pages: int or None, cached: bool,
      code / message / line / log_tail on failure.
    """
    tex_abs = os.path.abspath(tex_path)
    out_abs = os.path.abspath(output_dir)
    stem = os.path.splitext(os.path.basename(tex_abs))[0]
    pdf_path = os.path.join(out_abs, stem + ".pdf")
    stamp_path = os.path.join(out_abs, stem + ".buildinfo")

    with open(tex_abs, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()

    if os.path.exists(pdf_path) and os.path.exists(stamp_path):
        try:
            prev = json.load(open(stamp_path, encoding="utf-8"))
            if prev.get("sha256") == digest:
                return {"ok": True, "pdf": pdf_path, "pages": prev.get("pages"), "cached": True}
        except Exception:
            pass

    engine = find_engine()
    if not engine:
        return {"ok": False, "pdf": None, "pages": None, "cached": False,
                "code": "no_engine",
                "message": "没有找到 LaTeX 引擎。请安装 MiKTeX / TeX Live(xelatex),"
                           "或使用自带 Tectonic 的版本;也可设置环境变量 CV_XELATEX / CV_TECTONIC 指向可执行文件。"}
    kind, exe = engine
    if kind == "tectonic":
        timeout = max(timeout, 300)       # first run downloads packages

    with tempfile.TemporaryDirectory(prefix="cvbuild_") as work:
        work_tex = os.path.join(work, stem + ".tex")
        shutil.copyfile(tex_abs, work_tex)
        env = os.environ.copy()
        env["PATH"] = os.path.dirname(exe) + os.pathsep + env.get("PATH", "")
        if kind == "tectonic":
            cmd = [exe, "-X", "compile", "--keep-logs", "--outdir", work, work_tex]
            if TECTONIC_CACHE_DIR:
                os.makedirs(TECTONIC_CACHE_DIR, exist_ok=True)
                env["TECTONIC_CACHE_DIR"] = TECTONIC_CACHE_DIR
        else:
            cmd = [exe, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape"]
            if _is_miktex(exe):
                cmd.insert(1, "--disable-installer")
            cmd.append(work_tex)
        result = run_hidden(cmd, cwd=work, env=env, timeout=timeout)
        if result.timed_out:
            return {"ok": False, "pdf": None, "pages": None, "cached": False,
                    "code": "timeout",
                    "message": f"编译超过 {timeout} 秒,已强制中止。可能是 LaTeX 卡住了,"
                               "或 MiKTeX 在等待安装宏包;请稍后重试。"}

        work_pdf = os.path.join(work, stem + ".pdf")
        log_file = os.path.join(work, stem + ".log")
        process_out = (result.stdout or "") + (result.stderr or "")
        log_text = ""
        if os.path.exists(log_file):
            log_text = open(log_file, encoding="utf-8", errors="replace").read()
        log_text = log_text or process_out

        if result.returncode == 0 and os.path.exists(work_pdf) and os.path.getsize(work_pdf) > 1000:
            m = re.search(r"Output written on .*?\((\d+) pages?", log_text)
            pages = int(m.group(1)) if m else None
            os.makedirs(out_abs, exist_ok=True)
            shutil.move(work_pdf, pdf_path)
            with open(stamp_path, "w", encoding="utf-8") as f:
                json.dump({"sha256": digest, "pages": pages}, f)
            return {"ok": True, "pdf": pdf_path, "pages": pages, "cached": False}

        if kind == "tectonic" and not os.path.exists(log_file) and re.search(
                r"error sending request|connecting to|dns error|unsuccessful tunnel|timed out", process_out, re.I):
            return {"ok": False, "pdf": None, "pages": None, "cached": False,
                    "code": "tectonic_offline", "line": None,
                    "message": "Tectonic 首次使用需要联网下载 LaTeX 宏包,请联网后重试。",
                    "log_tail": process_out[-1500:]}
        code, message, line = parse_latex_log(log_text)
        return {"ok": False, "pdf": None, "pages": None, "cached": False,
                "code": code, "message": message, "line": line,
                "log_tail": log_text[-1500:]}
