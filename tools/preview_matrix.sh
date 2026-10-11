#!/usr/bin/env bash
# Run a pipeline's preview matrix: one `nextflow run -preview -with-dag` per row
# of a runs file. -preview builds the workflow graph and executes nothing (no
# containers, no tasks); each run takes seconds.
#
#   bash preview_matrix.sh [-j N] PIPELINE RUNS.tsv [OUTDIR] [-- EXTRA NEXTFLOW ARGS]
#
#   -j N       run N previews at once (default 1). Each runs in its own launch
#              folder under OUTDIR/launch/, so Nextflow's lock and history
#              files do not collide.
#   PIPELINE   what `nextflow run` takes: nf-core/fetchngs, or a local main.nf
#              (give a local script as an absolute path)
#   RUNS.tsv   one run per line: <name><TAB><args>. Blank lines and lines
#              starting with # are skipped; anything after a second tab is a
#              note and ignored.
#   OUTDIR     where the DOT files and logs go (default: dags)
#   after --   arguments added to every run, e.g. -r 1.13.0 -profile test
#
# Resumable: a run whose DOT file already exists and is not empty is skipped,
# so a batch can be interrupted and started again, and batches from
# tools/adaptive.py can all share one OUTDIR. Every run made is appended to
# OUTDIR/runs.tsv as <name> <ok|FAILED> <args> <seconds>, which is what
# tools/adaptive.py and tools/generate.py read.
#
# A run that fails is recorded and the matrix carries on: a failed run is a
# finding (an unguarded file(params.x), say), not a reason to stop. A run that
# takes longer than PREVIEW_TIMEOUT seconds (default 600) is stopped and
# counted as failed.
set -uo pipefail

JOBS=1
if [ "${1:-}" = "-j" ]; then JOBS=$2; shift 2; fi
[ $# -ge 2 ] || { sed -n '2,28p' "$0"; exit 2; }
PIPELINE=$1; RUNS=$2; shift 2
OUT=dags
if [ $# -gt 0 ] && [ "$1" != "--" ]; then OUT=$1; shift; fi
[ $# -gt 0 ] && [ "$1" = "--" ] && shift
COMMON=("$@")

mkdir -p "$OUT/launch"
OUT=$(cd "$OUT" && pwd)
touch "$OUT/runs.tsv"

one() {                                   # $1 name, $2 args
  local name=$1 args=$2 dir="$OUT/launch/$1" start status empties=()
  mkdir -p "$dir"
  # Nextflow reads `--param ''` as true, so an empty string cannot be passed on
  # the command line, and nf-schema rejects an empty string for a path. Both
  # go through a params file instead, where JSON keeps the type:
  #   --param ''    -> "param": ""     (a string that is empty: fetchngs' filter { x })
  #   --param null  -> "param": null   (not given at all: unsetting a path)
  while [[ $args =~ (^|[[:space:]])--([A-Za-z0-9_]+)[[:space:]]+(\'\'|null)([[:space:]]|$) ]]; do
    if [ "${BASH_REMATCH[3]}" = "null" ]; then
      empties+=("\"${BASH_REMATCH[2]}\": null")
      args=${args/"--${BASH_REMATCH[2]} null"/}
    else
      empties+=("\"${BASH_REMATCH[2]}\": \"\"")
      args=${args/"--${BASH_REMATCH[2]} ''"/}
    fi
  done
  if [ ${#empties[@]} -gt 0 ]; then
    { printf '{'; local i; for i in "${!empties[@]}"; do [ "$i" -gt 0 ] && printf ', '; printf '%s' "${empties[$i]}"; done; printf '}\n'; } > "$dir/empty.params.json"
    args="-params-file $dir/empty.params.json $args"
  fi
  start=$(date +%s)
  # Previews run as background jobs, and Nextflow runs `stty -echo < /dev/tty`.
  # A background job that touches the controlling terminal is stopped by the
  # shell (SIGTTOU): it freezes with no error, holding ~1 GB, which is what
  # the rnaseq "stalls" were. setsid gives each preview a session of its own
  # with no controlling terminal, so /dev/tty cannot be opened and nothing can
  # freeze; the console log is off as well. A run that still hangs is stopped
  # after PREVIEW_TIMEOUT seconds and recorded as failed.
  local detach=""
  command -v setsid > /dev/null && detach="setsid -w"
  # shellcheck disable=SC2086  # args is deliberately word-split
  if (cd "$dir" && NXF_ANSI_LOG=false eval $detach timeout "${PREVIEW_TIMEOUT:-600}" nextflow -log .nextflow.log run "$PIPELINE" "${COMMON[@]@Q}" -ansi-log false -preview -with-dag "$OUT/$name.dot" --outdir preview_out $args) \
       < /dev/null > "$OUT/$name.log" 2>&1 && [ -s "$OUT/$name.dot" ]; then
    status=ok
  else
    status=FAILED
  fi
  printf '%s\t%s\t%s\t%s\n' "$name" "$status" "$2" "$(( $(date +%s) - start ))" >> "$OUT/runs.tsv"
  printf '   %-40s %s\n' "$name" "$status"
}

todo=0; skipped=0
while IFS=$'\t' read -r name args _ || [ -n "$name" ]; do
  [ -z "$name" ] && continue
  case "$name" in \#*) continue ;; esac
  if [ -s "$OUT/$name.dot" ] && grep -q "^$name	ok	" "$OUT/runs.tsv"; then
    skipped=$((skipped + 1)); continue
  fi
  while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n; done
  one "$name" "$args" &
  todo=$((todo + 1))
done < "$RUNS"
wait

# count each run's latest attempt only (a rerun replaces an earlier failure)
latest=$(awk -F'\t' '{s[$1]=$2} END {for (k in s) print s[k]}' "$OUT/runs.tsv")
ok=$(grep -cx ok <<< "$latest")
failed=$(grep -cx FAILED <<< "$latest")
echo
echo "$todo run now, $skipped already done. In $OUT: $ok ok, $failed failed (runs.tsv has every run)."
