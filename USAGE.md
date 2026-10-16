# Using Grapevined

Everything below is run from the directory that holds `grapevined.json`, with

```sh
export GRAPEVINED_PASSPHRASE="your passphrase"      # Windows cmd: set GRAPEVINED_PASSPHRASE=your passphrase
```

in the shell. Output shown is exactly what the tool prints.

## 1. Start a season: the block registry

Blocks are the record every yield entry, ripeness sample and trellis job points
at, so register them first.

```sh
$ python3 grapevined.py block add --name "North Ridge" --variety "Pinot Noir" --vines 480 --rows 8 --planted-year 2016
block 1 added: North Ridge (Pinot Noir, 480 vines)
$ python3 grapevined.py block add --name "Creek Flat" --variety "Chardonnay" --vines 320
block 2 added: Creek Flat (Chardonnay, 320 vines)
$ python3 grapevined.py block list
id  name         variety     vines  rows
--  -----------  ----------  -----  ----
 1  North Ridge  Pinot Noir    480     8
 2  Creek Flat   Chardonnay    320     -
2 blocks
```

Block names are unique case-insensitively, so `--name "north ridge"` is refused
rather than creating a second block that looks the same:

```sh
$ python3 grapevined.py block add --name "north ridge" --variety "Pinot Noir"
error: a block named 'North Ridge' already exists (id 1)
```

`block show` is the one-screen summary you want before a pick decision - it
rolls the block's own records together:

```sh
$ python3 grapevined.py block show --id 1
block 1: North Ridge
  variety         Pinot Noir
  rows            8
  vines           480
  planted year    2016
  logged yield    1500 kg from 2 entries
  kg per vine     3.12
  vintage 2025    1500 kg
  latest ripeness 2025-08-30  Brix 22.5  pH 3.35  TA 6.6 g/L
  samples on file 2
```

If nothing has been recorded yet, `block show` says so and prints the command
that would fix it - no empty table with a bare heading.

## 2. Harvest yield tracker

`yield log` records kilograms for one block on one date. The vintage defaults to
the year of the date, so you only pass `--vintage` when a pick belongs to a
different vintage.

```sh
$ python3 grapevined.py yield log --block 1 --kg 1250 --date 2025-09-12 --notes "first pick, hand sorted"
yield 1 logged: 1250 kg for block 1 North Ridge on 2025-09-12 (vintage 2025)
$ python3 grapevined.py yield log --block 1 --kg 250 --date 2025-09-14
yield 2 logged: 250 kg for block 1 North Ridge on 2025-09-14 (vintage 2025)
$ python3 grapevined.py yield log --block 2 --kg 1610 --date 2025-09-18
yield 3 logged: 1610 kg for block 2 Creek Flat on 2025-09-18 (vintage 2025)
```

`yield report` is the roll-up: one row per block and vintage, kg/vine where the
block has a vine count, and a grand total.

```sh
$ python3 grapevined.py yield report
id  block        vintage  entries    kg  kg/vine
--  -----------  -------  -------  ----  -------
 1  North Ridge     2025        2  1500     3.12
 2  Creek Flat      2025        1  1610     5.03
total: 3110 kg from 3 entries across 2 blocks
```

What is refused, and why: `--kg 0`, `--kg -5` and a future `--date` (you cannot
have harvested tomorrow), plus any `--block` that is not registered. Each is one
line and stores nothing.

```sh
$ python3 grapevined.py yield log --block 1 --kg -5 --date 2025-09-12
error: kg must be greater than zero (got -5)
$ python3 grapevined.py yield log --block 1 --kg 100 --date 2025-12-31
error: the date cannot be in the future (got 2025-12-31)
$ python3 grapevined.py yield log --block 99 --kg 100 --date 2025-09-12
error: no block has that id: 99
```

## 3. Harvest ripeness log

Samples are logged as often as you walk the rows - Brix is required, pH and TA
are optional.

```sh
$ python3 grapevined.py ripeness add --block 1 --brix 19.8 --ph 3.10 --ta 8.4 --date 2025-08-12 --notes "veraison +2 weeks"
ripeness sample 1 stored: block 1 North Ridge on 2025-08-12 - Brix 19.8, pH 3.1
$ python3 grapevined.py ripeness add --block 1 --brix 22.5 --ph 3.35 --ta 6.6 --date 2025-08-30
ripeness sample 2 stored: block 1 North Ridge on 2025-08-30 - Brix 22.5, pH 3.35
```

`ripeness list --block N` is date-ascending regardless of the order you typed
the samples in, and marks the newest one:

