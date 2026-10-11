# Module contracts

All units mm. Part origin: top-center of the finished part, Z=0 = finished top face, Z negative down.
Python: `.venv/bin/python` (3.12, numpy, scipy, shapely, trimesh, cadquery, matplotlib, anthropic, pytest).

## Inputs (per part, `parts/<id>/`)
- `features.json` — 2.5D feature list (face, profile, pocket, hole); see parts/sm-101/features.json.
- `tools.json` — tool crib keyed by T number (type flat|face_mill|spot_drill|drill|ball, diameter, flutes, tip_angle, flute_length).
- `part.step`, `part.stl`, `drawing.png`, `drawing.pdf` — made by `instant_machinist/parts/` generator.

## G-code dialect (what every CAM path emits and the simulator accepts)
Haas-style ISO: G20/G21, G90/G91, G17, G0/G1/G2/G3 (I/J/K centre, or R), G43 H, G54, G28 G91 Z0,
T# M6, S M3/M4/M5, F (per minute, G94), M8/M9, canned cycles G81/G82/G83/G73 with R/Q/Z/P, G80,
G98/G99, comments in parentheses, N numbers optional, O program number, %. Multiple programs (one per setup) allowed.

## Simulator output (`instant_machinist/sim`) → renderer input
`out/<job>/sim/frames.npz`:
- `x0, y0, cell` (float) grid origin (cell centre of [0,0]) and pitch; `heights` float32 (F, ny, nx) stock top Z per frame (NaN = no material)
- `stock_z_bottom` float; `tool_pos` (F,3) tool tip; `tool_id` (F,) int; `tool_diam` (F,) float; `nc_line` (F,) int; `t_sec` (F,) cumulative machine time
- `final_gouge` (ny,nx) bool, `final_leftover` (ny,nx) bool
`out/<job>/sim/toolpath.npz`: `points` (N,3), `rapid` (N,) bool, `tool_id` (N,) int, `nc_line` (N,) int
`out/<job>/sim/report.json` + `report.md`: cycle time (cutting, rapid, tool change, total), per-tool time, checks
(gouge, leftover above tolerance, rapid into stock, plunge with flat end mill into solid, below-fixture Z), each with NC line + XY.
