"""Help surface, the local passphrase gate and the one-line error contract."""

from __future__ import annotations

import itertools
import json

import pytest

from helpers import (
    DEMO_PASSPHRASE,
    STORE_NAME,
    add_block,
    assert_only_ascii,
    assert_single_line_error,
    init_store,
    read_store,
    run,
    store_bytes,
    store_path,
)

GROUPS = ["block", "yield", "ripeness", "trellis", "init"]
LEAVES = [
    ("init", None),
    ("block", "add"),
    ("block", "list"),
    ("block", "show"),
    ("yield", "log"),
    ("yield", "report"),
    ("ripeness", "add"),
    ("ripeness", "list"),
    ("trellis", "add"),
    ("trellis", "list"),
    ("trellis", "done"),
    ("trellis", "rm"),
]


# -- help surface ----------------------------------------------------------

def test_root_help_lists_every_command_group_without_a_store(tmp_path):
    result = run("--help", cwd=tmp_path)
    assert result.returncode == 0
    for name in GROUPS:
        assert name in result.stdout
    assert not store_path(tmp_path).exists()
    assert_only_ascii(result.stdout)


def test_bare_invocation_prints_usage_and_exits_zero(tmp_path):
    result = run(cwd=tmp_path)
    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert not store_path(tmp_path).exists()


@pytest.mark.parametrize("group", GROUPS)
def test_group_help_needs_no_passphrase_or_store(tmp_path, group):
    result = run(group, "--help", cwd=tmp_path, passphrase=None)
    assert result.returncode == 0
    assert "usage:" in result.stdout


@pytest.mark.parametrize("group,subcommand", LEAVES)
def test_every_leaf_help_exits_zero_without_a_store(tmp_path, group, subcommand):
    args = [group] if subcommand is None else [group, subcommand]
    result = run(*args, "--help", cwd=tmp_path, passphrase=None)
    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_version_flag(tmp_path):
    result = run("--version", cwd=tmp_path)
    assert result.returncode == 0
    assert "Grapevined" in result.stdout


# -- store bootstrap -------------------------------------------------------

def test_command_without_a_store_errors_and_creates_nothing(tmp_path):
    result = run("block", "list", cwd=tmp_path, passphrase=None)
    assert_single_line_error(result, "no store found")
    assert "init" in result.stderr
    assert not store_path(tmp_path).exists()
    assert list(tmp_path.iterdir()) == []


def test_init_writes_a_salted_hash_and_never_the_plaintext(tmp_path):
    init_store(tmp_path, "hunter2")
    raw = store_bytes(tmp_path)
    assert b"hunter2" not in raw
    store = json.loads(raw.decode("utf-8"))
    assert store["version"] == 1
    assert store["auth"]["iterations"] >= 200_000
    assert len(store["auth"]["salt"]) == 32  # 16 random bytes, hex encoded
    assert len(store["auth"]["hash"]) == 64  # sha256 digest, hex encoded
    assert store["blocks"] == [] and store["yield_events"] == []


def test_init_is_idempotent_only_with_force(tmp_path):
    init_store(tmp_path, "hunter2")
    add_block(tmp_path, "North Ridge", passphrase="hunter2")
    before = store_bytes(tmp_path)

    refused = run("init", "--passphrase", "other", cwd=tmp_path)
    assert_single_line_error(refused, "already exists")
    assert store_bytes(tmp_path) == before

    forced = run("init", "--passphrase", "other", "--force", cwd=tmp_path)
    assert forced.returncode == 0
    assert read_store(tmp_path)["blocks"] == []
    assert store_bytes(tmp_path) != before


def test_init_rejects_an_empty_passphrase(tmp_path):
    result = run("init", "--passphrase", "  ", cwd=tmp_path)
    assert_single_line_error(result, "non-empty passphrase")
    assert not store_path(tmp_path).exists()


# -- passphrase gate -------------------------------------------------------

def test_passphrase_is_required_for_later_commands(tmp_path):
    init_store(tmp_path)
    before = store_bytes(tmp_path)
    result = run("block", "list", cwd=tmp_path, passphrase=None)
    assert_single_line_error(result, "passphrase required")
    assert "GRAPEVINED_PASSPHRASE" in result.stderr
    assert store_bytes(tmp_path) == before


def test_wrong_passphrase_is_one_non_enumerating_line_and_touches_nothing(tmp_path):
    init_store(tmp_path, "correct-horse")
    add_block(tmp_path, "North Ridge", passphrase="correct-horse")
    before = store_bytes(tmp_path)
    result = run("block", "list", cwd=tmp_path, passphrase="wrong")
    line = assert_single_line_error(result, "passphrase not accepted")
    assert "North Ridge" not in line
    assert "hash" not in line.lower()
    assert store_bytes(tmp_path) == before