```sh
$ python3 grapevined.py ripeness list --block 1
ripeness samples for block 1 North Ridge
id  date        brix    ph   ta  flag    note
--  ----------  ----  ----  ---  ------  -------------------
 1  2025-08-12  19.8   3.1  8.4          veraison +2 weeks
 2  2025-08-30  22.5  3.35  6.6  latest
2 samples, newest dated 2025-08-30
```

Ranges are checked before anything is written: Brix must be greater than 0 and
at most 40, pH between 0 and 14, TA greater than 0, and the date a real
`YYYY-MM-DD` that is not in the future.

```sh
$ python3 grapevined.py ripeness add --block 1 --brix 41 --date 2025-08-30
error: Brix must be at most 40 (got 41)
$ python3 grapevined.py ripeness add --block 1 --brix 22 --ph 15 --date 2025-08-30
error: pH must be between 0 and 14 (got 15)
$ python3 grapevined.py ripeness add --block 1 --brix 22 --date 30-08-2025
error: date must be in YYYY-MM-DD form (got '30-08-2025')
$ python3 grapevined.py ripeness add --block 7 --brix 22 --date 2025-08-30
error: no block has that id: 7
```

## 4. Trellis maintenance scheduler

```sh
$ python3 grapevined.py trellis add --block 1 --title "Replace trellis wire row 3" --due 2025-10-01
trellis job 1 scheduled: Replace trellis wire row 3 for block 1 North Ridge, due 2025-10-01
$ python3 grapevined.py trellis add --block 2 --title "Re-tension end post at row 12" --due 2025-09-20
trellis job 2 scheduled: Re-tension end post at row 12 for block 2 Creek Flat, due 2025-09-20
```

`trellis list` shows id, due date, status, block, completion date and an
`overdue` flag on open jobs whose due date has passed - the daily "what is
late?" view. Past due dates are accepted on purpose: you record work you
already owe, and the list tells you it is late.

```sh
$ python3 grapevined.py trellis list
id  due         status  block  block name   completed  flag     title
--  ----------  ------  -----  -----------  ---------  -------  -----------------------------
 1  2025-10-01  open        1  North Ridge  -                   Replace trellis wire row 3
 2  2025-09-20  open        2  Creek Flat   -          overdue  Re-tension end post at row 12
2 jobs, 2 open, 1 overdue
```

Closing and deleting job 1:

```sh
$ python3 grapevined.py trellis done --id 1
trellis job 1 marked done on 2025-09-24: Replace trellis wire row 3
$ python3 grapevined.py trellis rm --id 1
trellis job 1 removed: Replace trellis wire row 3 (its id is never reused)
```

A deleted id is never handed out again, so an id written on a shed whiteboard
can never silently point at a different job:

```sh
$ python3 grapevined.py trellis add --block 2 --title "Spray weeds under row 12" --due 2025-10-04
trellis job 3 scheduled: Spray weeds under row 12 for block 2 Creek Flat, due 2025-10-04
```

An unknown id, like every other rejection, prints one line and changes nothing:

```sh
$ python3 grapevined.py trellis rm --id 99
error: no trellis job has that id: 99
$ python3 grapevined.py trellis done --id 99
error: no trellis job has that id: 99
$ python3 grapevined.py trellis add --block 1 --title "Fix post" --due 01-10-2025
error: due date must be in YYYY-MM-DD form (got '01-10-2025')
```

## 5. Scripting it

Results go to stdout and errors to stderr with a non-zero exit code, so the tool
composes with the shell:

```sh
# kg per block as a flat table you can feed to awk: skip header and rule line
python3 grapevined.py yield report | tail -n +3

# refuse to continue if the store is locked or missing
python3 grapevined.py block list >/dev/null || { echo "cannot read the store"; exit 1; }
```

Exit code `0` means success; `2` means the command was rejected (bad input,
wrong or missing passphrase, missing or unreadable store). Never `0` on failure.

## 6. Housekeeping

- **Back up** by copying `grapevined.json`; there is nothing else to copy.
- **Move machines** by copying the same file and exporting the same passphrase.
- **Inspect** it with any JSON tool - it is flat, indented JSON with `version: 1`.
- **Start over** with `python3 grapevined.py init --force --passphrase <phrase>`,
  which replaces the store and erases its records.
- **Hand-edited** stores are read defensively: a missing list is repaired on
  load, an unknown `version` or invalid JSON is refused with one line rather
  than overwritten.

## 7. Getting help

```sh
python3 grapevined.py --help              # command groups, quick start, examples
python3 grapevined.py trellis --help      # subcommands and the overdue rules
python3 grapevined.py trellis add --help  # every flag, with an example
```

`--help` works with no store and no passphrase, and exits `0`.
