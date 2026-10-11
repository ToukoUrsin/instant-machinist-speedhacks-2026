# Demo

**Videos:** [problem (60 s)](../../media/problem-60s.mp4) · [product demo](../../media/product-demo.mp4) · [verified FTC-10 simulation](results/ftc-10/run3/simulation.mp4) · [shop-floor integrations](../../media/integrations-minute.mp4)

## Headline: NIST FTC-10 housing (canonical run `out/run3`)

1. The customer sends a STEP model and a 5-page GD&T drawing:
   [`parts/ftc-10/drawing.pdf`](../parts/ftc-10/drawing.pdf), NIST PMI test case FTC-10, public domain.
2. Claude Opus 5.5 reads the drawing in 28.5 s and returns 25 machining notes and 8 questions for the
   customer. Among them: the material and stock size, the quantity, the `M3x0.5-6g` thread class on
   holes, and approval for the extra setups.
3. The customer's STEP is imported into Autodesk Fusion in the cloud through the Fusion Compute MCP
   and oriented for machining: 214 faces, 188.3 cm³.
4. Five OP1 strategies (face, 3D adaptive clearing, wall finish, ball-end finish of the fins) are
   programmed in Fusion, posted to Haas G-code and verified by our simulator.
5. The manual-style baseline fails the verifier: 6 rapid moves into stock. All 4 adaptive programs pass
   every safety check.
6. Best program: **26:42 cycle vs 1:49:46** for a typical cautious manual program, **76 % less machine
   time**.
7. The editable Fusion file is saved to Fusion Team. Total programming time: **7:08**.
8. The simulation video of the winning program, ending on "Verified: 0 gouges · 0 crashes · 26:42
   cycle" ([`results/ftc-10/run3/simulation.mp4`](results/ftc-10/run3/simulation.mp4), 20 s, 1920 × 1080).

## Second example: SM-101 (2.5D, canonical runs `out/run2` and `out/readme-native`)

1. Claude Opus 5.5 reads the drawing in 22 s, and the spec matches the reference exactly. Fusion builds
   the model from it.
2. 5 strategies are verified: **6:28 vs 19:43** (67.2 % less machine time). Programmed and saved in
   **2:34**.
3. The verifier catches real defects in Fusion's first program for this part: an 8 mm gouge at
   `N37935`, 0.2 mm left on the floor, and a 7 mm slot instead of 8 mm.
4. The Instant Machinist engine programs the same part without any CAD/CAM license: **3:07 vs 22:28**
   (86.1 % less machine time), 2.7 s to program.

## Stills

| Still | File |
|---|---|
| FTC-10: simulation, final frame with the verified badge | [`img/ftc-10-sim-final.jpg`](img/ftc-10-sim-final.jpg) |
| FTC-10: simulation, Ø6 ball end mill finishing the fins | [`img/ftc-10-sim-ball-finish.jpg`](img/ftc-10-sim-ball-finish.jpg) |
| FTC-10: customer STEP in cloud Fusion (Fusion Compute screenshot) | [`img/ftc-10-fusion-model.png`](img/ftc-10-fusion-model.png) |
| FTC-10: verifier maps of the winning program | [`img/ftc-10-verifier-best.png`](img/ftc-10-verifier-best.png) |
| FTC-10: customer drawing, page 1 | [`parts/ftc-10/drawing.png`](../parts/ftc-10/drawing.png) |
| SM-101: customer drawing | [`parts/sm-101/drawing.png`](../parts/sm-101/drawing.png) |
| SM-101: model built in cloud Fusion from the spec | [`img/fusion-model.png`](img/fusion-model.png) |
| SM-101: verifier, Fusion's first program fails (gouge, leftover) | [`img/verifier-fusion-first-program-fail.png`](img/verifier-fusion-first-program-fail.png) |
| SM-101: verifier, best Fusion program passes | [`img/verifier-fusion-best-pass.png`](img/verifier-fusion-best-pass.png) |
| SM-101: verifier, native engine program passes | [`img/verifier-native-pass.png`](img/verifier-native-pass.png) |

## Re-create the demo outputs

```bash
make demo-ftc10      # STEP + drawing → Opus 5.5 → STEP import into cloud Fusion → 5 verified OP1 programs → Fusion file + video
make demo-fusion     # SM-101 drawing → Opus 5.5 → model in cloud Fusion → 5 verified programs → Fusion file + video
make demo-native     # SM-101 on the Instant Machinist engine, offline
make verify-example  # the verifier report on Fusion's first SM-101 program
```
