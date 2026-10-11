#!/usr/bin/env bash
# Render segment.html -> segment-<slug>.mp4 with the real Dial call audio under the listen-in section.
# Renders are not allowed on the build server: the outer call ships the job to Daytona via drun (with Inter fonts).
#   cd integrations/dial && python3 segment/build_data.py ftc-10 && bash segment/make_video.sh ftc-10
set -euo pipefail
SLUG=${1:-ftc-10}
SEG="$(cd "$(dirname "$0")" && pwd)"
if [ "${2:-}" != "--inner" ]; then
  cd "$SEG/.."   # dial/: drun uploads it (segment + evidence)
  mkdir -p segment/fonts && cp ~/.local/share/fonts/inter/Inter-{Regular,Medium,SemiBold,Bold,ExtraBold}.otf segment/fonts/
  trap 'rm -rf "$SEG/fonts"' EXIT
  drun --setup "sudo apt-get install -y ffmpeg >/dev/null 2>&1; npm i --no-save playwright-core@1 >/dev/null 2>&1 && npx playwright-core install --with-deps chromium >/dev/null 2>&1" -- bash segment/make_video.sh "$SLUG" --inner
  exit
fi
cd "$SEG"
mkdir -p ~/.fonts && cp fonts/*.otf ~/.fonts/ && fc-cache -f >/dev/null
N=$(fc-list | grep -c "Inter" || true); echo "Inter fonts: $N"; [ "$N" -gt 0 ] || { echo "Inter missing"; exit 1; }
export NODE_PATH=${NODE_PATH:-$PWD/../node_modules}
FPS=${FPS:-30}
rm -rf frames && mkdir -p frames
node render.js frames "$FPS"
read AT START END FILE DUR < <(python3 - <<'PY'
import json,re
d=json.loads(re.sub(r'^window.DATA = |;\s*$','',open('data.js').read()))
c=d['clip']; print(5, c['start'], c['end'], c['file'], 5+(c['end']-c['start'])+14+11+7)
PY
)
LEN=$(python3 -c "print($END-$START)")
ffmpeg -v error -y -ss "$START" -t "$LEN" -i "../evidence/$SLUG/$FILE" \
  -af "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.3,afade=t=out:st=$(python3 -c "print($LEN-0.5)"):d=0.5,adelay=$((AT*1000)):all=1,apad" -t "$DUR" -ar 48000 -ac 2 audio.m4a
ffmpeg -v error -y -framerate "$FPS" -i frames/f%05d.jpg -i audio.m4a -c:v libx264 -pix_fmt yuv420p -crf 20 \
  -preset medium -c:a aac -b:a 128k -shortest -movflags +faststart "segment-$SLUG.mp4"
rm -rf frames audio.m4a
echo "wrote segment-$SLUG.mp4"
