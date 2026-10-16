#!/usr/bin/env python3
"""Grapevined - vineyard block, yield, ripeness and trellis tracker.

Everything lives in one local ``grapevined.json`` protected by a single local
passphrase supplied through the ``GRAPEVINED_PASSPHRASE`` environment variable.
Standard library only: no install step, no server, no network, no third-party
package.

Every rejection prints exactly one ASCII line on stderr and exits non-zero
without touching the store, so a mistyped command can never corrupt a season of
records.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sys
import tempfile
from typing import Any, Callable, Dict, List, NoReturn, Optional, Sequence, Set, Tuple

__version__ = "1.0.0"

PROG = "grapevined.py"
STORE_NAME = "grapevined.json"
SCHEMA_VERSION = 1
KDF_ALGORITHM = "sha256"
KDF_ITERATIONS = 200_000
PASSPHRASE_ENV = "GRAPEVINED_PASSPHRASE"

EXIT_OK = 0
EXIT_ERROR = 2

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Collection name -> the counter key that hands out its next id.
COLLECTION_ID_KEYS = {
    "blocks": "block",
    "yield_events": "yield_event",
    "ripeness_samples": "ripeness_sample",
    "trellis_tasks": "trellis_task",
}


# --------------------------------------------------------------------------
# The one-line error contract
# --------------------------------------------------------------------------

def error(message: str) -> NoReturn:
    """Print exactly one ASCII line on stderr and exit non-zero.

    Everything a user can get wrong funnels through here, so no subcommand can
    invent its own error shape and no error can ever be two lines long.
    """
    single_line = " ".join(str(message).split())
    sys.stderr.write("error: %s\n" % single_line)
    raise SystemExit(EXIT_ERROR)


# --------------------------------------------------------------------------
# Formatting helpers (plain ASCII, aligned terminal columns)
# --------------------------------------------------------------------------

def number(value: Optional[float]) -> str:
    """Render a number for a column: no trailing zeros, '-' when absent."""
    if value is None:
        return "-"
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        if value.is_integer():
            return str(int(value))
        return ("%.2f" % value).rstrip("0").rstrip(".")
    return str(value)


def whole(value: Optional[int]) -> str:
    """Render an optional integer for a column."""
    return "-" if value is None else str(value)


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    right_align: Set[int] = frozenset(),
) -> List[str]:
    """Lay rows out as aligned monospace columns with a dashed rule."""
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def line(cells: Sequence[str]) -> str:
        parts = []
        for index, cell in enumerate(cells):
            parts.append(cell.rjust(widths[index]) if index in right_align else cell.ljust(widths[index]))
        return "  ".join(parts).rstrip()

    lines = [line([str(header) for header in headers])]
    lines.append("  ".join("-" * width for width in widths))
    lines.extend(line([str(cell) for cell in row]) for row in rows)
    return lines


def print_lines(lines: Sequence[str]) -> None:
    for line in lines:
        print(line)


def today() -> dt.date:
    return dt.date.today()


# --------------------------------------------------------------------------
# Store I/O - one whole JSON file, rewritten atomically
# --------------------------------------------------------------------------

def store_dir() -> str:
    """The fixed base directory Grapevined reads and writes in, fully resolved.

    No command line, flag or environment variable ever supplies a path, so the
    base is always the working directory of the operator who ran the command.
    """
    return os.path.realpath(os.path.abspath(os.getcwd()))


def contained_path(name: str) -> str:
    """Resolve `name` inside the fixed base directory, refusing any escape.

    The candidate is fully resolved (realpath) and then required to stay inside
    the resolved base directory, so a relative fragment, a symlink, an absolute
    name or a hand-built string can never point a read or a write outside the
    operator's own folder. Both halves of the path are otherwise constants: the
    base from the working directory, the file name from this module.
    """
    base = store_dir()
    candidate = os.path.realpath(os.path.join(base, name))
    if not candidate.startswith(base + os.sep):
        error("%s must stay inside the working directory (%s)" % (name, base))
    return candidate


def store_path() -> str:
    """Absolute path of the store: <working directory>/grapevined.json."""
    return contained_path(STORE_NAME)


def decode_store(text: str) -> Any:
    """Parse store text with a JSON-only parser.

    The store is data, never code: this is the single place any stored byte is
    turned back into Python, it accepts JSON and nothing else, and the parsed
    shape is validated by the caller before any of it is used.
    """
    try:
        return json.loads(text)
    except ValueError:
        error("%s is not valid JSON - repair it or re-run: %s init --force" % (STORE_NAME, PROG))


def encode_store(store: Dict[str, Any]) -> str:
    """Serialise the store as indented JSON that a human can read and diff."""
    return json.dumps(store, indent=2) + "\n"


def new_store(salt_hex: str, iterations: int, digest_hex: str) -> Dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "auth": {"salt": salt_hex, "iterations": iterations, "hash": digest_hex},
        "blocks": [],
        "yield_events": [],
        "ripeness_samples": [],
        "trellis_tasks": [],
        "next_ids": {key: 1 for key in COLLECTION_ID_KEYS.values()},
    }


def normalise_store(data: Dict[str, Any]) -> Dict[str, Any]:
    """Repair a hand-edited store so a missing key cannot crash a command."""
    for collection in COLLECTION_ID_KEYS:
        if not isinstance(data.get(collection), list):
            data[collection] = []
    counters = data.get("next_ids")
    if not isinstance(counters, dict):
        counters = {}
        data["next_ids"] = counters
    for collection, key in COLLECTION_ID_KEYS.items():
        highest = 0
        for record in data[collection]:
            if isinstance(record, dict) and isinstance(record.get("id"), int):
                highest = max(highest, record["id"])
        stored = counters.get(key)
        if not isinstance(stored, int) or stored <= highest:
            counters[key] = highest + 1
    if not isinstance(data.get("auth"), dict):
        data["auth"] = {}
    return data


def load_store() -> Dict[str, Any]:
    path = contained_path(STORE_NAME)
    if not os.path.isfile(path):
        error("no store found here - run: %s init --passphrase <phrase> first" % PROG)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        error("could not read %s (%s)" % (STORE_NAME, exc.strerror or exc.__class__.__name__))
    data = decode_store(text)
    if not isinstance(data, dict):
        error("%s is not a Grapevined store - re-run: %s init --force" % (STORE_NAME, PROG))
    if data.get("version") != SCHEMA_VERSION:
        error(
            "%s has schema version %r, this build expects %d - re-run: %s init --force"
            % (STORE_NAME, data.get("version"), SCHEMA_VERSION, PROG)
        )
    return normalise_store(data)


def save_store(store: Dict[str, Any]) -> None:
    """Write the whole store through a temp file + os.replace (never partial).

    The destination is the resolved, containment-checked store path and the
    temporary file is created by tempfile inside that same directory, so no part
    of a save is ever built from a path fragment and nothing can touch a file
    outside the operator's own folder.
    """
    target = contained_path(STORE_NAME)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=os.path.dirname(target),
            prefix=STORE_NAME + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(encode_store(store))
            temp_name = handle.name
        os.replace(temp_name, target)
    except OSError as exc:
        try:
            os.remove(temp_name)
        except OSError:
            pass
        error("could not write %s (%s)" % (STORE_NAME, exc.strerror or exc.__class__.__name__))


def allocate_id(store: Dict[str, Any], collection: str) -> int:
    """Hand out the next id; ids are never recycled after a delete."""
    key = COLLECTION_ID_KEYS[collection]
    next_value = store["next_ids"][key]
    store["next_ids"][key] = next_value + 1
    return next_value


# --------------------------------------------------------------------------
# The local passphrase gate
# --------------------------------------------------------------------------

def derive_passphrase_hash(passphrase: str, salt: bytes, iterations: int) -> str:
    digest = hashlib.pbkdf2_hmac(KDF_ALGORITHM, passphrase.encode("utf-8"), salt, iterations)
    return digest.hex()


def verify_passphrase(store: Dict[str, Any]) -> None:
    auth = store["auth"]
    provided = os.environ.get(PASSPHRASE_ENV)
    if not provided:
        error("passphrase required - set the %s environment variable" % PASSPHRASE_ENV)
    salt_hex = auth.get("salt")
    iterations = auth.get("iterations")
    expected = auth.get("hash")
    if not isinstance(salt_hex, str) or not isinstance(expected, str) or not isinstance(iterations, int):
        error("the store has no usable passphrase hash - re-run: %s init --force" % PROG)
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        error("the store passphrase salt is damaged - re-run: %s init --force" % PROG)
    if not hmac.compare_digest(derive_passphrase_hash(provided, salt, iterations), expected):
        # One non-enumerating line: never reveal whether the store or the
        # passphrase was the part that was wrong.
        error("passphrase not accepted")


# --------------------------------------------------------------------------
# Shared validation helpers
# --------------------------------------------------------------------------

def parse_iso_date(value: str, label: str = "date") -> dt.date:
    if not ISO_DATE.match(value or ""):
        error("%s must be in YYYY-MM-DD form (got %r)" % (label, value))
    try:
        return dt.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        error("%s is not a real calendar date (got %r)" % (label, value))


def positive_number(value: float, label: str, maximum: Optional[float] = None) -> float:
    if value is None or not math.isfinite(value) or value <= 0:
        error("%s must be greater than zero (got %s)" % (label, number(value)))
    if maximum is not None and value > maximum:
        error("%s must be at most %s (got %s)" % (label, number(maximum), number(value)))
    return value


def require_block(store: Dict[str, Any], block_id: int) -> Dict[str, Any]:
    for block in store["blocks"]:
        if block.get("id") == block_id:
            return block
    error("no block has that id: %d" % block_id)


def require_task(store: Dict[str, Any], task_id: int) -> Dict[str, Any]:
    for task in store["trellis_tasks"]:
        if task.get("id") == task_id:
            return task
    error("no trellis job has that id: %d" % task_id)


def block_label(block: Dict[str, Any]) -> str:
    return "%d %s" % (block["id"], block["name"])


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> None:
    if os.path.isfile(store_path()) and not args.force:
        error("%s already exists - re-run with --force to replace the whole store" % STORE_NAME)
    passphrase = args.passphrase
    if not passphrase or not passphrase.strip():
        error("a non-empty passphrase is required")
    salt = secrets.token_bytes(16)
    digest = derive_passphrase_hash(passphrase, salt, KDF_ITERATIONS)
    save_store(new_store(salt.hex(), KDF_ITERATIONS, digest))
    print("initialised %s (%d record sets, schema version %d)" % (STORE_NAME, len(COLLECTION_ID_KEYS), SCHEMA_VERSION))
    print("passphrase stored as a salted PBKDF2-HMAC-SHA256 hash (%d iterations), never in plain text" % KDF_ITERATIONS)
    print("next: export %s=<your passphrase>" % PASSPHRASE_ENV)


# --------------------------------------------------------------------------
# block
# --------------------------------------------------------------------------

def cmd_block_add(args: argparse.Namespace, store: Dict[str, Any]) -> None:
    name = (args.name or "").strip()
    variety = (args.variety or "").strip()
    if not name:
        error("a block name is required")
    if not variety:
        error("a variety is required")
    for existing in store["blocks"]:
        if str(existing.get("name", "")).casefold() == name.casefold():
            error("a block named %r already exists (id %s)" % (existing.get("name"), existing.get("id")))
    if args.vines is not None and args.vines <= 0:
        error("vines must be greater than zero (got %d)" % args.vines)
    if args.rows is not None and args.rows <= 0:
        error("rows must be greater than zero (got %d)" % args.rows)
    if args.planted_year is not None and not 1900 <= args.planted_year <= 2100:
        error("planted year must be between 1900 and 2100 (got %d)" % args.planted_year)

    block = {
        "id": allocate_id(store, "blocks"),
        "name": name,
        "variety": variety,
        "rows": args.rows,
        "vines": args.vines,
        "planted_year": args.planted_year,
    }
    store["blocks"].append(block)
    save_store(store)
    detail = ", %s vines" % whole(args.vines) if args.vines else ""
    print("block %d added: %s (%s%s)" % (block["id"], name, variety, detail))


def cmd_block_list(args: argparse.Namespace, store: Dict[str, Any]) -> None:
    blocks = sorted(store["blocks"], key=lambda item: item.get("id", 0))
    if not blocks:
        print("no blocks registered yet - add one: %s block add --name North --variety Pinot --vines 480" % PROG)
        return
    rows = [
        [whole(block.get("id")), str(block.get("name", "")), str(block.get("variety", "")),
         whole(block.get("vines")), whole(block.get("rows"))]
        for block in blocks
    ]
    print_lines(render_table(["id", "name", "variety", "vines", "rows"], rows, right_align={0, 3, 4}))
    print("%d block%s" % (len(blocks), "" if len(blocks) == 1 else "s"))


def cmd_block_show(args: argparse.Namespace, store: Dict[str, Any]) -> None:
    block = require_block(store, args.id)
    events = [event for event in store["yield_events"] if event.get("block_id") == block["id"]]
    samples = sorted(
        [sample for sample in store["ripeness_samples"] if sample.get("block_id") == block["id"]],
        key=lambda sample: (str(sample.get("date", "")), sample.get("id", 0)),
    )

    print("block %d: %s" % (block["id"], block.get("name", "")))
    print("  variety         %s" % block.get("variety", "-"))
    print("  rows            %s" % whole(block.get("rows")))
    print("  vines           %s" % whole(block.get("vines")))
    print("  planted year    %s" % whole(block.get("planted_year")))

    if not events:
        print("  logged yield    none yet - %s yield log --block %d --kg 1250 --date %s" % (PROG, block["id"], today().isoformat()))
    else:
        total = sum(float(event.get("kg") or 0) for event in events)
        print("  logged yield    %s kg from %d entr%s" % (number(total), len(events), "y" if len(events) == 1 else "ies"))
        vine_count = block.get("vines")
        if vine_count:
            print("  kg per vine     %.2f" % (total / float(vine_count)))
        for vintage in sorted({event.get("vintage") for event in events}):
            subtotal = sum(float(event.get("kg") or 0) for event in events if event.get("vintage") == vintage)
            print("  vintage %-7s %s kg" % (vintage, number(subtotal)))

    if not samples:
        print("  latest ripeness none yet - %s ripeness add --block %d --brix 22.5 --date %s" % (PROG, block["id"], today().isoformat()))
    else:
        latest = samples[-1]
        extras = []
        if latest.get("ph") is not None:
            extras.append("pH %s" % number(latest.get("ph")))
        if latest.get("ta") is not None:
            extras.append("TA %s g/L" % number(latest.get("ta")))
        print("  latest ripeness %s  Brix %s%s" % (
            latest.get("date"), number(latest.get("brix")),
            ("  " + "  ".join(extras)) if extras else "",
        ))
        print("  samples on file %d" % len(samples))


# --------------------------------------------------------------------------
# yield
# --------------------------------------------------------------------------

def cmd_yield_log(args: argparse.Namespace, store: Dict[str, Any]) -> None:
    block = require_block(store, args.block)
    kg = positive_number(args.kg, "kg")
    day = parse_iso_date(args.date, "date")
    if day > today():
        error("the date cannot be in the future (got %s)" % args.date)
    vintage = args.vintage if args.vintage is not None else day.year
    if not 1900 <= vintage <= 2100:
        error("vintage must be between 1900 and 2100 (got %d)" % vintage)

    event = {
        "id": allocate_id(store, "yield_events"),
        "block_id": block["id"],
        "vintage": vintage,
        "date": day.isoformat(),
        "kg": kg,
        "notes": args.notes,
    }
    store["yield_events"].append(event)
    save_store(store)
    print("yield %d logged: %s kg for block %s on %s (vintage %d)" % (
        event["id"], number(kg), block_label(block), day.isoformat(), vintage))


def cmd_yield_report(args: argparse.Namespace, store: Dict[str, Any]) -> None:
    if not store["yield_events"]:
        print("no yield logged yet - log some: %s yield log --block 1 --kg 1250 --date %s" % (PROG, today().isoformat()))
        return

    blocks = {block.get("id"): block for block in store["blocks"]}
    grouped: Dict[Tuple[int, Any], List[Dict[str, Any]]] = {}
    for event in store["yield_events"]:
        grouped.setdefault((event.get("block_id"), event.get("vintage")), []).append(event)

    rows: List[List[str]] = []
    grand_total = 0.0
    grand_entries = 0
    block_totals: Dict[int, float] = {}
    for (block_id, vintage) in sorted(grouped, key=lambda key: (key[0] if key[0] is not None else -1, key[1] if key[1] is not None else 0)):
        events = grouped[(block_id, vintage)]
        subtotal = sum(float(event.get("kg") or 0) for event in events)
        grand_total += subtotal
        grand_entries += len(events)
        block_totals[block_id] = block_totals.get(block_id, 0.0) + subtotal
        block = blocks.get(block_id)
        vines = block.get("vines") if block else None
        rows.append([
            whole(block_id),
            (block.get("name") if block else "(deleted block)") or "-",
            whole(vintage),
            str(len(events)),
            number(subtotal),
            ("%.2f" % (subtotal / float(vines))) if vines else "-",
        ])

    print_lines(render_table(
        ["id", "block", "vintage", "entries", "kg", "kg/vine"],
        rows,
        right_align={0, 2, 3, 4, 5},
    ))
    print("total: %s kg from %d entr%s across %d block%s" % (
        number(grand_total), grand_entries, "y" if grand_entries == 1 else "ies",
        len(block_totals), "" if len(block_totals) == 1 else "s"))


# --------------------------------------------------------------------------
# ripeness
# --------------------------------------------------------------------------

def cmd_ripeness_add(args: argparse.Namespace, store: Dict[str, Any]) -> None:
    block = require_block(store, args.block)
    brix = args.brix
    if brix is None or not math.isfinite(brix) or brix <= 0:
        error("Brix must be greater than zero (got %s)" % number(brix))
    if brix > 40:
        error("Brix must be at most 40 (got %s)" % number(brix))
    if args.ph is not None and (not math.isfinite(args.ph) or not 0 <= args.ph <= 14):
        error("pH must be between 0 and 14 (got %s)" % number(args.ph))
    if args.ta is not None and (not math.isfinite(args.ta) or args.ta <= 0):
        error("TA must be greater than zero (got %s)" % number(args.ta))
    day = parse_iso_date(args.date, "date")
    if day > today():
        error("the date cannot be in the future (got %s)" % args.date)

    sample = {
        "id": allocate_id(store, "ripeness_samples"),
        "block_id": block["id"],
        "date": day.isoformat(),
        "brix": brix,
        "ph": args.ph,
        "ta": args.ta,
        "notes": args.notes,
    }
    store["ripeness_samples"].append(sample)
    save_store(store)
    print("ripeness sample %d stored: block %s on %s - Brix %s%s" % (
        sample["id"], block_label(block), day.isoformat(), number(brix),
        (", pH %s" % number(args.ph)) if args.ph is not None else "",
    ))


def cmd_ripeness_list(args: argparse.Namespace, store: Dict[str, Any]) -> None:
    block = require_block(store, args.block)
    samples = sorted(
        [sample for sample in store["ripeness_samples"] if sample.get("block_id") == block["id"]],
        key=lambda sample: (str(sample.get("date", "")), sample.get("id", 0)),
    )
    if not samples:
        print("no samples recorded for block %d - add one: %s ripeness add --block %d --brix 22.5 --date %s" % (
            block["id"], PROG, block["id"], today().isoformat()))
        return

    latest_id = samples[-1].get("id")
    rows = [
        [whole(sample.get("id")), str(sample.get("date", "")), number(sample.get("brix")),
         number(sample.get("ph")), number(sample.get("ta")),
         "latest" if sample.get("id") == latest_id else "",
         sample.get("notes") or ""]
        for sample in samples
    ]
    print("ripeness samples for block %s" % block_label(block))
    print_lines(render_table(["id", "date", "brix", "ph", "ta", "flag", "note"], rows, right_align={0, 2, 3, 4}))
    print("%d sample%s, newest dated %s" % (
        len(samples), "" if len(samples) == 1 else "s", samples[-1].get("date")))


# --------------------------------------------------------------------------
# trellis
# --------------------------------------------------------------------------

def cmd_trellis_add(args: argparse.Namespace, store: Dict[str, Any]) -> None:
    block = require_block(store, args.block)
    title = (args.title or "").strip()
    if not title:
        error("a job title is required")
    due = parse_iso_date(args.due, "due date")

    task = {
        "id": allocate_id(store, "trellis_tasks"),
        "block_id": block["id"],
        "title": title,
        "due": due.isoformat(),
        "status": "open",
        "completed_on": None,
    }
    store["trellis_tasks"].append(task)
    save_store(store)
    print("trellis job %d scheduled: %s for block %s, due %s" % (
        task["id"], title, block_label(block), due.isoformat()))


def cmd_trellis_list(args: argparse.Namespace, store: Dict[str, Any]) -> None:
    tasks = sorted(store["trellis_tasks"], key=lambda task: task.get("id", 0))
    blocks = {block.get("id"): block for block in store["blocks"]}
    open_tasks = [task for task in tasks if task.get("status") != "done"]
    if not tasks:
        print("no open jobs - schedule one: %s trellis add --block 1 --title \"Replace wire row 3\" --due %s" % (
            PROG, today().isoformat()))
        return

    current = today().isoformat()
    rows = []
    overdue_count = 0
    for task in tasks:
        status = task.get("status", "open")
        block = blocks.get(task.get("block_id"))
        overdue = status == "open" and str(task.get("due", "")) < current
        if overdue:
            overdue_count += 1
        rows.append([
            whole(task.get("id")),
            str(task.get("due", "")),
            status,
            str(task.get("block_id")),
            (block.get("name") if block else "(deleted block)") or "-",
            task.get("completed_on") or "-",
            "overdue" if overdue else "",
            str(task.get("title", "")),
        ])
    print_lines(render_table(
        ["id", "due", "status", "block", "block name", "completed", "flag", "title"],
        rows,
        right_align={0, 3},
    ))
    print("%d job%s, %d open, %d overdue" % (
        len(tasks), "" if len(tasks) == 1 else "s", len(open_tasks), overdue_count))


def cmd_trellis_done(args: argparse.Namespace, store: Dict[str, Any]) -> None:
    task = require_task(store, args.id)
    if task.get("status") == "done":
        print("trellis job %d is already done (completed %s)" % (task["id"], task.get("completed_on") or "-"))
        return
    task["status"] = "done"
    task["completed_on"] = today().isoformat()
    save_store(store)
    print("trellis job %d marked done on %s: %s" % (task["id"], task["completed_on"], task.get("title", "")))


def cmd_trellis_rm(args: argparse.Namespace, store: Dict[str, Any]) -> None:
    task = require_task(store, args.id)
    store["trellis_tasks"] = [item for item in store["trellis_tasks"] if item.get("id") != task["id"]]
    save_store(store)
    print("trellis job %d removed: %s (its id is never reused)" % (task["id"], task.get("title", "")))


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

class GrapevinedParser(argparse.ArgumentParser):
    """argparse that keeps the one-line error contract even for bad flags."""

    def error(self, message: str) -> NoReturn:  # type: ignore[override]
        error(message)


EPILOG = """\
quick start:
  python3 grapevined.py init --passphrase <phrase>
  export GRAPEVINED_PASSPHRASE=<phrase>
  python3 grapevined.py block add --name "North Ridge" --variety "Pinot Noir" --vines 480
  python3 grapevined.py yield log --block 1 --kg 1250 --date 2025-09-12
  python3 grapevined.py ripeness add --block 1 --brix 22.5 --ph 3.4 --date 2025-08-30
  python3 grapevined.py trellis add --block 1 --title "Replace wire row 3" --due 2025-10-01

