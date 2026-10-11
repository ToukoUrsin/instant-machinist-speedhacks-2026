#!/usr/bin/env bash
# Headless Sparta Worlds run of a quote-agent version against one mission.
#   tools/run.sh <v1|v2> <mission-id> <normal|interruption|crash|crash-late|double> <evidence-name> [runs]
# ANTHROPIC_API_KEY is injected from the environment into this one process tree only (never written to disk).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HERE/.node/bin:$PATH" XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"
ver=$1 mission=$2 scen=$3 name=$4 runs=${5:-1}
agent="../../agent/quote-agent.mjs"; [ "$ver" = v1 ] && agent="../../agent/v1/quote-agent.mjs"
args=(--project . --mission "$mission" --timeout 300 --evidence "$HERE/evidence/$name.json")
[ "$scen" = interruption ] && args+=(--scenario interruption)
cmd=(node "$agent")
# crash: worker killed right after its 2nd write commits, job redelivered. double: trigger fires twice.
[ "$scen" = crash ] && cmd=(node ../../tools/redeliver.mjs crash 2 "$agent")
[ "$scen" = crash-late ] && cmd=(node ../../tools/redeliver.mjs crash 6 "$agent")   # after the draft, before the reply
[ "$scen" = double ] && cmd=(node ../../tools/redeliver.mjs double "$agent")
[ "$runs" -gt 1 ] && args+=(--runs "$runs")
mkdir -p "$HERE/evidence/traces"
# The starter's generated model limits (.env.example): 12 steps, 1024 tokens/turn, 120 s.
export WORLDS_AGENT_MAX_STEPS=12 WORLDS_AGENT_MAX_TOKENS=1024 WORLDS_AGENT_TIMEOUT_MS=120000
export SPARTA_TRACE="$HERE/evidence/traces/$name.jsonl" WORLDS_MODEL="${WORLDS_MODEL:-claude-opus-5-5}"
cd "$HERE/projects/shop-quote"
npx --no-install worlds starters run "${args[@]}" -- "${cmd[@]}"
