#!/bin/bash
# Assemble the product segment from recorded pieces. Run from out/demo/build (inputs copied there):
#   ui.mp4 sim.mp4 end.mp4 solution.mp3 result.mp3 bed.mp3
# Outputs: product-segment.mp4 (VO + soft music), product-segment-novo.mp4 (silent), ui.mp4 export (ui-export.mp4)
set -euo pipefail
X1=${X1:-37.6}      # ui -> sim crossfade start (output time)
SIMD=${SIMD:-16}    # simulation.mp4 duration
XF=0.4
X2=$(python3 -c "print(round($X1 + $SIMD - $XF, 3))")   # sim -> end card crossfade start
ENDD=${ENDD:-7}
TOTAL=$(python3 -c "print(round($X2 + $ENDD, 3))")
VO1=${VO1:-0.8}     # solution VO start
VO2=${VO2:-32.5}    # result VO part 1 start
CUT=${CUT:-18.75}   # split point inside result.mp3 ("That's sixty-seven percent...")
VO3=$(python3 -c "print(round($X2 + 0.8, 3))")          # result VO part 2 lands on the end card
echo "X1=$X1 X2=$X2 TOTAL=$TOTAL VO3=$VO3"

ffmpeg -y -loglevel error -i ui.mp4 -i sim.mp4 -i end.mp4 -filter_complex "
[0:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p,settb=1/30[a];
[1:v]scale=1920:1080,setpts=PTS-STARTPTS,fps=30,format=yuv420p,settb=1/30[b];
[2:v]trim=0:$ENDD,setpts=PTS-STARTPTS,fps=30,format=yuv420p,settb=1/30[c];
[a][b]xfade=transition=fade:duration=$XF:offset=$X1[ab];
[ab][c]xfade=transition=fade:duration=$XF:offset=$X2,trim=0:$TOTAL,setpts=PTS-STARTPTS[v]" \
  -map "[v]" -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -r 30 -movflags +faststart -an video.mp4

ffmpeg -y -loglevel error -i solution.mp3 -i result.mp3 -i bed.mp3 -filter_complex "
[0:a]aresample=48000,adelay=$(python3 -c "print(int($VO1*1000))"):all=1[s];
[1:a]aresample=48000,atrim=0:$CUT,afade=t=out:st=$(python3 -c "print($CUT-0.12)"):d=0.12,adelay=$(python3 -c "print(int($VO2*1000))"):all=1[r1];
[1:a]aresample=48000,atrim=start=$CUT,asetpts=PTS-STARTPTS,afade=t=in:d=0.05,adelay=$(python3 -c "print(int($VO3*1000))"):all=1[r2];
[s][r1][r2]amix=inputs=3:normalize=0,apad[vo];
[2:a]aresample=48000,atrim=0:$TOTAL,volume=-14dB,afade=t=in:d=1.5,afade=t=out:st=$(python3 -c "print($TOTAL-2.5)"):d=2.5[m];
[vo][m]amix=inputs=2:normalize=0,atrim=0:$TOTAL[out]" \
  -map "[out]" -c:a pcm_s16le premix.wav
# two-pass loudnorm to -14 LUFS
M=$(ffmpeg -hide_banner -i premix.wav -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p')
LN=$(python3 -c "import json,sys; m=json.loads(sys.argv[1]); print(f\"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true\")" "$M")
ffmpeg -y -loglevel error -i premix.wav -af "$LN,aresample=48000" -c:a pcm_s16le mix.wav

ffmpeg -y -loglevel error -i video.mp4 -i mix.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart product-segment.mp4
ffmpeg -y -loglevel error -i video.mp4 -f lavfi -i anullsrc=r=48000:cl=stereo -map 0:v -map 1:a -c:v copy -c:a aac -b:a 128k -t $TOTAL -movflags +faststart product-segment-novo.mp4
ffmpeg -y -loglevel error -i ui.mp4 -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -movflags +faststart -an ui-export.mp4
ls -la *.mp4
