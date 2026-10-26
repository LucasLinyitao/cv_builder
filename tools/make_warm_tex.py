"""Write a sample .tex that uses the same packages/fonts as the real template.
build_windows.bat --with-tectonic compiles it once so Tectonic downloads exactly what's needed,
and that package cache is then shipped inside the app (first PDF works offline)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import generate_cv as g

data = {"template": {"font": "TeX Gyre Termes"},
        "personal": {"name": "Warm Up", "email": "a@b.c", "phone": "1", "location": "HK"},
        "education": [{"id": "e", "institution": "Uni", "period": "Sep 2024 - Present", "degree": "BSc",
                       "cgpa": "4.0", "courses": "X, Y", "awards": "Z"}],
        "experiences": {"x": {"company": "Co & Co", "role": "Intern", "location": "HK", "start": "2025-01",
                              "end": "present", "variants": {"v1": ["Did 100% of things_ #1 {ok}."]}}},
        "projects": {"p": {"title": "Proj", "start": "2024-01", "end": "2024-02", "variants": {"v1": ["Built it."]}}},
        "skills": {"Interests": "A, B", "Languages": "English"}}
profile = {"education": ["e"], "experiences": ["x:v1"], "projects": ["p:v1"], "include_skills": True}
out = sys.argv[1] if len(sys.argv) > 1 else "warm.tex"
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
open(out, "w", encoding="utf-8").write(g.generate_tex(data, profile))
print("wrote", out)
