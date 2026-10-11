# Simulation report: NIST FTC-10

**Result: FAIL**  
Programs: out/run3/fusion/adaptive-L3.0-D24-F0.6/1001.nc

## Cycle time

| | time |
|---|---|
| Cutting (feed) | 26:13.1 |
| Rapid | 0:13.5 |
| Dwell | 0:00.0 |
| Tool change (4 x 4 s) | 0:16.0 |
| **Total** | **26:42.6** (26.71 min) |

| Tool | cutting | rapid | total | feed distance |
|---|---|---|---|---|
| T1 | 0:16.5 | 0:00.2 | 0:20.7 | 858.6 mm |
| T2 | 7:55.9 | 0:07.1 | 8:07.0 | 21280.6 mm |
| T3 | 5:50.5 | 0:04.9 | 5:59.4 | 11192.5 mm |
| T5 | 12:10.2 | 0:01.3 | 12:15.5 | 24429.7 mm |

## Checks

| Check | Result | Detail |
|---|---|---|
| Gouge | OK |  |
| Leftover above tolerance | FAIL | 469.38 mm2 in 61 regions, max 15.632 mm |
| Rapid into stock | OK |  |
| Flat end mill plunge into solid | FAIL | 3 events |
| Below fixture / vise | OK |  |
| Engagement > flute length (warning) | OK |  |

### Leftover above tolerance

-  at X28.38 Y18.38 {"area_mm2": 62.12, "max_excess_mm": 0.5, "feature": null, "target_z": -8.0, "stock_z": -7.5}
-  at X-62.62 Y37.38 {"area_mm2": 56.62, "max_excess_mm": 1.238, "feature": null, "target_z": -23.238, "stock_z": -22.0}
-  at X62.62 Y-37.38 {"area_mm2": 56.62, "max_excess_mm": 1.238, "feature": null, "target_z": -23.238, "stock_z": -22.0}
-  at X22.38 Y6.38 {"area_mm2": 51.56, "max_excess_mm": 1.967, "feature": null, "target_z": -7.607, "stock_z": -5.64}
-  at X22.38 Y-6.38 {"area_mm2": 41.06, "max_excess_mm": 1.966, "feature": null, "target_z": -7.607, "stock_z": -5.641}
-  at X-60.62 Y-37.38 {"area_mm2": 37.75, "max_excess_mm": 0.682, "feature": null, "target_z": -8.482, "stock_z": -7.8}
-  at X40.12 Y20.38 {"area_mm2": 35.75, "max_excess_mm": 1.327, "feature": null, "target_z": -5.5, "stock_z": -4.173}
-  at X51.12 Y20.38 {"area_mm2": 35.75, "max_excess_mm": 1.327, "feature": null, "target_z": -5.5, "stock_z": -4.173}
-  at X55.12 Y-15.62 {"area_mm2": 32.44, "max_excess_mm": 0.499, "feature": null, "target_z": -7.999, "stock_z": -7.5}
-  at X41.88 Y-23.12 {"area_mm2": 6.5, "max_excess_mm": 15.631, "feature": null, "target_z": -15.724, "stock_z": -0.093}

### Flat end mill plunge into solid

- line 29302 `N46460 Z-4.9 F750.` (T3) at X30.471 Y12.829 {"z": -4.9, "depth_into_material": 0.588}
- line 32704 `N63470 Z-23.4 F750.` (T3) at X69.339 Y28.059 {"z": -23.4, "depth_into_material": 0.6}
- line 35839 `N79145 Z-23.4 F750.` (T3) at X-69.485 Y-27.897 {"z": -23.4, "depth_into_material": 0.6}

_83630 segments, grid 648x316 @ 0.25 mm, target from parts/ftc-10/part.stl, runtime 23.73 s_
