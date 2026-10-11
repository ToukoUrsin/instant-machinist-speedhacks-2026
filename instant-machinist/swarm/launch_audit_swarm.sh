#!/usr/bin/env bash
set -u
repo="$(pwd)"
out="$repo/swarm/runs"
items=(
"audit parser G41/G42 cutter compensation semantics and propose tests"
"audit parser M98/M99 subprogram semantics and propose tests"
"audit parser G68 rotation and coordinate transforms"
"audit parser G52/G54.1 work offsets"
"audit parser inch/metric unit switching"
"audit parser R arc edge cases and full circles"
"audit parser comments checksums sequence numbers"
"audit parser modal state resets and tool changes"
"audit parser scientific notation and signed words"
"audit parser malformed input error reporting"
"audit stock finer cell accuracy tradeoffs"
"audit stock ball endmill geometry"
"audit stock bull endmill geometry"
"audit stock chamfer tool geometry"
"audit stock spot drill geometry"
"audit stock taper tool geometry"
"audit stock boundary clipping and z conventions"
"audit stock performance vectorization opportunities"
"audit checks holder collision detection"
"audit checks shank collision detection"
"audit checks rapid into stock detection"
"audit checks plunge detection"
"audit checks fixture collision"
"audit checks flute length violation"
"audit checks feeds and speeds sanity"
"audit checks chip load calculation"
"audit checks false positive behavior"
"audit cycle acceleration deceleration model"
"audit cycle constant feed baseline"
"audit cycle rapid traverse timing"
"audit cycle corner blending"
"audit cycle metric units"
"audit run API backward compatibility"
"audit report json schema and stable keys"
"audit CLI exit codes and output"
"audit fuzz property corpus design"
"audit generated 2.5D fixture strategy"
"audit seeded gouge ground truth fixtures"
"audit seeded leftover ground truth fixtures"
"audit seeded rapid collision fixtures"
"audit parser success benchmark design"
"audit runtime benchmark design"
"audit precision recall benchmark design"
"audit simulator determinism"
"audit simulator memory behavior"
"audit tests missing boundary cases"
"audit documentation contract gaps"
"audit native program compatibility"
"audit Fusion posted program compatibility"
"audit test isolation and fixture hygiene"
"audit highest impact safe improvement recommendation"
)
run_one() {
  id="$1"; item="$2"; d="$out/$id"; mkdir -p "$d"
  start=$(date +%s)
  prompt="You are audit agent $id for Instant Machinist. $item. Read the simulator and tests under this repository. Do not edit any files, do not use network or browsers, and do not touch lead-owned files. Return a concise report with concrete findings, file paths, and 1-3 acceptance tests. This is an audit run whose output will be saved."
  timeout 150 codex exec --ephemeral --json --model gpt-6.1-sol --sandbox read-only --dangerously-bypass-hook-trust -C "$repo" "$prompt" > "$d/transcript.jsonl" 2>&1
  rc=$?
  end=$(date +%s)
  python3 - "$d" "$id" "$item" "$rc" "$start" "$end" <<'PY'
import json,sys, pathlib
p=pathlib.Path(sys.argv[1]); rec={"agent_id":sys.argv[2],"item":sys.argv[3],"exit_code":int(sys.argv[4]),"started_epoch":int(sys.argv[5]),"ended_epoch":int(sys.argv[6]),"wall_s":int(sys.argv[6])-int(sys.argv[5]),"transcript":"transcript.jsonl"}
(p/"run.json").write_text(json.dumps(rec,indent=2)+"\n")
PY
}
export -f run_one
printf '%s\n' "${items[@]}" | nl -w2 -s' ' | awk '{id=$1; $1=""; sub(/^ /,""); print id"\t"$0}' | xargs -P 8 -n 1 bash -c 'line="$0"; id="${line%%$'"'\t'"'*}"; item="${line#*$'"'\t'"'}"; run_one "audit-$id" "$item"'
