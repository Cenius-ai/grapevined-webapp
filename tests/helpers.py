"""Shared helpers for the Grapevined command-line test suite.

Every test drives the real ``grapevined.py`` as a subprocess in a throwaway
working directory, which is the only way to prove the promises that matter:
one line on stderr, a non-zero exit code, and a byte-identical store.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLI = PROJECT_ROOT / "grapevined.py"
STORE_NAME = "grapevined.json"

DEMO_PASSPHRASE = "cenius"
TEST_PASSPHRASE = "shed-passphrase"


def run(
    *args: str,
    cwd: Path,
    passphrase: Optional[str] = TEST_PASSPHRASE,
) -> subprocess.CompletedProcess:
    """Run grapevined.py in `cwd`, with the passphrase env var set or removed."""
    env = dict(os.environ)
    env.pop("GRAPEVINED_PASSPHRASE", None)
    if passphrase is not None:
        env["GRAPEVINED_PASSPHRASE"] = passphrase
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )


def store_path(cwd: Path) -> Path:
    return cwd / STORE_NAME


def store_bytes(cwd: Path) -> bytes:
    return store_path(cwd).read_bytes()


def read_store(cwd: Path) -> Dict[str, Any]:
    return json.loads(store_bytes(cwd).decode("utf-8"))


def init_store(cwd: Path, passphrase: str = TEST_PASSPHRASE) -> subprocess.CompletedProcess:
    result = run("init", "--passphrase", passphrase, cwd=cwd)
    assert result.returncode == 0, result.stderr
    return result


def add_block(
    cwd: Path,
    name: str,
    variety: str = "Pinot Noir",
    *extra: str,
    passphrase: str = TEST_PASSPHRASE,
) -> subprocess.CompletedProcess:
    result = run("block", "add", "--name", name, "--variety", variety, *extra,
                 cwd=cwd, passphrase=passphrase)
    assert result.returncode == 0, result.stderr
    return result


def assert_single_line_error(
    result: subprocess.CompletedProcess,
    needle: str,
    expected_code: int = 2,
) -> str:
    """Assert the one-line error contract and return the offending line."""
    assert result.returncode == expected_code, (
        "expected exit %s, got %s (stderr=%r)" % (expected_code, result.returncode, result.stderr)
    )
    assert result.stdout == "", "a failing command must not write to stdout: %r" % result.stdout
    lines = result.stderr.splitlines()
    assert len(lines) == 1, "expected exactly one stderr line, got %r" % lines
    assert needle.lower() in lines[0].lower(), "%r not found in %r" % (needle, lines[0])
    return lines[0]


def assert_only_ascii(text: str) -> None:
    for char in text:
        assert ord(char) < 128, "non-ASCII character %r in output" % char
