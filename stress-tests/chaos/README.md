# chaos — adversarial stress tests

Deliberately try to break `px` by feeding it pathological input and interrupting it at the worst
moment. Each harness targets an **invariant that must always hold**; a failure is a finding, not a
flake. Findings are logged in `../../../engineering-docs/notes/px-cli-stress-test-bugs.md`.

| Harness | Invariant under attack | Needs account? |
|---|---|---|
| `01-offline-fuzzer.sh` | Any input → clean exit (no traceback, no hang, no signal death) | No |
| `02-kill-mid-apply.sh` | Interrupted `apply` + retry → exactly one project (no duplicate) | Yes |
| `03-state-corruption.sh` | Corrupt/lost context state → no duplicate context notes | Yes |

## Run

```bash
# Offline — safe, no token, run this first:
./01-offline-fuzzer.sh                 # optional: ./01-offline-fuzzer.sh <timeout_secs>

# Account harnesses (they create + delete their own throwaway projects):
export JARVISPY_URL="https://api.prometheux.ai/jarvispy/prometheux/staging"
export PMTX_TOKEN="<your JWT>"
./02-kill-mid-apply.sh                 # optional: ./02-kill-mid-apply.sh <attempts>
./03-state-corruption.sh
```

Each account harness tears down every project it created (by id). If a run is itself killed,
clean up leftovers with `px pull` (to list) + `px delete <id> -y`.

## Known findings so far (offline fuzzer)

- **`px validate` crashes with a traceback on deeply-nested YAML** (`RecursionError` from PyYAML).
- **`px validate` crashes with a traceback on invalid UTF-8** (`UnicodeDecodeError` in
  `parsing.py` `read_text`). Both should be clean `FAIL`s. See the bug log (#22, #23).
