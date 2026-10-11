#!/bin/bash
# Full product-segment build from a pipeline run.
#   demo/build_segment.sh <run_dir> <part_dir> "<customer>" "<title>" [model_png]
# Needs out/demo/vo/{solution,result}.mp3 + .words.json (demo/vo/make_vo.py) and the run's simulation.mp4.
set -euo pipefail
REPO=instant-machinist
cd "$REPO"
RUN=$1; PART=$2; CUST=$3; TITLE=$4; MODEL=${5:-}
python3 demo/ui/build_data.py "$RUN" "$PART" --customer "$CUST" --title "$TITLE" ${MODEL:+--model "$MODEL"}
SIM=$RUN/simulation.mp4
SIMD=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SIM")
VO=out/demo/vo
eval "$(python3 - "$VO" "$SIMD" <<'EOF'
import json, sys
vo, simd = sys.argv[1], float(sys.argv[2])
r = json.load(open(f"{vo}/result.words.json"))
t = lambda w: next(x[1] for x in r if x[0].lower().startswith(w))
VO2 = 32.5
X1 = round(VO2 + t("here's") - 0.65, 2)          # cut to simulation just before "Here's the simulation"
RES = round(VO2 + t("plus") - 0.2, 2)              # in-app result card lands on "plus the Fusion file"
CUT = round(t("that's") - 0.3, 2)                   # "That's N percent..." moves onto the end card
print(f"VO2={VO2} X1={X1} RES={RES} CUT={CUT} UIDUR={round(X1 + 0.8, 2)} SIMD={simd}")
EOF
)"
echo "VO2=$VO2 X1=$X1 RES=$RES CUT=$CUT UIDUR=$UIDUR SIMD=$SIMD"
cd demo
node record.mjs ui/index.html ../out/demo/seg/ui.mp4 "result=$RES&dur=$UIDUR"
node record.mjs cards/end.html ../out/demo/seg/end.mp4 "nofade&dur=8"
cd "$REPO/out/demo"
rm -rf build && mkdir build
cp seg/ui.mp4 seg/end.mp4 build/; cp "$REPO/$SIM" build/sim.mp4; cp vo/solution.mp3 vo/result.mp3 music/bed.mp3 build/
cp "$REPO/demo/assemble.sh" build/
cd build
drun -- env X1=$X1 VO2=$VO2 CUT=$CUT SIMD=$SIMD bash assemble.sh
cp product-segment.mp4 product-segment-novo.mp4 ..; cp ui-export.mp4 ../ui.mp4
for f in ../product-segment.mp4 ../product-segment-novo.mp4 ../ui.mp4; do echo "$f $(ffprobe -v error -show_entries format=duration -of csv=p=0 $f)"; done
