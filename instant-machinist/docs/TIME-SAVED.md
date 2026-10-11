# Time saved: method, numbers, assumptions

Instant Machinist saves time in two places:

1. **Programmer time.** A new part goes from customer STEP and drawing to a verified program in minutes, not hours.
2. **Machine time.** The optimizer tries several strategies and keeps the fastest program that passes
   every check, so the program also cuts faster.

Measured numbers come from the runs listed below, and every input that is not measured is labeled as an
assumption. Two demo parts:

- **NIST FTC-10 housing** (headline). Public-domain NIST PMI test case: the customer sends a STEP model
  and a 5-page GD&T drawing. 158 × 75 × 31 mm, 214 faces. We program **OP1, the top side**: face, 3D
  adaptive clearing, contour wall finish, 6 mm ball-end parallel finish of the fins. Run `out/run3`,
  copied in [`results/ftc-10/`](results/ftc-10).
- **SM-101 sensor mount plate** (2.5D, complete in one setup). 6061-T6, 120 × 80 × 20 mm, quantity 25
  (read from the drawing). Face, outside profile with R8 corners, a 64 × 36 × 8 pocket, a 40 × 8 × 4
  slot, 4 × Ø6.6 and 2 × Ø8 through holes. Runs `out/run2` (Fusion) and `out/readme-native` (native engine).

## 1. Programmer time per new part

| Step | Manual (CAM programmer) | Instant Machinist: FTC-10 OP1 | Instant Machinist: SM-101 | Source |
|---|---|---|---|---|
| Read drawing, plan setup and operations, pick tools, program toolpaths, post, simulate | **1–4 h** | **7 min 08 s** (STEP + drawing → saved Fusion file + 5 verified programs) | **2 min 34 s** (Fusion path, drawing → saved Fusion file + 5 verified programs) · **2.7 s** (native engine, spec → verified program) + 22 s drawing read | Manual: shop estimate. Ours: measured, [`results/ftc-10/summary.json`](results/ftc-10/summary.json), [`results/sm-101-fusion/summary.json`](results/sm-101-fusion/summary.json), [`results/sm-101-native/summary.json`](results/sm-101-native/summary.json) |
| Human review of the program, simulation video and Claude's questions for the customer | included above | **10 min** | **10 min** | Assumption |
| Corrections after review | included above | **10 min** allowance | **10 min** allowance | Assumption |
| **Total** | **60–240 min** | **≈ 27 min** | **≈ 23 min** (Fusion path) | |
| **Saved per new part** | | **33–213 min (55–89 %)** | **37–217 min (62–91 %)** | |

The automated step is not the bottleneck; the human review is. The review budget is deliberately
generous: the reviewer starts from a program that has already passed gouge, leftover, rapid,
plunge and fixture checks and comes with a simulation video, so review is reading, not reprogramming.

The 1–4 h manual range is our shop estimate for a new part; we apply the same range to FTC-10's OP1. For comparison, published
figures range from "an hour" for simple 3-axis parts (CloudNC beta feedback, 2023) to "four to eight
hours" for a part programmed without macros (Modern Machine Shop, 2024).

Timeline of the FTC-10 run ([`results/ftc-10/events.jsonl`](results/ftc-10/events.jsonl)):

| t (s) | Step |
|---|---|
| 0.7 | Claude Opus 5.5 starts reading the 5-page `drawing.pdf` |
| 29.2 | Drawing read: ±0.75 mm general profile tolerance, 25 machining notes, 8 questions for the customer (material, stock size, quantity, finish, thread class, setup approval, edge break, one unclear tolerance frame) |
| 30.1 | Cloud Fusion session started |
| 39.8 | Customer STEP imported into Fusion and oriented Z-up: 214 faces, 188.3 cm³ |
| 39.8 – 382.2 | 5 strategies: 4 operations generated per strategy (21–34 s), Haas G-code posted (76k–113k lines), verified by our simulator (21–38 s) |
| 382.2 | Best strategy chosen: 26:42 cycle vs 1:49:46 baseline |
| 428.5 | Best strategy re-generated and the editable Fusion file saved to Fusion Team. Done |

Timeline of the SM-101 Fusion run ([`results/sm-101-fusion/events.jsonl`](results/sm-101-fusion/events.jsonl)):

| t (s) | Step |
|---|---|
| 0.7 | Claude Opus 5.5 starts reading `drawing.pdf` |
| 22.0 | Spec extracted: 6 features, ±0.1 mm, Ra 3.2, qty 25, 12 notes, 4 questions for the customer; matches the reference spec exactly |
| 22.7 | Cloud Fusion session started (warm session) |
| 28.3 | 3D model built in Fusion from the spec: 30 faces, 167.5 cm³ |
| 38.0 – 131.2 | 5 strategies: toolpaths generated, Haas G-code posted, verified by our simulator (each ≈ 20 s) |
| 131.2 | Best strategy chosen: 6:28 cycle vs 19:43 baseline |
| 154.4 | Best strategy re-generated and the editable Fusion file saved to Fusion Team. Done |

A cold start of cloud Fusion, the first session of the day, took 5 min 28 s from `start_fusion` to the
built model in an earlier run (`out/sm-101-fusion`). Warm sessions start in about 6 s.

## 2. Machine time per part

Cycle times come from our simulator's model (`sim/cycle.py`): programmed feed over path length,
rapids at 25,000 mm/min per axis, 4 s per tool change. The same model is applied to every program, so
the comparisons below are like for like.

