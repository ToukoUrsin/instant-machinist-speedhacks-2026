"""Write VO text for the product segment from a run's summary.json (real numbers only) and synthesize it.
usage: python3 demo/vo/make_vo.py out/run3 [--only result]"""
import json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def words(n: int) -> str:
    if n < 20:
        return ONES[n]
    t, o = divmod(n, 10)
    return TENS[t] + ("" if o == 0 else "-" + ONES[o])


def dur(sec: float) -> str:
    if sec >= 3600 - 30:
        h, mm = divmod(int(round(sec / 60)), 60)
        out = "one hour" if h == 1 else f"{words(h)} hours"
        return out + (f" and {words(mm)} minute{'s' if mm != 1 else ''}" if mm else "")
    m, s = divmod(int(sec), 60)   # floor, to match the on-screen m:ss
    out = f"{words(m)} minute{'s' if m != 1 else ''}"
    return out + (f" and {words(s)} second{'s' if s != 1 else ''}" if s else "")


run = REPO / sys.argv[1]
S = json.loads((run / "summary.json").read_text())
n = len(S["variants"])
pct = int(round(S["machining_saved_pct"]))
events = [json.loads(l) for l in (run / "events.jsonl").read_text().splitlines() if l.strip()]
imported = any(e["step"] == "model" and ("STEP" in e["msg"] or "import" in e["msg"].lower()) for e in events)
model_line = "It brings in the customer's 3D model, " if imported else "It builds the 3D model, "
texts = {
    "solution": ("This is Instant Machinist. Drop in the customer's drawing. Claude reads it the way a programmer would: "
                 "material, quantity, tolerances, every feature. Then it drives Autodesk Fusion in the cloud. " + model_line +
                 f"sets up the stock, and generates the toolpaths. And it doesn't stop at one program. It tries {words(n)} strategies, "
                 "and our own simulator machines every one of them virtually, checking for gouges, leftover material and crashes. "
                 "Only verified programs go out."),
    "result": ("Out comes G-code ready for the machine, plus the Fusion file if your programmer wants to tweak it. Here's the simulation. "
               "Because it can try strategies nobody has time to try by hand, the program it picked runs in "
               f"{dur(S['best']['cycle_s'])}, instead of {dur(S['baseline']['cycle_s'])} for a typical cautious program. "
               f"That's {words(pct)} percent less machine time, on every part you run."),
}
only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else list(texts)
for k in only:
    print(k, "|", texts[k])
    subprocess.run([sys.executable, str(HERE / "tts_ts.py"), k, texts[k]], check=True)
