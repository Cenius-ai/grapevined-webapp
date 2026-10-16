"""The three trackers: block registry, yield, ripeness and trellis."""

from __future__ import annotations

import datetime as dt

from helpers import (
    add_block,
    assert_single_line_error,
    init_store,
    read_store,
    run,
    store_bytes,
)


# -- F1 block registry -----------------------------------------------------

def test_block_add_then_list_shows_id_name_variety_and_vines(tmp_path):
    init_store(tmp_path)
    added = add_block(tmp_path, "North Ridge", "Pinot Noir", "--vines", "480", "--rows", "8")
    assert added.stdout.startswith("block 1 added")

    listed = run("block", "list", cwd=tmp_path)
    assert listed.returncode == 0
    row = [line for line in listed.stdout.splitlines() if "North Ridge" in line]
    assert len(row) == 1
    assert row[0].split() == ["1", "North", "Ridge", "Pinot", "Noir", "480", "8"]


def test_duplicate_block_name_is_rejected_and_stores_nothing(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    before = store_bytes(tmp_path)
    result = run("block", "add", "--name", "north ridge", "--variety", "Pinot Noir", cwd=tmp_path)
    assert_single_line_error(result, "already exists")
    assert store_bytes(tmp_path) == before
    assert len(read_store(tmp_path)["blocks"]) == 1


def test_block_show_unknown_id_is_one_line_and_nonzero(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    result = run("block", "show", "--id", "99", cwd=tmp_path)
    assert_single_line_error(result, "no block has that id")


def test_block_show_includes_logged_yield_and_latest_ripeness(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge", "Pinot Noir", "--vines", "480")
    run("yield", "log", "--block", "1", "--kg", "1250", "--date", "2024-09-12", cwd=tmp_path)
    run("ripeness", "add", "--block", "1", "--brix", "21.4", "--date", "2024-08-20", cwd=tmp_path)
    run("ripeness", "add", "--block", "1", "--brix", "24", "--ph", "3.35", "--date", "2024-09-05", cwd=tmp_path)

    shown = run("block", "show", "--id", "1", cwd=tmp_path)
    assert shown.returncode == 0
    assert "North Ridge" in shown.stdout
    assert "1250 kg" in shown.stdout
    assert "2024-09-05" in shown.stdout and "Brix 24" in shown.stdout


def test_block_list_empty_state_invites_the_next_command(tmp_path):
    init_store(tmp_path)
    listed = run("block", "list", cwd=tmp_path)
    assert listed.returncode == 0
    assert "no blocks registered yet" in listed.stdout
    assert "block add --name" in listed.stdout


# -- F2 yield tracker ------------------------------------------------------

def test_yield_log_and_report_totals_per_block_and_vintage(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge", "Pinot Noir", "--vines", "480")
    run("yield", "log", "--block", "1", "--kg", "1250", "--date", "2024-09-12", cwd=tmp_path)
    run("yield", "log", "--block", "1", "--kg", "250", "--date", "2024-09-14", cwd=tmp_path)
    run("yield", "log", "--block", "1", "--kg", "900", "--date", "2023-09-12", cwd=tmp_path)

    report = run("yield", "report", cwd=tmp_path)
    assert report.returncode == 0
    lines = report.stdout.splitlines()
    row_2023 = [line for line in lines if " 2023 " in line][0]
    row_2024 = [line for line in lines if " 2024 " in line][0]
    assert row_2024.split() == ["1", "North", "Ridge", "2024", "2", "1500", "3.12"]
    assert row_2023.split() == ["1", "North", "Ridge", "2023", "1", "900", "1.88"]
    assert "total: 2400 kg from 3 entries across 1 block" in report.stdout


def test_yield_report_without_a_vine_count_prints_no_kg_per_vine(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "Creek Flat", "Chardonnay")
    run("yield", "log", "--block", "1", "--kg", "900", "--date", "2024-09-20", cwd=tmp_path)
    report = run("yield", "report", cwd=tmp_path)
    assert report.stdout.splitlines()[2].split() == ["1", "Creek", "Flat", "2024", "1", "900", "-"]


def test_yield_report_empty_state_invites_the_next_command(tmp_path):
    init_store(tmp_path)
    report = run("yield", "report", cwd=tmp_path)
    assert report.returncode == 0
    assert "no yield logged yet" in report.stdout


def test_yield_defaults_vintage_to_the_year_of_the_date(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    run("yield", "log", "--block", "1", "--kg", "10", "--date", "2021-09-12", cwd=tmp_path)
    assert read_store(tmp_path)["yield_events"][0]["vintage"] == 2021


def test_yield_rejects_unknown_block_and_stores_nothing(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    before = store_bytes(tmp_path)
    result = run("yield", "log", "--block", "99", "--kg", "100", "--date", "2024-09-12", cwd=tmp_path)
    assert_single_line_error(result, "no block has that id")
    assert store_bytes(tmp_path) == before
    assert read_store(tmp_path)["yield_events"] == []


# -- F4 ripeness log -------------------------------------------------------

def test_ripeness_list_is_date_ascending_with_the_newest_marked_latest(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge", "Pinot Noir", "--vines", "480")
    # logged out of order on purpose: the list must sort by date, not by id
    run("ripeness", "add", "--block", "1", "--brix", "24", "--date", "2024-09-05", cwd=tmp_path)
    run("ripeness", "add", "--block", "1", "--brix", "22.5", "--ph", "3.4", "--ta", "6.1",
        "--date", "2024-08-30", cwd=tmp_path)

    listed = run("ripeness", "list", "--block", "1", cwd=tmp_path)
    assert listed.returncode == 0
    lines = listed.stdout.splitlines()
    body = lines[3:5]  # title, header, rule, then one row per sample
    assert body[0].split()[:5] == ["2", "2024-08-30", "22.5", "3.4", "6.1"]
    assert body[1].split()[:5] == ["1", "2024-09-05", "24", "-", "-"]
    assert body[1].split()[-1] == "latest"
    assert "latest" not in body[0]
    assert "newest dated 2024-09-05" in listed.stdout


def test_ripeness_rejects_out_of_range_and_malformed_input(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    before = store_bytes(tmp_path)
    cases = [
        (["ripeness", "add", "--block", "1", "--brix", "0", "--date", "2024-08-30"], "greater than zero"),
        (["ripeness", "add", "--block", "1", "--brix", "40.5", "--date", "2024-08-30"], "at most 40"),
        (["ripeness", "add", "--block", "1", "--brix", "22", "--ph", "15", "--date", "2024-08-30"], "between 0 and 14"),
        (["ripeness", "add", "--block", "1", "--brix", "22", "--ta", "0", "--date", "2024-08-30"], "TA must be greater than zero"),
        (["ripeness", "add", "--block", "1", "--brix", "22", "--date", "30-08-2024"], "YYYY-MM-DD"),
        (["ripeness", "add", "--block", "7", "--brix", "22", "--date", "2024-08-30"], "no block has that id"),
    ]
    for args, needle in cases:
        assert_single_line_error(run(*args, cwd=tmp_path), needle)
        assert store_bytes(tmp_path) == before
    assert read_store(tmp_path)["ripeness_samples"] == []


def test_ripeness_future_date_is_rejected(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    future = (dt.date.today() + dt.timedelta(days=2)).isoformat()
    before = store_bytes(tmp_path)
    result = run("ripeness", "add", "--block", "1", "--brix", "22", "--date", future, cwd=tmp_path)
    assert_single_line_error(result, "cannot be in the future")
    assert store_bytes(tmp_path) == before


def test_ripeness_list_empty_state_invites_the_next_command(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    listed = run("ripeness", "list", "--block", "1", cwd=tmp_path)
    assert listed.returncode == 0
    assert "no samples recorded for block 1" in listed.stdout


# -- F3 trellis scheduler --------------------------------------------------

def test_trellis_add_list_done_and_rm(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    future = (dt.date.today() + dt.timedelta(days=30)).isoformat()

    added = run("trellis", "add", "--block", "1", "--title", "Replace trellis wire row 3",
                "--due", future, cwd=tmp_path)
    assert added.returncode == 0 and added.stdout.startswith("trellis job 1 scheduled")

    listed = run("trellis", "list", cwd=tmp_path)
    row = [line for line in listed.stdout.splitlines() if "Replace trellis wire row 3" in line][0]
    assert row.split()[:4] == ["1", future, "open", "1"]
    assert "overdue" not in row

    done = run("trellis", "done", "--id", "1", cwd=tmp_path)
    assert done.returncode == 0
    task = read_store(tmp_path)["trellis_tasks"][0]
    assert task["status"] == "done"
    assert task["completed_on"] == dt.date.today().isoformat()
    assert dt.date.today().isoformat() in run("trellis", "list", cwd=tmp_path).stdout

    removed = run("trellis", "rm", "--id", "1", cwd=tmp_path)
    assert removed.returncode == 0
    assert read_store(tmp_path)["trellis_tasks"] == []
    assert "no open jobs" in run("trellis", "list", cwd=tmp_path).stdout


def test_trellis_list_flags_only_open_overdue_jobs(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    run("trellis", "add", "--block", "1", "--title", "Stuck post", "--due", "2020-01-01", cwd=tmp_path)
    future = (dt.date.today() + dt.timedelta(days=14)).isoformat()
    run("trellis", "add", "--block", "1", "--title", "Rewire row 9", "--due", future, cwd=tmp_path)
    run("trellis", "add", "--block", "1", "--title", "Old closed job", "--due", "2020-01-01", cwd=tmp_path)
    run("trellis", "done", "--id", "3", cwd=tmp_path)

    output = run("trellis", "list", cwd=tmp_path).stdout
    flagged = [line for line in output.splitlines() if "overdue" in line and "jobs," not in line]
    assert len(flagged) == 1
    assert "Stuck post" in flagged[0]
    assert "3 jobs, 2 open, 1 overdue" in output


def test_trellis_done_and_rm_reject_unknown_ids_without_touching_the_store(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    run("trellis", "add", "--block", "1", "--title", "Fix post", "--due", "2024-10-01", cwd=tmp_path)
    before = store_bytes(tmp_path)
    assert_single_line_error(run("trellis", "done", "--id", "99", cwd=tmp_path), "no trellis job has that id")
    assert store_bytes(tmp_path) == before
    assert_single_line_error(run("trellis", "rm", "--id", "99", cwd=tmp_path), "no trellis job has that id")
    assert store_bytes(tmp_path) == before
    assert len(read_store(tmp_path)["trellis_tasks"]) == 1


def test_trellis_add_rejects_bad_due_date_and_unknown_block(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    before = store_bytes(tmp_path)
    assert_single_line_error(
        run("trellis", "add", "--block", "1", "--title", "Fix post", "--due", "01-10-2024", cwd=tmp_path),
        "due date must be in YYYY-MM-DD form",
    )
    assert_single_line_error(
        run("trellis", "add", "--block", "9", "--title", "Fix post", "--due", "2024-10-01", cwd=tmp_path),
        "no block has that id",
    )
    assert store_bytes(tmp_path) == before


def test_scheduling_a_job_before_its_block_exists_stores_nothing(tmp_path):
    init_store(tmp_path)
    result = run("trellis", "add", "--block", "1", "--title", "Fix post", "--due", "2024-10-01", cwd=tmp_path)
    assert_single_line_error(result, "no block has that id")
    assert read_store(tmp_path)["trellis_tasks"] == []


def test_deleted_trellis_ids_are_never_reused(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    run("trellis", "add", "--block", "1", "--title", "First job", "--due", "2024-10-01", cwd=tmp_path)
    run("trellis", "rm", "--id", "1", cwd=tmp_path)
    added = run("trellis", "add", "--block", "1", "--title", "Second job", "--due", "2024-10-02", cwd=tmp_path)
    assert "trellis job 2 scheduled" in added.stdout
    assert read_store(tmp_path)["trellis_tasks"][0]["id"] == 2


def test_trellis_done_twice_is_reported_without_a_second_write(tmp_path):
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    run("trellis", "add", "--block", "1", "--title", "Fix post", "--due", "2024-10-01", cwd=tmp_path)
    run("trellis", "done", "--id", "1", cwd=tmp_path)
    before = store_bytes(tmp_path)
    again = run("trellis", "done", "--id", "1", cwd=tmp_path)
    assert again.returncode == 0
    assert "already done" in again.stdout
    assert store_bytes(tmp_path) == before


def test_a_block_id_is_not_a_trellis_job_id(tmp_path):
    """`trellis done --id 2` addresses job 2, never block 2's job."""
    init_store(tmp_path)
    add_block(tmp_path, "North Ridge")
    add_block(tmp_path, "Creek Flat")
    run("trellis", "add", "--block", "2", "--title", "Fix post row 12", "--due", "2024-10-01", cwd=tmp_path)
    assert_single_line_error(run("trellis", "done", "--id", "99", cwd=tmp_path), "no trellis job has that id")
    assert_single_line_error(run("block", "show", "--id", "99", cwd=tmp_path), "no block has that id")
    assert read_store(tmp_path)["trellis_tasks"][0]["status"] == "open"