def test_correct_passphrase_unlocks_the_store(tmp_path):
    init_store(tmp_path, DEMO_PASSPHRASE)
    result = run("block", "list", cwd=tmp_path, passphrase=DEMO_PASSPHRASE)
    assert result.returncode == 0
    assert "no blocks registered yet" in result.stdout


# -- error contract --------------------------------------------------------

def _populated_store(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge", "Pinot Noir", "--vines", "480")
    run("trellis", "add", "--block", "1", "--title", "Fix post", "--due", "2024-10-01", cwd=tmp_path)
    return tmp_path


BAD_COMMANDS = [
    ["yield", "log", "--block", "1", "--kg", "-5", "--date", "2024-09-12"],
    ["yield", "log", "--block", "1", "--kg", "100", "--date", "2099-09-12"],
    ["yield", "log", "--block", "1", "--kg", "100", "--date", "12-09-2024"],
    ["yield", "log", "--block", "1", "--kg", "abc", "--date", "2024-09-12"],
    ["yield", "log", "--block", "99", "--kg", "100", "--date", "2024-09-12"],
    ["ripeness", "add", "--block", "1", "--brix", "0", "--date", "2024-08-30"],
    ["ripeness", "add", "--block", "1", "--brix", "41", "--date", "2024-08-30"],
    ["ripeness", "add", "--block", "1", "--brix", "22", "--ph", "15", "--date", "2024-08-30"],
    ["ripeness", "add", "--block", "1", "--brix", "22", "--date", "30-08-2024"],
    ["ripeness", "add", "--block", "7", "--brix", "22", "--date", "2024-08-30"],
    ["ripeness", "list", "--block", "7"],
    ["trellis", "add", "--block", "1", "--title", "Fix post", "--due", "01-10-2024"],
    ["trellis", "add", "--block", "9", "--title", "Fix post", "--due", "2024-10-01"],
    ["trellis", "done", "--id", "99"],
    ["trellis", "rm", "--id", "99"],
    ["block", "show", "--id", "99"],
    ["block", "add", "--name", "North Ridge", "--variety", "Pinot Noir"],
    ["block", "add", "--name", "South", "--variety", "Shiraz", "--vines", "0"],
    ["block", "add", "--name", "South", "--variety", "Shiraz", "--planted-year", "1500"],
]


@pytest.mark.parametrize("args", BAD_COMMANDS, ids=lambda args: " ".join(args))
def test_every_rejected_command_is_one_line_and_leaves_the_store_identical(tmp_path, args):
    _populated_store(tmp_path)
    before = store_bytes(tmp_path)
    result = run(*args, cwd=tmp_path)
    assert result.returncode != 0
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert result.stderr.startswith("error: ")
    assert_only_ascii(result.stderr)
    assert store_bytes(tmp_path) == before


def test_rejected_command_leaves_no_temporary_file_behind(tmp_path):
    _populated_store(tmp_path)
    run("yield", "log", "--block", "99", "--kg", "1", "--date", "2024-09-12", cwd=tmp_path)
    leftover = [path.name for path in tmp_path.iterdir() if path.name != STORE_NAME]
    assert leftover == []


def test_successful_write_is_atomic_and_leaves_no_temp_file(tmp_path):
    _populated_store(tmp_path)
    assert run("block", "add", "--name", "Creek Flat", "--variety", "Chardonnay", cwd=tmp_path).returncode == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == [STORE_NAME]
    assert len(read_store(tmp_path)["blocks"]) == 2


def test_unknown_subcommand_is_one_line(tmp_path):
    init_store(tmp_path)
    result = run("block", "bogus", cwd=tmp_path)
    assert_single_line_error(result, "invalid choice")


def test_hand_edited_store_with_unknown_schema_version_is_refused(tmp_path):
    init_store(tmp_path)
    store = read_store(tmp_path)
    store["version"] = 99
    store_path(tmp_path).write_text(json.dumps(store), encoding="utf-8")
    before = store_bytes(tmp_path)
    result = run("block", "list", cwd=tmp_path)
    assert_single_line_error(result, "schema version")
    assert store_bytes(tmp_path) == before


def test_corrupt_store_is_refused_with_one_line(tmp_path):
    store_path(tmp_path).write_text("{not json at all", encoding="utf-8")
    before = store_bytes(tmp_path)
    result = run("block", "list", cwd=tmp_path)
    assert_single_line_error(result, "not valid JSON")
    assert store_bytes(tmp_path) == before


def test_missing_store_does_not_grow_the_working_directory(tmp_path):
    for args in itertools.chain([["block", "list"], ["yield", "report"], ["trellis", "list"]]):
        result = run(*args, cwd=tmp_path, passphrase=None)
        assert result.returncode != 0
    assert list(tmp_path.iterdir()) == []
