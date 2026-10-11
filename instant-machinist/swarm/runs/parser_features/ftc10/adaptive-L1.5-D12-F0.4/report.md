# Simulation report: NIST FTC-10

**Result: FAIL**
Programs: out/run3/fusion/adaptive-L1.5-D12-F0.4/1001.nc

## Cycle time

| | time |
|---|---|
| Cutting (feed) | 37:39.9 |
| Rapid | 0:18.3 |
| Dwell | 0:00.0 |
| Tool change (4 x 4 s) | 0:16.0 |
| **Total** | **38:14.2** (38.24 min) |

| Tool | cutting | rapid | total | feed distance |
|---|---|---|---|---|
| T1 | 0:16.5 | 0:00.2 | 0:20.7 | 858.6 mm |
| T2 | 13:26.8 | 0:12.5 | 13:43.3 | 35625.3 mm |
| T3 | 5:50.5 | 0:04.9 | 5:59.4 | 11192.5 mm |
| T5 | 18:06.0 | 0:00.7 | 18:10.7 | 36305.3 mm |

## Checks

| Check | Result | Detail |
|---|---|---|
| Gouge | OK |  |
| Leftover above tolerance | FAIL | 2378.19 mm2 in 21 regions, max 30.929 mm |
| Rapid into stock | OK |  |
| Flat end mill plunge into solid | FAIL | 3 events |
| Below fixture / vise | OK |  |
| Engagement > flute length (warning) | OK |  |

### Leftover above tolerance

-  at X13.88 Y37.62 {"area_mm2": 2068.38, "max_excess_mm": 30.929, "feature": null, "target_z": -31.0, "stock_z": -0.071}
-  at X28.38 Y18.38 {"area_mm2": 62.12, "max_excess_mm": 0.5, "feature": null, "target_z": -8.0, "stock_z": -7.5}
-  at X40.12 Y31.88 {"area_mm2": 35.75, "max_excess_mm": 1.318, "feature": null, "target_z": -5.5, "stock_z": -4.182}
-  at X51.12 Y31.88 {"area_mm2": 35.75, "max_excess_mm": 1.318, "feature": null, "target_z": -5.5, "stock_z": -4.182}
-  at X55.12 Y-15.62 {"area_mm2": 32.44, "max_excess_mm": 0.499, "feature": null, "target_z": -7.999, "stock_z": -7.5}
-  at X-67.38 Y-28.88 {"area_mm2": 22.25, "max_excess_mm": 5.529, "feature": null, "target_z": -31.0, "stock_z": -25.471}
-  at X72.62 Y-28.88 {"area_mm2": 22.25, "max_excess_mm": 5.529, "feature": null, "target_z": -31.0, "stock_z": -25.471}
-  at X-70.38 Y31.12 {"area_mm2": 22.25, "max_excess_mm": 4.933, "feature": null, "target_z": -31.0, "stock_z": -26.067}
-  at X69.62 Y31.12 {"area_mm2": 22.25, "max_excess_mm": 4.933, "feature": null, "target_z": -31.0, "stock_z": -26.067}
-  at X41.88 Y-23.12 {"area_mm2": 6.5, "max_excess_mm": 15.524, "feature": null, "target_z": -15.724, "stock_z": -0.199}

### Flat end mill plunge into solid

- line 46297 `N31445 Z-4.9 F750.` (T3) at X30.471 Y12.829 {"z": -4.9, "depth_into_material": 0.588}
- line 49699 `N48455 Z-23.4 F750.` (T3) at X69.339 Y28.059 {"z": -23.4, "depth_into_material": 0.6}
- line 52834 `N64130 Z-23.4 F750.` (T3) at X-69.485 Y-27.897 {"z": -23.4, "depth_into_material": 0.6}

_125927 segments, grid 648x316 @ 0.25 mm, target from parts/ftc-10/part.stl, runtime 30.8 s_
