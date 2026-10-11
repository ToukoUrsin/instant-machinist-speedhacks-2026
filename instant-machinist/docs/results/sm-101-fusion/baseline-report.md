# Simulation report: SM-101

**Result: PASS**  
Programs: out/run2/fusion/baseline-manual/1001.nc

## Cycle time

| | time |
|---|---|
| Cutting (feed) | 19:20.6 |
| Rapid | 0:02.4 |
| Dwell | 0:00.0 |
| Tool change (5 x 4 s) | 0:20.0 |
| **Total** | **19:43.0** (19.72 min) |

| Tool | cutting | rapid | total | feed distance |
|---|---|---|---|---|
| T1 | 0:33.4 | 0:00.2 | 0:37.6 | 732.2 mm |
| T2 | 10:12.6 | 0:01.1 | 10:21.7 | 8519.1 mm |
| T3 | 2:36.6 | 0:00.2 | 2:40.8 | 1076.5 mm |
| T4 | 5:58.0 | 0:00.9 | 6:02.9 | 3340.7 mm |

## Checks

| Check | Result | Detail |
|---|---|---|
| Gouge | OK |  |
| Leftover above tolerance | OK |  |
| Rapid into stock | OK |  |
| Flat end mill plunge into solid | OK |  |
| Below fixture / vise | OK |  |
| Engagement > flute length (warning) | OK |  |

_13930 segments, grid 496x336 @ 0.25 mm, target from features.json, runtime 1.44 s_
