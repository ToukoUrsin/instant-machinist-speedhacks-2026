#!/usr/bin/env bash
# Render segment.html -> segment-30s.mp4 and segment-60s.mp4 (1080p, 30 fps, H.264, silent stereo track for editing).
# On the box: refresh numbers, then this script ships the render to Daytona via drun (renders are not allowed on the build server):
#   cd integrations/keewano && export XDG_RUNTIME_DIR=/run/user/1000 \
#     && python3 ingest.py && python3 segment_data.py \
#     && python3 segment/build_data.py && bash segment/make_video.sh [both|30|60|stills|check]
#   stills: JPEG stills + automatic clipping check;  check: both cuts + frames extracted from the MP4s into check/
set -euo pipefail
cd "$(dirname "$0")"
if [ "${1:-}" != "--inner" ]; then
  mkdir -p fonts && cp ~/.local/share/fonts/inter/Inter-{Regular,Medium,SemiBold,Bold,ExtraBold}.otf fonts/  # Inter for the sandbox
  trap 'rm -rf fonts' EXIT
  drun --setup "sudo apt-get update -qq >/dev/null 2>&1; sudo apt-get install -y ffmpeg fonts-dejavu-core fonts-jetbrains-mono >/dev/null 2>&1; npm i --no-save playwright-core@1 >/dev/null 2>&1 && npx playwright-core install --with-deps chromium >/dev/null 2>&1" -- bash make_video.sh --inner "${1:-both}"
  exit
fi
mkdir -p ~/.fonts && cp fonts/*.otf ~/.fonts/ && fc-cache -f >/dev/null && echo "fonts: $(fc-list | grep -c 'Inter') Inter, $(fc-list | grep -c 'JetBrains') JetBrains Mono"
export NODE_PATH=${NODE_PATH:-$PWD/node_modules}
FPS=${FPS:-30}; WHAT=${2:-both}
if [ "$WHAT" = stills ]; then
  node render.js stills stills "${T30:-1,3.5,5,8,11.5,15,19,21.5,24,26.5,29}" 30
  node render.js stills stills "${T60:-2,5.5,10,14,18,22,26,31,36,39,42,45,49,51,53,56,58.5}" 60
  rm -rf node_modules package.json package-lock.json; exit 0
fi
cuts=$(case "$WHAT" in both|check) echo "30 60";; *) echo "$WHAT";; esac)
for C in $cuts; do
  rm -rf frames && mkdir -p frames
  node render.js frames "$FPS" "$C"
  ffmpeg -v error -y -framerate "$FPS" -i frames/f%05d.jpg -f lavfi -i anullsrc=r=48000:cl=stereo \
    -c:v libx264 -vf scale=in_range=pc:out_range=tv,format=yuv420p -color_range tv -crf 22 -preset slow -tune stillimage -r "$FPS" \
    -c:a aac -b:a 64k -shortest -movflags +faststart "segment-${C}s.mp4"
  rm -rf frames
  ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate:format=duration,size -of compact "segment-${C}s.mp4"
done
if [ "$WHAT" = check ]; then
  rm -rf check && mkdir -p check
  for t in 1 3 6 9 11.5 14 17 19.5 22 24 26 28.5; do ffmpeg -v error -y -ss $t -i segment-30s.mp4 -frames:v 1 -q:v 3 check/v30_$t.jpg; done
  for t in 2 5 9 13 17 21 24 28 32 36 38.5 40 44 48 52 55 58.5; do ffmpeg -v error -y -ss $t -i segment-60s.mp4 -frames:v 1 -q:v 3 check/v60_$t.jpg; done
fi
rm -rf node_modules package.json package-lock.json
