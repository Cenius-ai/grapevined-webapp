#!/usr/bin/env bash
# Grapevined demo: walks a whole season (blocks, yield, ripeness, trellis) against
# a scratch store in a throwaway directory. Non-interactive, no network, no config.
# Runs under bash or a POSIX sh:  bash demo.sh   /   sh demo.sh
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"
CLI="$ROOT/grapevined.py"

DEMO_DIR="$(mktemp -d "${TMPDIR:-/tmp}/grapevined-demo.XXXXXX")"
trap 'rm -rf "$DEMO_DIR"' EXIT
cd "$DEMO_DIR"

# Standard demo credential. Grapevined is a single-operator tool, so the local
# passphrase is the only credential: use `cenius` (demo identity: cenius@cenius.ai).
DEMO_PASSPHRASE="${GRAPEVINED_PASSPHRASE:-cenius}"
GRAPEVINED_PASSPHRASE="$DEMO_PASSPHRASE"
export GRAPEVINED_PASSPHRASE

day() {
    "$PYTHON" -c 'import datetime,sys; print((datetime.date.today()+datetime.timedelta(days=int(sys.argv[1]))).isoformat())' "$1"
}

step() {
    printf '\n== %s\n' "$1"
}

run() {
    printf '\n$ python3 grapevined.py %s\n' "$*"
    "$PYTHON" "$CLI" "$@"
}

printf 'Grapevined demo - vineyard block, yield, ripeness and trellis tracker\n'
printf 'scratch store  : %s/grapevined.json\n' "$DEMO_DIR"
printf 'demo passphrase: %s   (standard demo credential: cenius@cenius.ai / cenius)\n' "$DEMO_PASSPHRASE"

step "help is first-class and needs no store and no passphrase"
run --help

step "init - create the store; only a salted hash of the passphrase is written"
run init --passphrase "$DEMO_PASSPHRASE"

step "register the blocks every other record points at"
run block add --name "North Ridge" --variety "Pinot Noir" --vines 480 --rows 8 --planted-year 2016
run block add --name "Creek Flat" --variety "Chardonnay" --vines 320 --rows 6 --planted-year 2019
run block add --name "Old Barn" --variety "Shiraz" --vines 210 --rows 4 --planted-year 2008
run block list

step "log the harvest, block by block"
run yield log --block 1 --kg 1250 --date "$(day -34)" --notes "first pick, hand sorted"
run yield log --block 1 --kg 380 --date "$(day -21)" --notes "second pass"
run yield log --block 2 --kg 1610 --date "$(day -28)"
run yield log --block 3 --kg 640 --date "$(day -12)"

step "yield report - totals, vintage subtotals and kg per vine"
run yield report

step "ripeness samples through the ripening window"
run ripeness add --block 1 --brix 19.8 --ph 3.10 --ta 8.4 --date "$(day -30)" --notes "veraison plus two weeks"
run ripeness add --block 1 --brix 22.5 --ph 3.35 --ta 6.6 --date "$(day -16)"
run ripeness add --block 1 --brix 24.1 --ph 3.42 --ta 5.9 --date "$(day -3)" --notes "flavour ripe, pick Thursday"
run ripeness add --block 2 --brix 18.2 --ph 3.05 --ta 9.1 --date "$(day -18)"
run ripeness list --block 1

step "schedule trellis work, then read it back with late jobs flagged"
run trellis add --block 1 --title "Replace trellis wire row 3" --due "$(day -2)"
run trellis add --block 2 --title "Re-tension end post at row 12" --due "$(day 9)"
run trellis add --block 3 --title "Repair hail net over rows 1-2" --due "$(day 21)"
run trellis list

step "close one job and delete another; ids are never recycled"
run trellis done --id 1
run trellis rm --id 3
run trellis list

step "block show - one block's yield and latest ripeness together"
run block show --id 1

step "one malformed command: one line on stderr, non-zero exit, store untouched"
STORE_BEFORE="$(cksum grapevined.json)"
set +e
run yield log --block 1 --kg -5 --date "$(day -5)"
STATUS=$?
set -e
STORE_AFTER="$(cksum grapevined.json)"
printf '   -> exit code %s, store unchanged: %s\n' "$STATUS" "$([ "$STORE_BEFORE" = "$STORE_AFTER" ] && echo yes || echo NO)"

step "the passphrase is never written to disk in plain text"
if grep -q "$DEMO_PASSPHRASE" grapevined.json; then
    printf '   -> FAIL: plaintext passphrase found in the store\n'
    exit 1
fi
printf '   -> plaintext passphrase found in grapevined.json: no\n'
"$PYTHON" -c 'import json; d=json.load(open("grapevined.json")); a=d["auth"]; print("   -> stored: %d PBKDF2-HMAC-SHA256 iterations, salt %s..." % (a["iterations"], a["salt"][:8])); print("   -> records: %d blocks, %d yield entries, %d ripeness samples, %d trellis jobs" % (len(d["blocks"]), len(d["yield_events"]), len(d["ripeness_samples"]), len(d["trellis_tasks"])))'

printf '\nDemo complete. Scratch store removed from %s\n' "$DEMO_DIR"
