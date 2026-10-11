#!/usr/bin/env bash
# Render segment.html -> segment-60s.mp4 (1080p30 H.264, silent stereo AAC track so it concatenates with the other segments).
# On the build server this ships the render to Daytona via drun (renders are not allowed on the box), with real Inter fonts:
#   cd integrations/sparta/segment && python3 build_data.py && bash make_video.sh            # full video + check frames
#   bash make_video.sh stills 5,15,25,33,42,50,58                                         # stills only
set -euo pipefail
cd "$(dirname "$0")"
if [ "${1:-}" != "--inner" ]; then
  mkdir -p fonts && cp ~/.local/share/fonts/inter/Inter-{Regular,Medium,SemiBold,Bold,ExtraBold}.otf fonts/  # Inter for the sandbox
  trap 'rm -rf fonts' EXIT
  drun --setup "sudo apt-get install -y ffmpeg fonts-dejavu-core >/dev/null 2>&1; npm i --no-save --prefix /tmp/pw playwright-core@1 >/dev/null 2>&1 && /tmp/pw/node_modules/.bin/playwright-core install --with-deps chromium >/dev/null 2>&1" -- bash make_video.sh --inner "$@"
  exit
fi
shift
mkdir -p ~/.fonts && cp fonts/*.otf ~/.fonts/ && fc-cache -f >/dev/null
N=$(fc-list | grep -c "Inter" || true); echo "Inter faces installed: $N"; [ "$N" -gt 0 ] || { echo "no Inter font"; exit 1; }
export NODE_PATH=${NODE_PATH:-/tmp/pw/node_modules}
FPS=${FPS:-30}
if [ "${1:-}" = stills ]; then rm -rf stills && node render.cjs stills stills "$2"; exit; fi
rm -rf frames && mkdir -p frames
node render.cjs frames "$FPS"
ffmpeg -v error -y -framerate "$FPS" -i frames/f%05d.jpg -f lavfi -i anullsrc=r=48000:cl=stereo \
  -c:v libx264 -pix_fmt yuv420p -crf 22 -preset slow -tune stillimage -r "$FPS" -c:a aac -b:a 96k -shortest \
  -movflags +faststart segment-60s.mp4
rm -rf frames
mkdir -p check && for t in 2 9 14 19.5 23 26.5 30 34.5 38 44.5 48 52.5 56 59.5; do
  ffmpeg -v error -y -ss "$t" -i segment-60s.mp4 -frames:v 1 "check/t$t.png"; done
ffprobe -v error -show_entries format=duration,size:stream=codec_name,width,height,r_frame_rate -of compact segment-60s.mp4
echo "wrote segment-60s.mp4"
