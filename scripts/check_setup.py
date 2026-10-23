"""Week 1 setup check. Run it from the project folder:

    python scripts/check_setup.py

It prints "Setup OK" when your computer and project are ready. It never prints
the value of any secret, only whether things are in the right place.
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_PACKAGES = ["requests", "psycopg", "dotenv", "streamlit", "anthropic", "openai"]

failures = []
warnings = []


def ok(message):
    print(f"[ok]   {message}")


def fail(message, fix):
    failures.append(message)
    print(f"[FAIL] {message}\n       Fix: {fix}")


def warn(message):
    warnings.append(message)
    print(f"[warn] {message}")


# 1. Python version: the course standardizes on 3.12 so everyone's code behaves the same.
if sys.version_info >= (3, 12):
    ok(f"Python {sys.version_info.major}.{sys.version_info.minor}")
else:
    fail(f"Python {sys.version_info.major}.{sys.version_info.minor} is too old",
         "install Python 3.12 (ask your AI agent to help) and recreate .venv with it")

# 2. Virtual environment: keeps this project's packages separate from everything else.
if sys.prefix != sys.base_prefix:
    ok("Running inside a virtual environment")
else:
    warn("Not running inside a virtual environment. Activate .venv first (see README).")

# 3. Packages from requirements.txt.
missing = []
for name in REQUIRED_PACKAGES:
    try:
        importlib.import_module(name)
    except ImportError:
        missing.append(name)
if missing:
    fail(f"Missing packages: {', '.join(missing)}", "run: pip install -r requirements.txt")
else:
    ok("All required packages are installed")

# 4. .env exists (it holds your real secrets on this computer only).
env_file = ROOT / ".env"
if env_file.exists():
    ok(".env exists")
else:
    fail(".env not found", "copy .env.example to .env, then put a fake TEST_SECRET value in it")

# 5. .gitignore protects .env, so Git never uploads it.
gitignore = ROOT / ".gitignore"
ignored_lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
if ".env" in [line.strip() for line in ignored_lines]:
    ok(".gitignore lists .env")
else:
    fail(".gitignore does not list .env", "add a line containing exactly .env to .gitignore")

# 6. Git is not tracking .env (it can still be tracked if it was committed before being ignored).
try:
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if tracked.returncode == 0:
        fail(".env is tracked by Git, so your secrets would be uploaded",
             "run: git rm --cached .env  then commit. If real keys were ever pushed, rotate them.")
    else:
        ok("Git is not tracking .env")
except FileNotFoundError:
    warn("Git is not installed or not on your PATH, so the Git check was skipped.")

# 7. .env.example holds names only. It is public, so any value in it is a leaked value.
example = ROOT / ".env.example"
if example.exists():
    with_values = []
    for number, line in enumerate(example.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, _, value = stripped.partition("=")
        if value.strip():
            with_values.append(f"line {number} ({name.strip()})")
    if with_values:
        fail(".env.example contains values on " + ", ".join(with_values),
             "delete the values so each line reads NAME= with nothing after the equals sign")
    else:
        ok(".env.example contains names only")
else:
    fail(".env.example not found", "restore it from the course template")

# 8. Windows path length: very deep folders break some package installs.
if os.name == "nt" and len(str(ROOT)) > 80:
    warn(f"Your project path is {len(str(ROOT))} characters long. If installs fail with "
         "'No such file or directory', move the project to a short folder such as C:\\dev\\bsad6153.")

print()
if failures:
    print(f"Setup NOT OK: {len(failures)} problem(s) above. Ask your AI agent to help you fix them,")
    print("and read each command it suggests before you approve it.")
    sys.exit(1)
print("Setup OK" + (f" ({len(warnings)} warning(s) above)" if warnings else ""))
