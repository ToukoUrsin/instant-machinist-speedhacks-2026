# Instant Machinist

**A customer's STEP model and drawing in. A verified CNC program, cycle time and simulation video out, in minutes instead of hours.**

Every new part a job shop wins needs a CNC program, and writing one takes a skilled programmer
1–4 hours before the spindle turns. Instant Machinist reads the drawing with Claude Opus 5.5,
programs the part in cloud Autodesk Fusion or with its own CAM engine, proves every program in its
own simulator, and keeps the fastest program that passes every safety check.

| NIST FTC-10 housing, OP1 (214 faces, 5-page GD&T drawing) | |
|---|---|
| Drawing + STEP → OP1 (top side) programmed, verified, posted to Haas G-code, saved as an editable Fusion file | **7 min 08 s** (a whole new part takes 1–4 h by hand, [sources](docs/PROBLEM.md); this run covers OP1 only) |
| Best cycle time vs our cautious manual-style baseline (same operations, book feeds) | **26:42 vs 1:49:46 (−76 %)** |
| Safety checks on the winning program (OP1 rule) | **PASS**: 0 gouges · 0 rapids into stock · 0 fixture hits; 3 short plunges flagged for review. The whole-part report shows FAIL only because later setups' stock remains |
| Cautious manual-style program (same operations, book feeds) | rejected by the verifier: 6 rapid moves into stock |
| Drawing problems flagged for the customer | 8 questions, e.g. missing material, `M3x0.5-6g` external thread class on holes |

![Verified FTC-10 simulation](instant-machinist/docs/img/ftc-10-sim-final.jpg)

**[▶ Demo video (3 min)](media/demo.mp4)** · Parts: [problem (60 s)](media/problem-60s.mp4) · [product demo](media/product-demo.mp4) · [simulation of the verified program](instant-machinist/docs/results/ftc-10/run3/simulation.mp4) · [shop-floor integrations](media/integrations-minute.mp4)

## What's in this repository

| Path | What it is |
|---|---|
| [`instant-machinist/`](instant-machinist/) | The product: drawing reader, Fusion Compute client, native 2.5D CAM engine, G-code simulator/verifier, strategy optimizer, video renderer, tests and docs. **Start here: [instant-machinist/README.md](instant-machinist/README.md)** |
| [`integrations/`](integrations/) | The rest of the job around the program: material sourcing (Darwin), supplier calls (Dial), deposit invoicing tested in a sandbox (Sparta), shop analytics (Keewano), multi-agent build memory (Alike) |
| [`media/`](media/) | Rendered demo videos |
| [`docs/`](docs/) | The problem and market, with sources; problem slides (PDF) |

## Try it in one minute (offline, no accounts)

```bash
cd instant-machinist
make install       # Python 3.12 venv via uv
make test          # interpreter, verifier, CAM engine, renderer, smoke tests
make demo-native   # SM-101 spec → native CAM → verified Haas program in ~3 s
                   # expect: best ≈ 3:10 vs ≈ 22:30 baseline, all checks PASS, report printed
```

The Fusion path (`make demo-ftc10`) needs an Anthropic API key and an Autodesk account; see
[instant-machinist/docs/FUSION-COMPUTE.md](instant-machinist/docs/FUSION-COMPUTE.md).

## Docs
- [The problem, with sources](docs/PROBLEM.md) · [Architecture](instant-machinist/docs/ARCHITECTURE.md) · [Verifier](instant-machinist/docs/VERIFIER.md) · [Time saved, method and assumptions](instant-machinist/docs/TIME-SAVED.md) · [Fusion Compute](instant-machinist/docs/FUSION-COMPUTE.md) · [Data contracts](instant-machinist/docs/CONTRACTS.md) · [Results](instant-machinist/docs/results/)

Built on 11 October 2026 at a16z SpeedHacks. MIT licensed.
