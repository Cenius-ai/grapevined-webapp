#!/bin/sh
# Grapevined installer.
#
# Installs project-level dependencies only, then EXITS. It never installs a
# system package, never touches a service and never starts anything in the
# foreground. Safe to re-run: every step is idempotent.
#
# The application has no third-party runtime dependency, so this script mostly
# proves the interpreter can import and run the tool.
set -eu

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

echo "Grapevined install"
echo "  python: $("$PYTHON" --version 2>&1)"
echo "  project: $(pwd)"

# 1. Refresh packaging tooling first: old pip silently fails modern installs.
#    Offline is not fatal here because Grapevined has nothing to download.
if ! "$PYTHON" -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1; then
    echo "  note: could not refresh pip/setuptools/wheel (offline?). Continuing:" \
         "Grapevined has no third-party runtime dependencies." >&2
fi

# 2. Runtime dependencies (declared, deliberately empty).
"$PYTHON" -m pip install -r requirements.txt

# 3. Optional console entry point. The tool runs standalone either way, so a
#    failure here is a warning, not an install failure.
if "$PYTHON" -m pip install --no-build-isolation -e . >/dev/null 2>&1; then
    echo "  installed the 'grapevined' console command (optional sugar)"
else
    echo "  note: editable install skipped - run the tool as: python3 grapevined.py" >&2
fi

# 4. Test runner, installed only when it is not already on the interpreter.
if "$PYTHON" -c 'import pytest' >/dev/null 2>&1; then
    echo "  pytest already available: $("$PYTHON" -c 'import pytest; print(pytest.__version__)')"
else
    "$PYTHON" -m pip install -r requirements-dev.txt
fi

# 5. Cheap self-check so an incomplete environment fails here, not at first use.
"$PYTHON" -c 'import grapevined; assert callable(grapevined.main)'
"$PYTHON" grapevined.py --version >/dev/null

echo "Setup complete. Nothing is running in the background."
echo
echo "Next:"
echo "  python3 grapevined.py init --passphrase <phrase>"
echo "  export GRAPEVINED_PASSPHRASE=<phrase>"
echo "  python3 grapevined.py block add --name \"North Ridge\" --variety \"Pinot Noir\" --vines 480"
echo "  python3 grapevined.py block list"
echo
echo "  bash demo.sh        # full season walkthrough on a scratch store"
echo "  python3 -m pytest   # test suite"
