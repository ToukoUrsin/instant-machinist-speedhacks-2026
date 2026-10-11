# Simulation report: SM-101

**Result: FAIL**  
Programs: docs/examples/sm-101-fusion-first-program.nc

## Cycle time

| | time |
|---|---|
| Cutting (feed) | 8:14.9 |
| Rapid | 0:02.2 |
| Dwell | 0:00.0 |
| Tool change (5 x 4 s) | 0:20.0 |
| **Total** | **8:37.1** (8.62 min) |

| Tool | cutting | rapid | total | feed distance |
|---|---|---|---|---|
| T1 | 0:14.1 | 0:00.2 | 0:18.3 | 732.2 mm |
| T2 | 4:59.5 | 0:00.9 | 5:08.4 | 11700.7 mm |
| T3 | 0:29.5 | 0:00.2 | 0:33.7 | 533.4 mm |
| T4 | 2:31.8 | 0:00.9 | 2:36.7 | 3316.2 mm |

## Checks

| Check | Result | Detail |
|---|---|---|
| Gouge | FAIL | 2189.75 mm2, max 8.0 mm deep |
| Leftover above tolerance | FAIL | 2265.25 mm2 in 2 regions, max 4.0 mm |
| Rapid into stock | OK |  |
| Flat end mill plunge into solid | FAIL | 1 events |
| Below fixture / vise | OK |  |
| Engagement > flute length (warning) | OK |  |

### Gouge

- line 7601 `N37935 Z-7.` (T2) at X-27.88 Y-27.88 {"area_mm2": 2189.75, "max_depth_mm": 8.0, "z": -8.0, "feature": "F1", "part_floor_z": 0.0}

### Leftover above tolerance

-  at X-26.88 Y-17.62 {"area_mm2": 2121.5, "max_excess_mm": 0.2, "feature": "F3", "target_z": -8.0, "stock_z": -7.8}
-  at X-14.12 Y-33.62 {"area_mm2": 143.75, "max_excess_mm": 4.0, "feature": "F4", "target_z": -4.0, "stock_z": 0.0}

### Flat end mill plunge into solid

- line 7601 `N37935 Z-7.` (T2) at X-27.0 Y26.0 {"z": -7.0, "depth_into_material": 7.0}

_19800 segments, grid 496x336 @ 0.25 mm, target from features.json, runtime 1.85 s_
