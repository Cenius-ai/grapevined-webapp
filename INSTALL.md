# Installing Grapevined

## 1. Prerequisites (you install these, not the script)

| Requirement | Why | Check |
| --- | --- | --- |
| Python 3.9 or newer | Grapevined is a Python program (tested on 3.11) | `python3 --version` |
| POSIX shell or Windows `cmd` | to run the commands | `sh --version` / `cmd /c ver` |

Nothing else: no compiler, no database engine, no service, no network at
runtime. `install.sh` installs **project-level** dependencies only and never
calls `sudo`, `apt-get`, `brew` or any other system package manager - install
Python itself first if `python3 --version` fails.

## 2. Install

```sh
bash install.sh
```

The script is idempotent, safe to re-run, and it **exits** at the end - it never
starts Grapevined or anything else in the foreground. In order it:

1. refreshes `pip`, `setuptools` and `wheel` (an offline machine only prints a note)
2. installs `requirements.txt` - the declared, deliberately empty runtime dependency list
3. optionally installs the `grapevined` console command via `pip install -e .`; if that is skipped, run the tool as `python3 grapevined.py`
4. installs the pinned test runner only when `pytest` is not already importable
5. runs a self-check (`import grapevined` and `grapevined.py --version`) so a broken environment fails at install time

Environment variables for the install step: `PYTHON` (default `python3`). No
`.env` file exists in a fresh checkout and none is needed - the tool reads a
passphrase only when you run it, and you supply that with `--passphrase` at
`init` time.

## 3. Create your store

```sh
python3 grapevined.py init --passphrase "your passphrase"
export GRAPEVINED_PASSPHRASE="your passphrase"     # Windows cmd: set GRAPEVINED_PASSPHRASE=your passphrase
```

`init` writes `grapevined.json` in the current directory. It refuses to
overwrite an existing store unless you pass `--force` (which destroys the
records in it).

`GRAPEVINED_PASSPHRASE` is the only environment variable Grapevined reads; see
`.env.example`. Its shape is a plain string, so `export
GRAPEVINED_PASSPHRASE=cenius` (the documented demo credential) is valid with no
edits. There is no default value in code on purpose: the passphrase is chosen by
you at `init` time and must match the hash in the store.

## 4. Run

There is no server and no port. Start the tool on its own:

```sh
python3 grapevined.py block list
python3 grapevined.py yield report
```

Or, if the optional console command was installed:

```sh
grapevined block list
```

To see the whole product exercised end to end on a scratch store in a temp
directory (creates it, runs every command, deletes it again):

```sh
bash demo.sh
```

## 5. Test

```sh
python3 -m pytest
```

The suite needs only the pinned `pytest` from `requirements-dev.txt`. It runs
offline, asks for no input, and creates its own fixture data in temporary
directories.

## 6. Uninstall

```sh
rm -f grapevined.json          # your records - back this up first if you want them
python3 -m pip uninstall grapevined   # only if you installed the console command
```

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `error: passphrase required - set the GRAPEVINED_PASSPHRASE environment variable` | export the passphrase you chose at `init` time in this shell |
| `error: passphrase not accepted` | the exported value differs from the one hashed into `grapevined.json` |
| `error: no store found here - run: grapevined.py init --passphrase <phrase> first` | you are in a different directory than the one holding `grapevined.json`; `cd` to it |
| `error: grapevined.json already exists - re-run with --force` | a store is already there; use `--force` only if you mean to erase its records |
| `error: ... has schema version N, this build expects 1` | the file was written by a different version; keep a copy and use the matching release |
| `python3: command not found` | install Python 3.9+ and re-run `bash install.sh` |
