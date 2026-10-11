# Canonical run outputs (NIST FTC-10, SM-101)

These files are copied unchanged from the runs that produced the numbers in the README. `out/` is
not committed, so they are kept here.

| Folder | Source run | Command |
|---|---|---|
| [`ftc-10/`](ftc-10) | `out/run3` | `python -m instant_machinist.pipeline --part parts/ftc-10 --engine fusion --out out/run3` |
| [`sm-101-fusion/`](sm-101-fusion) | `out/run2` | `python -m instant_machinist.pipeline --part parts/sm-101 --engine fusion --out out/run2 --no-video` |
| [`sm-101-native/`](sm-101-native) | `out/readme-native` | `python -m instant_machinist.pipeline --part parts/sm-101 --engine native --out out/readme-native --no-read --no-video` |

| File | Content |
|---|---|
| `summary.json` | Programming time, baseline, best, every variant with cycle time and pass/fail, % machine time saved |
| `events.jsonl` | Timeline of every step, in seconds since start (drawing read, model, toolpaths, post, verify, save) |
| `spec.json` | The machining spec used: SM-101 from Claude Opus 5.5's drawing read; FTC-10 stock, setup, STEP URL and orientation |
| `best-1001.nc` (`.nc.gz` for FTC-10) | The verified Haas program that won (FTC-10: 76,190 lines, gzipped) |
| `best-ops.json` | Its operations (Fusion: strategy, validity, Fusion warnings; native: tools, feeds, stepovers, times) |
| `best-report.md` / `.json` | Verifier report: cycle time per tool, all checks |
| `baseline-report.md` | Verifier report of the typical cautious manual program used as the baseline |
| `variants.json` | Native engine: all 8 variants ranked by cycle time |

**Reading the FTC-10 reports.** The `Result` line at the top of a verifier report is the whole-part
verdict: every check, including leftover. FTC-10's programs are OP1 of a multi-setup part, so the
pipeline judges them by the safety checks (gouge, rapid into stock, fixture, flute length). The stock
left for later setups is listed in the report region by region. Those per-program verdicts are in
`summary.json` (`pass`, `checks`) and in [VERIFIER.md](../VERIFIER.md#pass-rules).