**Baseline = a typical cautious manual program (our estimate), not a specific shop's program.**
- **FTC-10:** Fusion 3D pocket clearing with 4 mm stepover and 2 mm depth steps, 0.5 mm wall steps,
  0.3 mm ball-finish stepover, and conservative "book" feeds (Ø10 end mill at 5,000 rpm / 900 mm/min,
  Ø6 ball at 6,000 rpm / 800 mm/min).
- **SM-101, Fusion path:** Fusion's own 2D pocket + 2D contour roughing with 2 mm depth steps, 4 mm
  stepover and the same book feeds.
- **SM-101, native engine:** a 10 % stepover, 0.5 × D depth, 60 % feed-scale program.

### FTC-10 OP1 ([`results/ftc-10`](results/ftc-10), run `out/run3`)

Pass rule for an OP1 of a multi-setup part: gouge, rapid into stock, fixture and flute length must
pass. Stock that later setups machine is reported, not failed (see [VERIFIER.md](VERIFIER.md#ftc-10-op1-of-a-multi-setup-part)).

| Program | Cycle | Verifier |
|---|---|---|
| Baseline: 3D pocketing, 2 mm steps, book feeds | 1:49:46 (6,586.2 s) | **Fails**: 6 rapid moves into stock |
| Adaptive 1.5 mm load, 12 mm steps, 0.4 mm finish stepover | 38:14 (2,294.2 s) | Pass: 0 gouges, 0 rapids into stock |
| Adaptive 2.5 mm load, 12 mm steps, 0.4 mm finish stepover | 34:30 (2,070.9 s) | Pass |
| Adaptive 2.5 mm load, 24 mm steps, 0.5 mm finish stepover | 30:00 (1,800.8 s) | Pass |
| **Adaptive 3.0 mm load, 24 mm steps, 0.6 mm finish stepover (chosen)** | **26:42 (1,602.6 s)** | **Pass** |

**Saved: 4,983.6 s = 83 min per part (75.7 %).** The drawing gives no quantity, so Claude asks the
customer. At quantity 1 that is 83 min of spindle time on OP1 alone.

### SM-101, Fusion path ([`results/sm-101-fusion`](results/sm-101-fusion), run `out/run2`)

| Program | Cycle | Checks |
|---|---|---|
| Baseline: 2D pocketing, 2 mm steps, book feeds | 19:43 (1,183.0 s) | 6/6 pass |
| Adaptive 1.5 mm load, 10 mm steps | 8:39 (518.9 s) | 6/6 pass |
| Adaptive 2.5 mm load, 10 mm steps | 7:07 (427.0 s) | 6/6 pass |
| Adaptive 2.0 mm load, 20 mm steps | 7:19 (438.5 s) | 6/6 pass |
| **Adaptive 3.0 mm load, 20 mm steps (chosen)** | **6:28 (388.5 s)** | **6/6 pass** |

**Saved: 794.5 s = 13.2 min per part (67.2 %).** For the 25-piece order on the drawing that is
**5.5 h of spindle time**.

### SM-101, native engine ([`results/sm-101-native`](results/sm-101-native), run `out/readme-native`)

| Program | Cycle | Checks |
|---|---|---|
| Baseline: 10 % stepover, 0.5 × D steps, 60 % feeds | 22:28 (1,348.4 s) | 6/6 pass |
| **Chosen: offset roughing 60 % stepover, 1 × D steps (fastest of 8 variants)** | **3:07 (187.1 s)** | **6/6 pass** |

**Saved: 1,161.3 s = 19.4 min per part (86.1 %).** For 25 pieces: **8.1 h of spindle time**.

The two engines use different tools for the holes (Fusion: helical boring with a Ø5 end mill; native:
spot drill + Ø6.6 / Ø8 peck drills) and different feeds tables, so compare each engine against its own
baseline.

## 3. Per job

For one new FTC-10 job (OP1), at the 4 h end of the manual range: **3.5 h programmer time + 1.4 h
machine time ≈ 4.9 h saved**, before any repeat orders.

For one new SM-101-type job of 25 parts, Fusion path, at the 4 h end of the manual range:
**3.6 h programmer time + 5.5 h machine time ≈ 9 h saved**. At the 1 h end: 0.6 h + 5.5 h ≈ 6 h.

## Assumptions

- Manual programming time of 1–4 h per new part is a shop estimate. It is not measured here.
- Review (10 min) and corrections (10 min) are assumptions, budgeted the same for both parts.
- Baselines are our estimate of a typical cautious manual program, built with the same CAM system so
  the comparison isolates strategy and feeds.
- The cycle model uses programmed feeds and per-axis rapid rates without acceleration limits. Real
  machine times will be somewhat longer for every program, most of all for dense adaptive toolpaths.
- Machine setup (fixturing, tool touch-off, first-article inspection) is the same for both and not
  counted.
- Feeds and speeds: the Fusion strategies use the feeds in `fusion/strategies.py`; the native engine
  uses its 6061-T6 carbide table (`cam/feeds.py`), clamped to Haas VF-2 limits (8,100 rpm, 16,500 mm/min).

## Reproduce

```bash
make demo-native                        # native numbers, offline, about 3 s
make demo-ftc10                         # FTC-10 numbers: ANTHROPIC_API_KEY + Fusion token (docs/FUSION-COMPUTE.md)
make demo-fusion                        # SM-101 Fusion numbers
jq '.programming_s, .baseline.cycle_s, .best.cycle_s, .machining_saved_pct' out/demo-ftc10/summary.json
```
