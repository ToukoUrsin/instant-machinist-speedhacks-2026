#!/usr/bin/env bash
# Render segment.html -> segment-20s.mp4 and overlay.html -> overlay-10s.mp4 (green key #00ff00) + overlay-10s-alpha.webm (VP9 alpha).
# On the box: refresh numbers, then this script ships the render to Daytona via drun (renders are not allowed on the build server):
#   cd integrations/alike && python3 stats.py && python3 segment/build_data.py && bash segment/make_video.sh
set -euo pipefail
cd "$(dirname "$0")"
if [ "${1:-}" != "--inner" ]; then
  mkdir -p fonts && cp ~/.local/share/fonts/inter/Inter-{Regular,Medium,SemiBold,Bold,ExtraBold}.otf fonts/  # Inter for the sandbox
  trap 'rm -rf fonts' EXIT
  drun --setup "sudo apt-get install -y ffmpeg fonts-dejavu-core >/dev/null 2>&1; npm i --no-save playwright-core@1 >/dev/null 2>&1 && npx playwright-core install --with-deps chromium >/dev/null 2>&1" -- bash make_video.sh --inner
  exit
fi
mkdir -p ~/.fonts && cp fonts/*.otf ~/.fonts/ && fc-cache -f >/dev/null && fc-list | grep -c "Inter" || true
export NODE_PATH=${NODE_PATH:-$PWD/node_modules}
FPS=${FPS:-30}
rm -rf frames oframes kframes && mkdir -p frames oframes kframes
node render.js segment.html frames "$FPS" &
node render.js overlay.html oframes "$FPS" png-alpha &
node render.js "overlay.html?key=1" kframes "$FPS" &
wait
V="-c:v libx264 -vf scale=in_range=pc:out_range=tv,format=yuv420p -color_range tv -crf 20 -preset slow -r $FPS -movflags +faststart"
ffmpeg -v error -y -framerate "$FPS" -i frames/f%05d.jpg -f lavfi -i anullsrc=r=48000:cl=stereo $V -c:a aac -b:a 64k -shortest segment-20s.mp4
ffmpeg -v error -y -framerate "$FPS" -i kframes/f%05d.jpg $V overlay-10s.mp4
ffmpeg -v error -y -framerate "$FPS" -i oframes/f%05d.png -c:v libvpx-vp9 -pix_fmt yuva420p -b:v 0 -crf 30 -row-mt 1 -auto-alt-ref 0 overlay-10s-alpha.webm
rm -rf frames oframes kframes node_modules package.json package-lock.json
ls -la segment-20s.mp4 overlay-10s.mp4 overlay-10s-alpha.webm
