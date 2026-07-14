#!/usr/bin/env python3
"""Modular CV Generator — YAML data + profile selection -> LaTeX (.tex)

Usage:
  python generate_cv.py --profile cv_profile_full.yaml --out output/cv.tex --pdf
  python generate_cv.py --profile cv_profile_ib.yaml --out output/ib.tex --pdf
  python generate_cv.py --list              # show all available experiences & variants
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys

try:
    import yaml
except ImportError:
    print("PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)


def build_preamble(data):
    """Build LaTeX preamble, with optional font override from data."""
    font = data.get("template", {}).get("font", "TeX Gyre Termes")
    if font.lower() == "tex gyre termes":
        fonts_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "fonts"
        ).replace("\\", "/")
        if os.path.isdir(fonts_dir):
            font_line = (
                "\\setmainfont{TeX Gyre Termes}[\n"
                f"  Path = {fonts_dir}/,\n"
                "  Extension = .otf,\n"
                "  UprightFont = texgyretermes-regular,\n"
                "  BoldFont = texgyretermes-bold,\n"
                "  ItalicFont = texgyretermes-italic,\n"
                "  BoldItalicFont = texgyretermes-bolditalic,\n"
                "]\n"
            )
        else:
            font_line = f"\\setmainfont{{{font}}}\n"
    else:
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

def gen_personal(data):
    p = data["personal"]
    return (
        "\\begin{center}\n"
        f"    {{\\Large\\bfseries {escape_latex(p['name'])}}}\\\\\n"
        f"    \\vspace{{4pt}}\n"
        f"    {escape_latex(p['email'])} $\\cdot$ {escape_latex(p['phone'])} $\\cdot$ {escape_latex(p['location'])}\n"
        "\\end{center}"
    )


def gen_education(data, profile):
    if not profile.get("education"):
        return ""
    lines = ["\\section{Education}", "\\vspace{4pt}"]
    edu_map = {e["id"]: e for e in data.get("education", [])}

    for entry in profile["education"]:
        eid, _ = parse_entry(entry)
        edu = edu_map.get(eid)
        if not edu:
            print(f"  [warn] education '{eid}' not found", file=sys.stderr)
            continue
        lines.append(
            f"\\subsectiontitle{{{escape_latex(edu['institution'])}}}{{{escape_latex(edu['period'])}}}"
            f"{{{escape_latex(edu['degree'])}}}\\textbf{{CGA:}} {escape_latex(edu['cgpa'])}"
        )
        lines.append("\\begin{itemize}")
        if edu.get("courses"):
            lines.append(f"    \\item \\textbf{{Key Courses:}} {escape_latex(edu['courses'])}")
        if edu.get("awards"):
            lines.append(f"    \\item \\textbf{{Awards \\& Scholarships}} {escape_latex(edu['awards'])}")
        lines.append("\\end{itemize}")
    return "\n".join(lines)


def gen_experience(data, profile):
    if not profile.get("experiences"):
        return ""
    lines = ["\\section{Professional Experience}", "\\vspace{4pt}"]
    exp_map = data.get("experiences", {})

    for entry in profile["experiences"]:
        eid, variant = parse_entry(entry)
        exp = exp_map.get(eid)
        if not exp:
            print(f"  [warn] experience '{eid}' not found", file=sys.stderr)
            continue
        variant = variant or "v1"
        bullets = exp["variants"].get(variant)
        if bullets is None:
            print(f"  [warn] variant '{variant}' not found for '{eid}'", file=sys.stderr)
            continue
        lines.append(
            f"\\subsectiontitle{{{escape_latex(exp['company'])}}}{{{escape_latex(exp['period'])}}}"
            f"{{{escape_latex(exp['role'])}}}{{{escape_latex(exp['location'])}}}"
        )
        lines.append("\\begin{itemize}")
        for b in bullets:
            lines.append(f"    \\item {escape_latex(b)}")
        lines.append("\\end{itemize}")
    return "\n".join(lines)


def gen_projects(data, profile):
    if not profile.get("projects"):
        return ""
    lines = ["\\section{Projects \\& Competitions}", "\\vspace{4pt}"]
    proj_map = data.get("projects", {})

    for entry in profile["projects"]:
        eid, variant = parse_entry(entry)
        proj = proj_map.get(eid)
        if not proj:
            print(f"  [warn] project '{eid}' not found", file=sys.stderr)
            continue
        variant = variant or "v1"
        bullets = proj["variants"].get(variant)
        if bullets is None:
            print(f"  [warn] variant '{variant}' not found for '{eid}'", file=sys.stderr)
            continue
        lines.append(f"\\projecttitle{{{escape_latex(proj['title'])}}}{{{escape_latex(proj['period'])}}}")
        lines.append("\\begin{itemize}")
        for b in bullets:
            lines.append(f"    \\item {escape_latex(b)}")
        lines.append("\\end{itemize}")
    return "\n".join(lines)


def gen_skills(data, profile):
    if not profile.get("include_skills", True):
        return ""
    s = data["skills"]
    lines = ["\\section{Skills \\& Languages}"]
    lines.append(f"\\textbf{{Programming:}} {escape_latex(s['programming'])} \\\\")
    lines.append(f"\\textbf{{Tools:}} {escape_latex(s['tools'])} \\\\")
    lines.append(f"\\textbf{{Languages:}} {escape_latex(s['languages'])} \\\\")
    lines.append(f"\\textbf{{Interests:}} {escape_latex(s['interests'])}")
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


def _find_xelatex():
    """Return the xelatex executable from PATH.

    Users configure their own TeX distribution (MiKTeX / TeX Live) and
    ensure `xelatex` is on PATH. Nothing is hard-coded here.
    """
    return shutil.which("xelatex") or "xelatex"


def compile_pdf(tex_path, output_dir):
    """Compile .tex to .pdf using xelatex. Returns (True, None) or (False, error_msg)."""
    xelatex = _find_xelatex()
    tex_abs = os.path.abspath(tex_path)
    out_abs = os.path.abspath(output_dir)
    pdf_path = os.path.join(out_abs, os.path.splitext(os.path.basename(tex_path))[0] + ".pdf")
    cmd = [xelatex]
    # --disable-installer is MiKTeX-specific; TeX Live rejects it as an
    # unknown option. Only add it when a MiKTeX binary was detected.
    if "miktex" in xelatex.lower():
        cmd.append("--disable-installer")
    cmd += [
        "-interaction=nonstopmode",
        "-output-directory=" + out_abs,
        tex_abs,
    ]
    # Use full inherited environment (same as CLI mode)
    env = os.environ.copy()
    miktex_bin = os.path.dirname(xelatex)
    if miktex_bin not in env.get("PATH", ""):
        env["PATH"] = miktex_bin + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=output_dir,
        stdin=subprocess.DEVNULL, env=env,
    )
    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000:
        return True, None
    # Build diagnostic error
    err = (result.stderr[-500:] or "").strip()
    if not err:
        err = (result.stdout[-500:] or "").strip()
    # Check log file as well
    log_path = os.path.splitext(tex_abs)[0] + ".log"
    log_tail = ""
    if os.path.exists(log_path):
        log_tail = open(log_path, "r", errors="replace").read()[-500:].strip()
    print(f"xelatex rc={result.returncode} cmd={' '.join(cmd)}", file=sys.stderr)
    if log_tail:
        print("log tail:", log_tail[:500], file=sys.stderr)
    return False, err or f"rc={result.returncode}" + (f" log={log_tail[:200]}" if log_tail else "")


def list_entries(data):
    """Print all available experiences, projects, and their variants."""
    print("=== Education ===")
    for e in data.get("education", []):
        print(f"  {e['id']}: {e['institution']} — {e['degree']}")

    print("\n=== Experiences ===")
    for eid, exp in data.get("experiences", {}).items():
        variants = list(exp.get("variants", {}).keys())
        print(f"  {eid}: {exp['company']} — {exp['role']}")
        print(f"    variants: {', '.join(variants)}")

    print("\n=== Projects ===")
    for pid, proj in data.get("projects", {}).items():
        variants = list(proj.get("variants", {}).keys())
        print(f"  {pid}: {proj['title']}")
        print(f"    variants: {', '.join(variants)}")

    print(f"\n=== Skills: {'included by default' if data.get('skills') else 'not set'} ===")


def main():
    parser = argparse.ArgumentParser(description="Modular CV Generator")
    parser.add_argument("--data", default=None,
                        help="Path to cv_data.yaml (default: same dir as script)")
    parser.add_argument("--profile", default=None,
                        help="Path to profile YAML")
    parser.add_argument("--out", default="output/cv.tex",
                        help="Output .tex path")
    parser.add_argument("--pdf", action="store_true",
                        help="Also compile to PDF via xelatex")
    parser.add_argument("--list", action="store_true",
                        help="List all available experiences and variants")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = args.data or os.path.join(script_dir, "cv_data.yaml")
    data = load_yaml(data_path)

    if args.list:
        list_entries(data)
        return

    if not args.profile:
        parser.error("--profile is required (or use --list)")

    profile = load_yaml(args.profile)

    tex = generate_tex(data, profile)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(tex)
    print(f"Generated: {args.out}")

    if args.pdf:
        ok, err = compile_pdf(args.out, out_dir)
        if ok:
            pdf_path = os.path.splitext(args.out)[0] + ".pdf"
            print(f"Compiled: {pdf_path}")
        else:
            print("PDF compilation failed", file=sys.stderr)
            if err:
                print(f"  xelatex: {err}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
