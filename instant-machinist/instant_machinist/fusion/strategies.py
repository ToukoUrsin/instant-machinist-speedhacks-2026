"""CAM strategy variants the agent explores in Fusion; the fastest verified one wins."""
TOOLS = {
    "1": {"desc": "50mm Face Mill", "rpm": 6000, "feed": 3000},
    "2": {"desc": "10mm Flat Endmill", "rpm": 8000, "feed": 2400},
    "3": {"desc": "6mm Flat Endmill", "rpm": 8000, "feed": 1500},
    "4": {"desc": "5mm Flat Endmill", "rpm": 8000, "feed": 1200},
}
CONSERVATIVE_TOOLS = {
    "1": {"desc": "50mm Face Mill", "rpm": 3000, "feed": 1200},
    "2": {"desc": "10mm Flat Endmill", "rpm": 5000, "feed": 900},
    "3": {"desc": "6mm Flat Endmill", "rpm": 6000, "feed": 600},
    "4": {"desc": "5mm Flat Endmill", "rpm": 6000, "feed": 500},
}

BASELINE = {"name": "baseline-manual", "label": "Typical manual program: 2D pocketing, 2 mm depth steps, book feeds",
            "rough": "pocket2d", "stepover": 4, "stepdown": 2, "slotStepdown": 1, "tools": CONSERVATIVE_TOOLS}

VARIANTS = [
    {"name": f"adaptive-L{load}-D{sd}", "label": f"Adaptive clearing, {load} mm load, {sd} mm steps",
     "rough": "adaptive", "optimalLoad": load, "stepdown": sd, "slotStepdown": 2, "tools": TOOLS}
    for load, sd in [(1.5, 10), (2.5, 10), (2.0, 20), (3.0, 20)]
]

# 3D parts (STEP input): top-side OP1 with ball-mill finishing.
TOOLS_3D = {**TOOLS, "5": {"desc": "6mm Ball Endmill", "rpm": 8000, "feed": 2000}}
CONSERVATIVE_TOOLS_3D = {**CONSERVATIVE_TOOLS, "5": {"desc": "6mm Ball Endmill", "rpm": 6000, "feed": 800}}

BASELINE_3D = {"name": "baseline-manual", "label": "Typical manual program: 3D pocketing, 2 mm depth steps, book feeds",
               "rough": "pocket", "stepover": 4, "stepdown": 2, "wallStepdown": 0.5, "finishStepover": 0.3,
               "tools": CONSERVATIVE_TOOLS_3D}

VARIANTS_3D = [
    {"name": f"adaptive-L{load}-D{sd}-F{fs}", "label": f"Adaptive {load} mm load, {sd} mm steps, {fs} mm finish stepover",
     "rough": "adaptive", "optimalLoad": load, "stepdown": sd, "wallStepdown": 1.0, "finishStepover": fs, "tools": TOOLS_3D}
    for load, sd, fs in [(1.5, 12, 0.4), (2.5, 12, 0.4), (2.5, 24, 0.5), (3.0, 24, 0.6)]
]
