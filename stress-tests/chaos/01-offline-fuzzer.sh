#!/usr/bin/env bash
#
# Chaos #2 — offline fuzzer for `px validate`.
#
# Feeds pathological workspaces to `px validate` (fully offline) and checks the
# one invariant that must ALWAYS hold: no matter how broken the input, px exits
# cleanly (a normal PASS/FAIL) — never an unhandled Python traceback, never a
# hang, never a signal death. A crash/hang/traceback on any case is a finding.
#
# No account or token needed. Safe to run first.
#
# Usage:  ./01-offline-fuzzer.sh [TIMEOUT_SECS]   (default 15)

TIMEOUT="${1:-15}"
PX="${PX:-px}"
command -v "$PX" >/dev/null 2>&1 || { echo "FATAL: '$PX' not found (set PX=)."; exit 2; }
if [[ -t 1 ]]; then R=$'\033[31m'; G=$'\033[32m'; B=$'\033[1m'; Z=$'\033[0m'; else R=; G=; B=; Z=; fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

# Portable timeout: run "$@", kill after $TIMEOUT. Sets RC (124 = timed out) and OUT.
guard() {
  local out="$TMP/out.$$"; : > "$out"
  ( "$@" >"$out" 2>&1 ) & local pid=$!
  ( sleep "$TIMEOUT"; kill -9 "$pid" 2>/dev/null ) & local killer=$!
  wait "$pid" 2>/dev/null; RC=$?
  if kill -0 "$pid" 2>/dev/null; then RC=124; fi
  kill "$killer" 2>/dev/null; wait "$killer" 2>/dev/null || true
  # RC 137 (128+9) means our killer fired → treat as timeout/hang.
  [[ "$RC" == 137 ]] && RC=124
  OUT="$(cat "$out")"
}

# A case PASSES iff px exited cleanly (not a signal/hang) and printed no traceback.
check() {
  local name="$1" dir="$2"
  guard "$PX" validate "$dir"
  local bad=""
  [[ "$RC" == 124 ]] && bad="HANG/timeout (${TIMEOUT}s)"
  [[ "$RC" -ge 130 && "$RC" != 124 ]] && bad="signal death (rc=$RC)"
  grep -q "Traceback (most recent call last)" <<<"$OUT" && bad="unhandled traceback"
  if [[ -n "$bad" ]]; then
    FAIL=$((FAIL+1)); printf '  %sBREAK%s %-22s %s\n' "$R" "$Z" "$name" "$bad"
    printf '%s\n' "$OUT" | sed 's/^/        /' | head -6
  else
    PASS=$((PASS+1)); printf '  %sok%s    %-22s (clean exit rc=%s)\n' "$G" "$Z" "$name" "$RC"
  fi
}

# Minimal valid-ish workspace at $1 (workspace + one project + empty concepts).
mkbase() {
  local d="$1"
  mkdir -p "$d/projects/p/concepts"
  printf 'schemaVersion: 1\nworkspace:\n  name: fuzz\nprojects:\n  - ./projects/p\n' > "$d/prometheux.workspace.yaml"
  printf 'schemaVersion: 1\nproject:\n  name: P\n  scope: user\nconcepts: ./concepts\n' > "$d/projects/p/prometheux.yaml"
}
concept() {  # concept <dir> <predicate> <body> <metaExtra>
  local d="$1" p="$2"
  printf '%s\n' "$3" > "$d/projects/p/concepts/$p.vadalog"
  { printf 'conceptType: logic\noutputPredicate: %s\n' "$p"; [[ -n "${4:-}" ]] && printf '%s\n' "$4"; } > "$d/projects/p/concepts/$p.meta.yaml"
}

printf '%sOffline fuzzer — px validate must exit cleanly on every input%s\n' "$B" "$Z"
printf 'timeout=%ss  px=%s\n\n' "$TIMEOUT" "$PX"

# 0. baseline: a clean workspace must PASS
d="$TMP/c0"; mkbase "$d"; concept "$d" ok "ok(X) :- src(X)." ; check "baseline-clean" "$d"

# 1. YAML alias-expansion bomb (bounded ~10^6) in the project manifest
d="$TMP/c1"; mkbase "$d"
{
  echo 'schemaVersion: 1'
  echo 'a: &a ["x","x","x","x","x","x","x","x","x","x"]'
  echo 'b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a,*a]'
  echo 'c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b,*b]'
  echo 'd: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c,*c]'
  echo 'e: &e [*d,*d,*d,*d,*d,*d,*d,*d,*d,*d]'
  echo 'project:'
  echo '  name: bomb'
  echo '  scope: user'
  echo '  boom: [*e,*e,*e,*e,*e,*e,*e,*e,*e,*e]'
  echo 'concepts: ./concepts'
} > "$d/projects/p/prometheux.yaml"
check "yaml-alias-bomb" "$d"