every command reads the local passphrase from GRAPEVINED_PASSPHRASE and errors
go to stderr with a non-zero exit code, so the tool is safe to script.
the full season walkthrough on a scratch store:  bash demo.sh
"""


def _leaf(group: argparse.ArgumentParser, name: str, handler: Callable[..., None], help_text: str,
          description: str, epilog: str) -> argparse.ArgumentParser:
    parser = group.add_parser(
        name,
        help=help_text,
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(handler=handler)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = GrapevinedParser(
        prog=PROG,
        description="Grapevined %s - vineyard block, yield, ripeness and trellis tracker." % __version__,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="Grapevined %s" % __version__)
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    # -- init ------------------------------------------------------------
    init_parser = commands.add_parser(
        "init",
        help="create grapevined.json and set the local passphrase",
        description="Create the local store and store a salted PBKDF2-HMAC-SHA256 hash of the passphrase.",
        epilog="example:\n  python3 grapevined.py init --passphrase \"cellar door\"",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    init_parser.add_argument("--passphrase", required=True, metavar="PHRASE",
                             help="the passphrase that will protect every later command")
    init_parser.add_argument("--force", action="store_true",
                             help="replace an existing grapevined.json and destroy its records")
    init_parser.set_defaults(handler=cmd_init)

    # -- block -----------------------------------------------------------
    block = commands.add_parser(
        "block",
        help="register and inspect vineyard blocks",
        description="The blocks every other record points at.",
        epilog="examples:\n  python3 grapevined.py block add --name \"North Ridge\" --variety \"Pinot Noir\" --vines 480\n"
               "  python3 grapevined.py block list\n  python3 grapevined.py block show --id 1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    block_sub = block.add_subparsers(dest="subcommand", metavar="<subcommand>")
    add = _leaf(block_sub, "add", cmd_block_add, "register a block",
                "Register a vineyard block. Block names are unique (case-insensitive).",
                "example:\n  python3 grapevined.py block add --name \"North Ridge\" --variety \"Pinot Noir\" --vines 480 --rows 8 --planted-year 2016")
    add.add_argument("--name", required=True, help="block name, unique across the store")
    add.add_argument("--variety", required=True, help="planted variety, e.g. \"Pinot Noir\"")
    add.add_argument("--vines", type=int, default=None, help="vine count, used for kg/vine in yield report")
    add.add_argument("--rows", type=int, default=None, help="row count")
    add.add_argument("--planted-year", type=int, default=None, dest="planted_year", help="year the block was planted")
    _leaf(block_sub, "list", cmd_block_list, "list blocks", "List every registered block.",
          "example:\n  python3 grapevined.py block list")
    show = _leaf(block_sub, "show", cmd_block_show, "show one block with its yield and ripeness",
                 "Show one block, its logged yield per vintage and its latest ripeness sample.",
                 "example:\n  python3 grapevined.py block show --id 1")
    show.add_argument("--id", type=int, required=True, dest="id", help="block id from 'block list'")
    block.set_defaults(help_parser=block)

    # -- yield -----------------------------------------------------------
    yield_group = commands.add_parser(
        "yield",
        help="log harvested kilograms and roll them up",
        description="Harvest yield per block and vintage.",
        epilog="examples:\n  python3 grapevined.py yield log --block 1 --kg 1250 --date 2025-09-12\n"
               "  python3 grapevined.py yield report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    yield_sub = yield_group.add_subparsers(dest="subcommand", metavar="<subcommand>")
    log = _leaf(yield_sub, "log", cmd_yield_log, "log harvested kilograms for a block",
                "Log kilograms harvested. kg must be > 0 and the date must not be in the future.",
                "example:\n  python3 grapevined.py yield log --block 1 --kg 1250 --date 2025-09-12 --vintage 2025")
    log.add_argument("--block", type=int, required=True, help="block id from 'block list'")
    log.add_argument("--kg", type=float, required=True, help="kilograms harvested, greater than zero")
    log.add_argument("--date", required=True, metavar="YYYY-MM-DD", help="harvest date")
    log.add_argument("--vintage", type=int, default=None, help="vintage year (defaults to the year of --date)")
    log.add_argument("--notes", default=None, help="free-text note")
    _leaf(yield_sub, "report", cmd_yield_report, "totals per block and per vintage",
          "Kilograms per block, per-vintage subtotals and kg/vine where a vine count is known.",
          "example:\n  python3 grapevined.py yield report")
    yield_group.set_defaults(help_parser=yield_group)

    # -- ripeness --------------------------------------------------------
    ripeness = commands.add_parser(
        "ripeness",
        help="record Brix/pH/TA samples through the ripening window",
        description="Harvest ripeness samples per block.",
        epilog="examples:\n  python3 grapevined.py ripeness add --block 1 --brix 22.5 --ph 3.4 --ta 6.1 --date 2025-08-30\n"
               "  python3 grapevined.py ripeness list --block 1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ripeness_sub = ripeness.add_subparsers(dest="subcommand", metavar="<subcommand>")
    ripeness_add = _leaf(ripeness_sub, "add", cmd_ripeness_add, "record a ripeness sample",
                         "Brix must be greater than 0 and at most 40; pH must be between 0 and 14.",
                         "example:\n  python3 grapevined.py ripeness add --block 1 --brix 22.5 --ph 3.4 --date 2025-08-30")
    ripeness_add.add_argument("--block", type=int, required=True, help="block id from 'block list'")
    ripeness_add.add_argument("--brix", type=float, required=True, help="Brix, greater than 0 and at most 40")
    ripeness_add.add_argument("--ph", type=float, default=None, help="pH, between 0 and 14")
    ripeness_add.add_argument("--ta", type=float, default=None, help="titratable acidity in g/L")
    ripeness_add.add_argument("--date", required=True, metavar="YYYY-MM-DD", help="sampling date")
    ripeness_add.add_argument("--notes", default=None, help="free-text note")
    ripeness_list = _leaf(ripeness_sub, "list", cmd_ripeness_list, "list samples for a block",
                          "Samples in ascending date order with the newest marked latest.",
                          "example:\n  python3 grapevined.py ripeness list --block 1")
    ripeness_list.add_argument("--block", type=int, required=True, help="block id from 'block list'")
    ripeness.set_defaults(help_parser=ripeness)

    # -- trellis ---------------------------------------------------------
    trellis = commands.add_parser(
        "trellis",
        help="schedule and close trellis maintenance jobs",
        description="Trellis repair and maintenance jobs per block.",
        epilog="examples:\n  python3 grapevined.py trellis add --block 1 --title \"Replace wire row 3\" --due 2025-10-01\n"
               "  python3 grapevined.py trellis list\n  python3 grapevined.py trellis done --id 1\n"
               "  python3 grapevined.py trellis rm --id 1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    trellis_sub = trellis.add_subparsers(dest="subcommand", metavar="<subcommand>")
    trellis_add = _leaf(trellis_sub, "add", cmd_trellis_add, "schedule a trellis job",
                        "Schedule a maintenance job; --due must be in YYYY-MM-DD form.",
                        "example:\n  python3 grapevined.py trellis add --block 1 --title \"Replace wire row 3\" --due 2025-10-01")
    trellis_add.add_argument("--block", type=int, required=True, help="block id from 'block list'")
    trellis_add.add_argument("--title", required=True, help="short description of the job")
    trellis_add.add_argument("--due", required=True, metavar="YYYY-MM-DD", help="due date")
    _leaf(trellis_sub, "list", cmd_trellis_list, "list jobs with open/done status",
          "Every job with its due date, block, status and an overdue flag for open jobs past their due date.",
          "example:\n  python3 grapevined.py trellis list")
    trellis_done = _leaf(trellis_sub, "done", cmd_trellis_done, "close a job by id",
                         "Mark a job done and stamp today's date as its completion date.",
                         "example:\n  python3 grapevined.py trellis done --id 1")
    trellis_done.add_argument("--id", type=int, required=True, dest="id", help="job id from 'trellis list'")
    trellis_rm = _leaf(trellis_sub, "rm", cmd_trellis_rm, "delete a job by id",
                       "Delete a job by id. A deleted id is never handed out again.",
                       "example:\n  python3 grapevined.py trellis rm --id 1")
    trellis_rm.add_argument("--id", type=int, required=True, dest="id", help="job id from 'trellis list'")
    trellis.set_defaults(help_parser=trellis)

    return parser


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "handler", None)
    if handler is None:
        # Bare invocation, or a command group without a subcommand: usage only,
        # exit 0, and no passphrase needed.
        target = getattr(args, "help_parser", parser)
        target.print_help()
        return EXIT_OK

    if handler is cmd_init:
        handler(args)
        return EXIT_OK

    store = load_store()
    verify_passphrase(store)
    handler(args, store)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
