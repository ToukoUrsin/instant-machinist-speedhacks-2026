#!/bin/bash
# usage: tts.sh name "text"
set -e
OUT=out/demo/vo
VOICE=${VOICE:-cjVigY5qzO86Huf0OWal}
python3 - "$1" "$2" <<'PY' > /tmp/tts_$1.json
import json,sys
print(json.dumps({"text":sys.argv[2],"model_id":"eleven_multilingual_v2","voice_settings":{"stability":0.55,"similarity_boost":0.8,"style":0.15,"use_speaker_boost":True}}))
PY
bash -c "curl -sf -X POST https://api.elevenlabs.io/v1/text-to-speech/$VOICE?output_format=mp3_44100_192 -H \"xi-api-key: \$ELEVENLABS_API_KEY\" -H 'Content-Type: application/json' --data @/tmp/tts_$1.json -o $OUT/$1.mp3"
ffprobe -v error -show_entries format=duration -of csv=p=0 $OUT/$1.mp3
