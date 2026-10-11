# Simulation report: SM-101

**Result: PASS**  
Programs: out/readme-native/native/native/1001.nc

## Cycle time

| | time |
|---|---|
| Cutting (feed) | 2:36.7 |
| Rapid | 0:06.4 |
| Dwell | 0:00.0 |
| Tool change (6 x 4 s) | 0:24.0 |
| **Total** | **3:07.1** (3.12 min) |

| Tool | cutting | rapid | total | feed distance |
|---|---|---|---|---|
| T1 | 0:18.1 | 0:00.5 | 0:22.6 | 584.0 mm |
| T2 | 1:27.6 | 0:01.1 | 1:32.8 | 2377.4 mm |
| T3 | 0:30.9 | 0:00.4 | 0:35.3 | 350.3 mm |
| T4 | 0:08.9 | 0:01.5 | 0:14.4 | 34.4 mm |
| T5 | 0:07.8 | 0:02.1 | 0:13.9 | 115.2 mm |
| T6 | 0:03.3 | 0:00.9 | 0:08.2 | 39.9 mm |

## Checks

| Check | Result | Detail |
|---|---|---|
| Gouge | OK |  |
| Leftover above tolerance | OK |  |
| Rapid into stock | OK |  |
| Flat end mill plunge into solid | OK |  |
| Below fixture / vise | OK |  |
| Engagement > flute length (warning) | OK |  |

_1225 segments, grid 496x336 @ 0.25 mm, target from features.json, runtime 0.48 s_