# 2. deeply nested YAML (recursion) in a concept meta
d="$TMP/c2"; mkbase "$d"
printf 'ok(X) :- src(X).\n' > "$d/projects/p/concepts/ok.vadalog"
{ printf 'conceptType: logic\noutputPredicate: ok\ndeep: '; printf '[%.0s' $(seq 1 4000); printf ']%.0s' $(seq 1 4000); printf '\n'; } > "$d/projects/p/concepts/ok.meta.yaml"
check "deep-nested-yaml" "$d"

# 3. unicode / emoji predicate + filename
d="$TMP/c3"; mkbase "$d"; concept "$d" 'café_日本_🐒' 'café_日本_🐒(X) :- src(X).'
check "unicode-emoji-names" "$d"

# 4. absurdly long predicate/filename
d="$TMP/c4"; mkbase "$d"; long="$(printf 'a%.0s' $(seq 1 300))"
concept "$d" "$long" "$long(X) :- src(X)." || true
check "1000-char-name" "$d"

# 5. symlink loop inside the workspace
d="$TMP/c5"; mkbase "$d"; concept "$d" ok "ok(X) :- src(X)."
ln -s "$d/projects/p/concepts" "$d/projects/p/concepts/loop" 2>/dev/null || true
check "symlink-loop" "$d"

# 6. huge concept body (~15MB)
d="$TMP/c6"; mkbase "$d"
yes 'huge(X) :- src(X).' 2>/dev/null | head -n 600000 > "$d/projects/p/concepts/huge.vadalog" || true
printf 'conceptType: logic\noutputPredicate: huge\n' > "$d/projects/p/concepts/huge.meta.yaml"
check "huge-15MB-body" "$d"

# 7. malformed YAML meta (tab + unclosed quote)
d="$TMP/c7"; mkbase "$d"
printf 'ok(X) :- src(X).\n' > "$d/projects/p/concepts/ok.vadalog"
printf 'conceptType: logic\n\toutputPredicate: "unclosed\n' > "$d/projects/p/concepts/ok.meta.yaml"
check "malformed-yaml" "$d"

# 8. duplicate output predicate across two concepts
d="$TMP/c8"; mkbase "$d"; concept "$d" a "dup(X) :- src(X)." "outputPredicate: dup"; concept "$d" b "dup(Y) :- src(Y)." "outputPredicate: dup"
check "duplicate-output-pred" "$d"

# 9. a concept "file" that is actually a directory
d="$TMP/c9"; mkbase "$d"; mkdir -p "$d/projects/p/concepts/weird.vadalog"
check "dir-named-like-file" "$d"

# 10. invalid UTF-8 bytes in a meta file
d="$TMP/c10"; mkbase "$d"; printf 'ok(X) :- src(X).\n' > "$d/projects/p/concepts/ok.vadalog"
printf 'conceptType: logic\noutputPredicate: ok\nx: \xff\xfe\xc3\x28\n' > "$d/projects/p/concepts/ok.meta.yaml"
check "invalid-utf8-meta" "$d"

# 11. concept dependency cycle A <-> B
d="$TMP/c11"; mkbase "$d"; concept "$d" a "a(X) :- b(X)."; concept "$d" b "b(X) :- a(X)."
check "dependency-cycle" "$d"

# 12. hostile manifest types (id/scope wrong shapes)
d="$TMP/c12"; mkbase "$d"
printf 'schemaVersion: 1\nproject:\n  id: []\n  name: 123\n  scope: 7\nconcepts: ./concepts\n' > "$d/projects/p/prometheux.yaml"
check "hostile-manifest-types" "$d"

echo
printf '%s────────────────────────────────────────%s\n' "$B" "$Z"
if [[ "$FAIL" -eq 0 ]]; then
  printf '%sFUZZER: all %d cases exited cleanly%s\n' "$G" "$((PASS+FAIL))" "$Z"; exit 0
else
  printf '%sFUZZER: %d/%d case(s) BROKE the clean-exit invariant%s\n' "$R" "$FAIL" "$((PASS+FAIL))" "$Z"; exit 1
fi
