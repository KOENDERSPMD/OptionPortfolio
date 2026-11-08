#!/usr/bin/env python3
"""Create a new app from the template.

    python3 new_app.py <target-dir> --package budget --title "Budget" [--port 8770] [--env BUDGET]

Copies assets/template to <target-dir>, renames the __pkg__ folder to the package name and fills in
the placeholders: __pkg__ (Python package), __ENV__ (environment-variable prefix), __TITLE__ (name
shown to the user) and __PORT__ (default port). Refuses to write into a non-empty directory, except
one that only holds a fresh git clone (.git, .github, README, LICENSE, .gitignore).
"""

import argparse
import keyword
import re
import shutil
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "template"
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".md", ".txt", ".ini", ".sh", ".service", ""}
ALLOWED_EXISTING = {".git", ".github", ".gitattributes", "README.md", "LICENSE", "LICENSE.md", ".gitignore"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target")
    ap.add_argument("--package", required=True, help="Python package name, e.g. budget")
    ap.add_argument("--title", required=True, help='Name shown in the UI, e.g. "Budget"')
    ap.add_argument("--port", type=int, default=8770, help="Default port (pick one no other app of yours uses)")
    ap.add_argument("--env", help="Environment-variable prefix (default: package name in capitals)")
    a = ap.parse_args()

    if not re.fullmatch(r"[a-z][a-z0-9_]*", a.package) or keyword.iskeyword(a.package):
        sys.exit("--package must be lower case letters, digits and _ (a valid Python name)")
    env = (a.env or a.package).upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", env):
        sys.exit("--env must be upper case letters, digits and _")
    if not 1024 < a.port < 65536:
        sys.exit("--port must be between 1025 and 65535")

    target = Path(a.target).resolve()
    if target.exists():
        extra = {p.name for p in target.iterdir()} - ALLOWED_EXISTING
        if extra:
            sys.exit(f"{target} is not empty ({', '.join(sorted(extra))}); choose a new directory")
    target.mkdir(parents=True, exist_ok=True)

    values = {"__pkg__": a.package, "__ENV__": env, "__TITLE__": a.title, "__PORT__": str(a.port)}
    for src in sorted(TEMPLATE.rglob("*")):
        if "__pycache__" in src.parts or src.suffix == ".pyc":
            continue
        rel = src.relative_to(TEMPLATE).as_posix().replace("__pkg__", a.package)
        if rel == "gitignore":
            rel = ".gitignore"  # stored without the dot so it doesn't act on the skill's own folder
        dst = target / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in TEXT_SUFFIXES:
            text = src.read_text(encoding="utf-8")
            for key, value in values.items():
                text = text.replace(key, value)
            dst.write_text(text, encoding="utf-8")
            shutil.copymode(src, dst)
        else:
            shutil.copy2(src, dst)

    left = [str(p.relative_to(target)) for p in target.rglob("*") if p.is_file() and ".git" not in p.parts
            and p.suffix in TEXT_SUFFIXES and re.search(r"__(pkg|ENV|TITLE|PORT)__", p.read_text(encoding="utf-8"))]
    if left:
        sys.exit(f"Placeholders left in: {', '.join(left)}")
    print(f"Created {a.title} in {target} (package {a.package}, env {env}_*, port {a.port})")
    print("Next:")
    print(f"  cd {target}")
    print("  python3 -m venv .venv && .venv/bin/pip install -q -r requirements-dev.txt")
    print("  .venv/bin/python -m pytest -q")
    print(f"  ./start.sh      (no screen: {env}_NO_BROWSER=1 ./start.sh)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
