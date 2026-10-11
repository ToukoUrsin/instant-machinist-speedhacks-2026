# Simulation report: SM-101

**Result: PASS**  
Programs: out/readme-native/native/baseline/1001.nc

## Cycle time

| | time |
|---|---|
| Cutting (feed) | 21:54.7 |
| Rapid | 0:09.7 |
| Dwell | 0:00.0 |
| Tool change (6 x 4 s) | 0:24.0 |
| **Total** | **22:28.4** (22.47 min) |

| Tool | cutting | rapid | total | feed distance |
|---|---|---|---|---|
| T1 | 0:50.3 | 0:00.5 | 0:54.8 | 584.0 mm |
| T2 | 18:45.0 | 0:03.2 | 18:52.2 | 14937.8 mm |
| T3 | 1:18.9 | 0:00.4 | 1:23.3 | 583.8 mm |
| T4 | 0:24.6 | 0:01.5 | 0:30.1 | 34.4 mm |
| T5 | 0:25.6 | 0:03.0 | 0:32.6 | 135.5 mm |
| T6 | 0:10.3 | 0:01.0 | 0:15.3 | 45.0 mm |

## Checks

| Check | Result | Detail |
|---|---|---|
| Gouge | OK |  |
| Leftover above tolerance | OK |  |
| Rapid into stock | OK |  |
| Flat end mill plunge into solid | OK |  |
| Below fixture / vise | OK |  |
| Engagement > flute length (warning) | OK |  |

_4789 segments, grid 496x336 @ 0.25 mm, target from features.json, runtime 0.91 s_
