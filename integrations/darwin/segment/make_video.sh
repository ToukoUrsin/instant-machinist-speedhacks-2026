#!/usr/bin/env bash
# Render segment.html -> segment-<slug>-30s.mp4 (main-film cut), -60s.mp4 (Darwin judging cut) and
# -30s-dial-handoff.mp4 (last 5 s hands the stock gap to a real clip of the Dial segment).
# On the box (renders are not allowed on the build server; this ships the job to Daytona via drun):
#   cd integrations/darwin/segment && python3 build_data.py ftc-10 && bash make_video.sh ftc-10 30 60 30h
#   bash make_video.sh stills 30:1,8,14 60:20,40      # HTML stills only (layout check)
set -euo pipefail
cd "$(dirname "$0")"
if [ "${1:-}" != "--inner" ]; then
  mkdir -p fonts && cp ~/.local/share/fonts/inter/Inter-{Regular,Medium,SemiBold,Bold,ExtraBold}.otf fonts/  # Inter for the sandbox
  cp ../../dial/segment/segment-ftc-10.mp4 dial-src.mp4   # read-only copy of the Dial segment for the handoff cut
  trap 'rm -rf fonts dial-src.mp4' EXIT
  drun --setup "sudo apt-get install -y ffmpeg fonts-dejavu-core >/dev/null 2>&1; npm i --no-save playwright-core@1 >/dev/null 2>&1 && npx playwright-core install --with-deps chromium >/dev/null 2>&1" -- bash make_video.sh --inner "$@"
  exit
fi
shift
mkdir -p ~/.fonts && cp fonts/*.otf ~/.fonts/ && fc-cache -f >/dev/null && echo "Inter fonts: $(fc-list | grep -c Inter)"
export NODE_PATH=${NODE_PATH:-$PWD/node_modules}
SLUG=${1:-ftc-10}; shift; FPS=${FPS:-30}
mkdir -p stills
if [ "$SLUG" = stills ]; then
  for spec in "$@"; do V=${spec%%:*} node render.js stills stills "${spec#*:}" & done; wait
  rm -rf node_modules package.json package-lock.json; exit 0
fi
ENC="-c:v libx264 -crf 22 -preset medium -r $FPS -movflags +faststart"
one() {
  local V=$1 F=frames_$1 OUT=segment-$SLUG-$1s.mp4
  [ "$V" = 30h ] && OUT=segment-$SLUG-30s-dial-handoff.mp4
  rm -rf "$F"; V=$V node render.js "$F" "$FPS" >/dev/null
  local DUR; DUR=$(python3 -c "import glob;print((len(glob.glob('$F/f*.jpg'))-1)/$FPS)")
  if [ "$V" = 30h ]; then
    # Dial listen-in section (real call audio, 1x) overlaid into the handoff frame for the last 5 s.
    local AT; AT=$(python3 -c "print($DUR-5)"); local SS=${DIAL_SS:-6}
    ffmpeg -v error -y -ss "$SS" -t 5 -i dial-src.mp4 -vf fps=$FPS,scale=1056:594 \
      -af "afade=t=in:d=0.3,afade=t=out:st=4.4:d=0.6" -c:v libx264 -crf 18 -c:a aac -b:a 192k dclip.mp4
    ffmpeg -v error -y -framerate "$FPS" -i "$F/f%05d.jpg" -i dclip.mp4 -filter_complex \
      "[0:v]scale=in_range=pc:out_range=tv,format=yuv420p[m];[1:v]setpts=PTS-STARTPTS+$AT/TB[d];
       [m][d]overlay=780:290:eof_action=pass,format=yuv420p[v];
       [1:a]asetpts=PTS-STARTPTS,adelay=$(python3 -c "print(int($AT*1000))"):all=1,apad,aformat=sample_rates=48000:channel_layouts=stereo[a]" \
      -map "[v]" -map "[a]" -t "$DUR" $ENC -color_range tv -c:a aac -b:a 128k "$OUT"
    rm -f dclip.mp4
  else
    ffmpeg -v error -y -framerate "$FPS" -i "$F/f%05d.jpg" -f lavfi -i anullsrc=r=48000:cl=stereo -t "$DUR" \
      -vf scale=in_range=pc:out_range=tv,format=yuv420p -color_range tv $ENC -c:a aac -b:a 64k -shortest "$OUT"
  fi
  rm -rf "$F"
  for ts in $(python3 -c "d=$DUR;print(' '.join(str(round(x,2)) for x in [i*d/12+0.5 for i in range(12)]+[d-0.6]+([d-4.7,d-3,d-1.5] if '$V'=='30h' else [])))"); do
    ffmpeg -v error -y -ss "$ts" -i "$OUT" -frames:v 1 -vf scale=1280:-1 "stills/qa_${V}_${ts}.png" || true
  done
  echo "wrote $OUT $DUR s"
}
for V in "$@"; do one "$V" & done; wait
rm -rf node_modules package.json package-lock.json
for f in segment-$SLUG-*.mp4; do ffprobe -v error -show_entries format=duration,size:stream=codec_name,width,height,r_frame_rate -of compact "$f"; done
