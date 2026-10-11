"""ElevenLabs TTS with character timestamps. usage: tts_ts.py name text  (needs ELEVENLABS_API_KEY)"""
import base64, json, os, sys, urllib.request
name, text = sys.argv[1], sys.argv[2]
OUT = "out/demo/vo"
voice = os.environ.get("VOICE", "cjVigY5qzO86Huf0OWal")
body = {"text": text, "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.15, "use_speaker_boost": True}}
req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_192",
                             data=json.dumps(body).encode(), headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Content-Type": "application/json"})
d = json.load(urllib.request.urlopen(req))
open(f"{OUT}/{name}.mp3", "wb").write(base64.b64decode(d["audio_base64"]))
a = d["alignment"]
# word start times
words, cur, start = [], "", None
for ch, t0, t1 in zip(a["characters"], a["character_start_times_seconds"], a["character_end_times_seconds"]):
    if ch.isspace():
        if cur: words.append([cur, start, prev_end]); cur = ""
        continue
    if not cur: start = t0
    cur += ch; prev_end = t1
if cur: words.append([cur, start, prev_end])
json.dump(words, open(f"{OUT}/{name}.words.json", "w"))
print(name, words[-1][2])
