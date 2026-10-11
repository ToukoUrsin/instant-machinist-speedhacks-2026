# Simulation report: NIST FTC-10

**Result: FAIL**
Programs: out/run3/fusion/adaptive-L2.5-D24-F0.5/1001.nc

## Cycle time

| | time |
|---|---|
| Cutting (feed) | 29:29.7 |
| Rapid | 0:15.2 |
| Dwell | 0:00.0 |
| Tool change (4 x 4 s) | 0:16.0 |
| **Total** | **30:00.8** (30.01 min) |

| Tool | cutting | rapid | total | feed distance |
|---|---|---|---|---|
| T1 | 0:16.5 | 0:00.2 | 0:20.7 | 858.6 mm |
| T2 | 8:48.8 | 0:08.8 | 9:01.6 | 23595.3 mm |
| T3 | 5:50.5 | 0:04.9 | 5:59.4 | 11192.5 mm |
| T5 | 14:33.8 | 0:01.2 | 14:39.0 | 29180.8 mm |

## Checks

| Check | Result | Detail |
|---|---|---|
| Gouge | OK |  |
| Leftover above tolerance | FAIL | 2360.94 mm2 in 21 regions, max 30.866 mm |
| Rapid into stock | OK |  |
| Flat end mill plunge into solid | FAIL | 3 events |
| Below fixture / vise | OK |  |
| Engagement > flute length (warning) | OK |  |

### Leftover above tolerance

-  at X13.88 Y37.62 {"area_mm2": 2051.12, "max_excess_mm": 30.866, "feature": null, "target_z": -31.0, "stock_z": -0.134}
-  at X28.38 Y18.38 {"area_mm2": 62.12, "max_excess_mm": 0.5, "feature": null, "target_z": -8.0, "stock_z": -7.5}
-  at X40.12 Y25.12 {"area_mm2": 35.75, "max_excess_mm": 1.316, "feature": null, "target_z": -5.5, "stock_z": -4.184}
-  at X51.12 Y25.12 {"area_mm2": 35.75, "max_excess_mm": 1.316, "feature": null, "target_z": -5.5, "stock_z": -4.184}
-  at X55.12 Y-15.62 {"area_mm2": 32.44, "max_excess_mm": 0.499, "feature": null, "target_z": -7.999, "stock_z": -7.5}
-  at X-69.62 Y-25.88 {"area_mm2": 22.25, "max_excess_mm": 4.891, "feature": null, "target_z": -31.0, "stock_z": -26.109}
-  at X70.38 Y-25.88 {"area_mm2": 22.25, "max_excess_mm": 4.891, "feature": null, "target_z": -31.0, "stock_z": -26.109}
-  at X-70.38 Y31.12 {"area_mm2": 22.25, "max_excess_mm": 4.936, "feature": null, "target_z": -31.0, "stock_z": -26.064}
-  at X69.62 Y31.12 {"area_mm2": 22.25, "max_excess_mm": 4.936, "feature": null, "target_z": -31.0, "stock_z": -26.064}
-  at X41.88 Y-23.12 {"area_mm2": 6.5, "max_excess_mm": 15.523, "feature": null, "target_z": -15.724, "stock_z": -0.2}

### Flat end mill plunge into solid

- line 33022 `N65060 Z-4.9 F750.` (T3) at X30.471 Y12.829 {"z": -4.9, "depth_into_material": 0.588}
- line 36424 `N82070 Z-23.4 F750.` (T3) at X69.339 Y28.059 {"z": -23.4, "depth_into_material": 0.6}
- line 39559 `N97745 Z-23.4 F750.` (T3) at X-69.485 Y-27.897 {"z": -23.4, "depth_into_material": 0.6}

_96374 segments, grid 648x316 @ 0.25 mm, target from parts/ftc-10/part.stl, runtime 24.27 s_
