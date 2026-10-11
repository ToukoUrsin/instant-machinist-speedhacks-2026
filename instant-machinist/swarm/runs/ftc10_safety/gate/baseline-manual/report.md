# Simulation report: NIST FTC-10

**Result: FAIL**  
Programs: out/run3/fusion/baseline-manual/1001.nc

## Cycle time

| | time |
|---|---|
| Cutting (feed) | 109:18.2 |
| Rapid | 0:12.0 |
| Dwell | 0:00.0 |
| Tool change (4 x 4 s) | 0:16.0 |
| **Total** | **109:46.2** (109.77 min) |

| Tool | cutting | rapid | total | feed distance |
|---|---|---|---|---|
| T1 | 0:39.1 | 0:00.2 | 0:43.3 | 858.6 mm |
| T2 | 23:14.6 | 0:01.1 | 23:19.7 | 17725.2 mm |
| T3 | 25:09.5 | 0:09.3 | 25:22.8 | 21139.1 mm |
| T5 | 60:15.0 | 0:01.4 | 60:20.4 | 48296.4 mm |

## Checks

| Check | Result | Detail |
|---|---|---|
| Gouge | OK |  |
| Leftover above tolerance | FAIL | 430.75 mm2 in 45 regions, max 15.571 mm |
| Rapid into stock | FAIL | 6 events |
| Flat end mill plunge into solid | FAIL | 4 events |
| Below fixture / vise | OK |  |
| Engagement > flute length (warning) | OK |  |

### Leftover above tolerance

-  at X28.38 Y18.38 {"area_mm2": 62.12, "max_excess_mm": 0.5, "feature": null, "target_z": -8.0, "stock_z": -7.5}
-  at X22.38 Y6.38 {"area_mm2": 51.31, "max_excess_mm": 1.967, "feature": null, "target_z": -7.607, "stock_z": -5.64}
-  at X22.38 Y-6.38 {"area_mm2": 40.81, "max_excess_mm": 1.967, "feature": null, "target_z": -7.607, "stock_z": -5.641}
-  at X-63.12 Y37.38 {"area_mm2": 38.38, "max_excess_mm": 0.969, "feature": null, "target_z": -23.469, "stock_z": -22.5}
-  at X63.12 Y37.38 {"area_mm2": 38.38, "max_excess_mm": 0.969, "feature": null, "target_z": -23.469, "stock_z": -22.5}
-  at X-60.38 Y-37.38 {"area_mm2": 37.75, "max_excess_mm": 0.905, "feature": null, "target_z": -8.405, "stock_z": -7.5}
-  at X40.12 Y30.12 {"area_mm2": 35.75, "max_excess_mm": 1.316, "feature": null, "target_z": -5.5, "stock_z": -4.184}
-  at X51.12 Y30.12 {"area_mm2": 35.75, "max_excess_mm": 1.316, "feature": null, "target_z": -5.5, "stock_z": -4.184}
-  at X39.88 Y-31.38 {"area_mm2": 32.5, "max_excess_mm": 0.499, "feature": null, "target_z": -7.999, "stock_z": -7.5}
-  at X41.88 Y-23.88 {"area_mm2": 6.5, "max_excess_mm": 15.571, "feature": null, "target_z": -15.724, "stock_z": -0.152}

### Rapid into stock

- line 15784 `N78860 G0 Z-4.046` (T3) at X28.125 Y38.125 {"depth": 0.246}
- line 16234 `N81110 G0 Z-4.457` (T3) at X28.375 Y38.375 {"depth": 0.657}
- line 16578 `N82830 G0 Z-4.851` (T3) at X28.375 Y39.125 {"depth": 1.051}
- line 16920 `N84540 G0 Z-5.179` (T3) at X28.625 Y38.375 {"depth": 1.379}
- line 17611 `N87995 G0 Z-6.011` (T3) at X28.875 Y38.625 {"depth": 2.211}
- line 17753 `N88705 G0 Z-6.5` (T3) at X29.125 Y38.625 {"depth": 2.7}

### Flat end mill plunge into solid

- line 19589 `N97885 Z-23.5 F300.` (T3) at X68.848 Y-29.545 {"z": -23.5, "depth_into_material": 0.65}
- line 21180 `N5850 Z-23.5 F300.` (T3) at X69.406 Y27.062 {"z": -23.5, "depth_into_material": 0.65}
- line 24888 `N24390 Z-23.5 F300.` (T3) at X-68.895 Y29.595 {"z": -23.5, "depth_into_material": 0.65}
- line 26482 `N32360 Z-23.5 F300.` (T3) at X-69.512 Y-27.087 {"z": -23.5, "depth_into_material": 0.65}

_116030 segments, grid 648x316 @ 0.25 mm, target from parts/ftc-10/part.stl, runtime 38.8 s_
