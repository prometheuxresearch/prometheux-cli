#!/usr/bin/env bash
#
# gen-notes.sh — every N seconds, drop a new markdown file full of random words
# into a folder. Pair with watch-push.sh, which pushes each new file to a
# project's context layer as a note.
#
# Usage:
#   ./gen-notes.sh [DIR] [INTERVAL_SECS] [WORDS_PER_FILE]
# Defaults: DIR = ./workspace/projects/ctx/context, INTERVAL = 10, WORDS = 40
#
# Files are NOT deleted — inspect them to compare against the platform. Ctrl-C to stop.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${1:-$HERE/workspace/projects/ctx/context}"
INTERVAL="${2:-10}"
NWORDS="${3:-40}"
WORDS_SRC="/usr/share/dict/words"

mkdir -p "$DIR"
echo "Generating a note every ${INTERVAL}s into:"
echo "  $DIR"
echo "(Ctrl-C to stop; files are kept for you to compare.)"
echo

random_body() {
  if [[ -r "$WORDS_SRC" ]]; then
    awk -v seed="$1" -v n="$NWORDS" '
      BEGIN { srand(seed) }
      { a[NR] = $0 }
      END {
        for (i = 0; i < n; i++) {
          printf "%s ", a[int(rand() * NR) + 1]
          if ((i + 1) % 12 == 0) printf "\n"
        }
        printf "\n"
      }' "$WORDS_SRC"
  else
    local out="" i
    for ((i = 0; i < NWORDS; i++)); do out+="w${RANDOM} "; done
    printf '%s\n' "$out"
  fi
}

while true; do
  ts="$(date +%Y%m%d-%H%M%S)"
  seed="$(date +%s)${RANDOM}"
  file="$DIR/note-${ts}-${RANDOM}.md"
  {
    echo "# Note ${ts}"
    echo
    random_body "$seed"
  } > "$file"
  echo "[$(date +%H:%M:%S)] wrote $(basename "$file")"
  sleep "$INTERVAL"
done
