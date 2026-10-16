"""The README quick start, run start-to-finish exactly as documented."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from helpers import DEMO_PASSPHRASE, assert_only_ascii, init_store, read_store, run

PASSPHRASE = DEMO_PASSPHRASE  # the standard demo credential used by demo.sh and the README


def gv(*args: str, cwd: Path):
    return run(*args, cwd=cwd, passphrase=PASSPHRASE)


def test_readme_quick_start_walks_a_full_season(tmp_path):
    """Every command in the README quick start succeeds in order and shows data."""
    # 1. create the store with a passphrase
    assert init_store(tmp_path, PASSPHRASE).returncode == 0

    # 2. register two blocks
    first = gv("block", "add", "--name", "North Ridge", "--variety", "Pinot Noir",
               "--vines", "480", "--rows", "8", "--planted-year", "2016", cwd=tmp_path)
    assert first.returncode == 0, first.stderr
    second = gv("block", "add", "--name", "Creek Flat", "--variety", "Chardonnay",
                "--vines", "320", cwd=tmp_path)
    assert second.returncode == 0, second.stderr

    # 3. log yield for both blocks
    this_year = dt.date.today().year
    for block, kg in (("1", "1250"), ("1", "250"), ("2", "1610")):
        logged = gv("yield", "log", "--block", block, "--kg", kg,
                    "--date", "%d-09-12" % this_year, cwd=tmp_path)
        assert logged.returncode == 0, logged.stderr

    # 4. record ripeness samples through the ripening window
    for block, brix, date in (("1", "19.8", "%d-08-12" % this_year),
                              ("1", "22.5", "%d-08-30" % this_year),
                              ("2", "18.2", "%d-08-28" % this_year)):
        sampled = gv("ripeness", "add", "--block", block, "--brix", brix, "--date", date, cwd=tmp_path)
        assert sampled.returncode == 0, sampled.stderr

    # 5. schedule and close a trellis job
    due = (dt.date.today() + dt.timedelta(days=21)).isoformat()
    scheduled = gv("trellis", "add", "--block", "1", "--title", "Replace trellis wire row 3",
                   "--due", due, cwd=tmp_path)
    assert scheduled.returncode == 0, scheduled.stderr
    assert gv("trellis", "done", "--id", "1", cwd=tmp_path).returncode == 0

    # 6. read everything back: every list and report renders real seeded content
    block_list = gv("block", "list", cwd=tmp_path)
    assert "North Ridge" in block_list.stdout and "Creek Flat" in block_list.stdout

    report = gv("yield", "report", cwd=tmp_path)
    assert "total: 3110 kg from 3 entries across 2 blocks" in report.stdout

    ripeness = gv("ripeness", "list", "--block", "1", cwd=tmp_path)
    assert "22.5" in ripeness.stdout and "latest" in ripeness.stdout

    trellis = gv("trellis", "list", cwd=tmp_path)
    assert "Replace trellis wire row 3" in trellis.stdout and "done" in trellis.stdout

    show = gv("block", "show", "--id", "1", cwd=tmp_path)
    assert "1500 kg" in show.stdout

    for output in (block_list.stdout, report.stdout, ripeness.stdout, trellis.stdout, show.stdout):
        assert_only_ascii(output)

    # 7. the store is plain readable JSON and never holds the plaintext passphrase
    assert PASSPHRASE not in (tmp_path / "grapevined.json").read_text(encoding="utf-8")
    store = read_store(tmp_path)
    assert len(store["blocks"]) == 2
    assert len(store["yield_events"]) == 3
    assert len(store["ripeness_samples"]) == 3
    assert len(store["trellis_tasks"]) == 1


def test_standard_demo_credential_is_the_one_that_works(tmp_path):
    """The platform's standard demo credential opens the store built by demo.sh."""
    assert PASSPHRASE == "cenius"
    init_store(tmp_path, PASSPHRASE)
    assert gv("block", "list", cwd=tmp_path).returncode == 0
    assert run("block", "list", cwd=tmp_path, passphrase="something-else").returncode != 0
