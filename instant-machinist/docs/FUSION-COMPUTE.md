# Driving Autodesk Fusion in the cloud (Fusion Compute MCP)

The Fusion path gives shops a normal, editable Fusion document with the model, setup, operations and
NC program inside. Programmers can open it, review it and change it like any job they built
themselves. No desktop Fusion runs anywhere. Every step happens in a headless Fusion instance in
Autodesk's cloud, which we reach through the **Fusion Compute MCP server** (public beta):

```
https://developer.api.autodesk.com/da/v3/mcp/fusion
```

Code: [`instant_machinist/fusion/`](../instant_machinist/fusion).

| File | Role |
|---|---|
| `mcp_client.py` | Minimal MCP client over Streamable HTTP: JSON-RPC 2.0, protocol `2025-06-18`, `mcp-session-id` header, plain JSON or SSE responses, OAuth bearer token with automatic refresh. |
| `session.py` | `start_fusion` / `fusion_status` / `stop_fusion` / `invoke_fusion`, plus `ts(code)`, which runs TypeScript in Fusion through `MCP.ExecuteTypeScript` and returns the script's JSON result. |
| `build.py` | Builds a script from `ts/common.ts` + JSON constants (`const FEATURES: any = {...}`) + a module + a call. The result comes back through `adsk.result = JSON.stringify(...)`, together with a `LOG` array. |
| `ts/model.ts` | Spec → parametric 3D model. |
| `ts/importstep.ts` | Customer STEP → oriented for machining: rotate to Z-up, top centre at the origin. |
| `ts/cam.ts` | 2.5D setup, tools, operations, toolpath generation, Haas post, tool table. |
| `ts/cam3d.ts` | 3D OP1 for an imported STEP: face, 3D adaptive or pocket clearing, contour wall finish, ball-end parallel finish; per-operation generation. |
| `program.py` | `FusionProgrammer`: `import_step()` or `model()` → `program3d()` / `program()` one strategy → post → writes `1001.nc`, `tools.json`, `ops.json`; screenshot; save. |
| `strategies.py` | Baselines and adaptive variants the optimizer tries: 2.5D (`BASELINE`, `VARIANTS`) and 3D (`BASELINE_3D`, `VARIANTS_3D`, adding a 6 mm ball end mill and finish stepover). |

## Authentication

The Fusion Compute MCP uses OAuth 2.1 (authorization code + PKCE). Sign in once with an Autodesk
account that has Fusion. The token endpoint is `https://developer.api.autodesk.com/mcpauth/v1/token`
and the resource is the MCP endpoint above. Store the token response, plus an `obtained` Unix
timestamp, as JSON at **`~/.adsk/token.json`** (mode 600), or point `IM_FUSION_TOKEN` at another path:

```json
{"access_token": "…", "token_type": "Bearer", "expires_in": 3599, "refresh_token": "…", "obtained": 1791748000}
```

`mcp_client._load_token()` refreshes the access token with the refresh token 2 minutes before it
expires and rewrites the file with mode 600. No secret is stored in this repository. The drawing
reader needs `ANTHROPIC_API_KEY` in the environment.

Save location: `FusionProgrammer.save()` writes to a Fusion Team folder URN (`DEFAULT_FOLDER` in
`program.py`). Pass your own `folder_urn` to save in your team's project.

## STEP input: NIST FTC-10 (headline run `out/run3`)

When the customer sends a STEP model, it goes straight into cloud Fusion and nothing is rebuilt:

1. **Start Fusion.** `start_fusion` with a fresh engine session id (`im-<unix time>`), then poll
   `fusion_status` until it reports `active`.
2. **Import the STEP.** `MCP.IO` with `mode: "import"`, `format: "step"` and a `downloadUrl`. Fusion
   downloads the customer's file itself, so it never passes through the MCP message. The part's
   `features.json` carries the URL (`step_url`).
3. **Orient for machining** (`importstep.ts`, `orientImported(rotX)`). The NIST file is Y-up, so it is
   rotated +90° about X (`step_rot_x_deg`). Then it is translated so the top centre of the part is the
   origin and Z = 0 is its highest point, the same convention as everything else. FTC-10 comes in
   with 214 faces and 188.3 cm³, a 158 × 75 × 31 mm box.
4. **Program OP1, the top side** (`cam3d.ts`, `program3d(FEATURES, STRATEGY)`):
   - A setup with stock offsets from the spec (162 × 79 × 39.5 mm blank). WCS at the top centre, G54.
   - **Face** (50 mm face mill).
   - **3D adaptive clearing** (10 mm flat end mill, optimal load and max stepdown from the variant,
     0.3 mm radial / 0.2 mm vertical stock to leave, down to the model bottom). The baseline uses 3D
     pocket clearing instead (4 mm stepover, 2 mm steps).
   - **Finish walls** (contour, 6 mm flat end mill, 1 mm steps; 0.5 mm for the baseline).
   - **Finish fins** (parallel, 6 mm ball end mill, 0.4–0.6 mm stepover; 0.3 mm for the baseline).
5. **Generate one operation at a time** (`genOp(i, 25000)`). Python calls it repeatedly, 25 s slices
   with up to 240 s per operation. Toolpath generation only advances while a script is running, so
   one long blocking call is avoided. 3D adaptive takes about 10–11 s for the winner; all 4 operations
   take 21–34 s per strategy.
6. **Post** with `HAAS (pre-NGC)` (76k–113k lines per program), export the tool table, and verify
   with our simulator against the STEP-derived mesh `parts/ftc-10/part.stl`.
7. **Save** the winning strategy: `MCP.Documents` `saveAs` → `"NIST FTC-10 - Instant Machinist"` in
   Fusion Team.

Measured (`out/run3/events.jsonl`): session start + STEP import + orientation in 9.7 s; 5 strategies
programmed, posted and verified; the file saved. Total **7:08**, including Claude's 28.5 s read of the
5-page drawing.

## 2.5D from the spec: SM-101 (run `out/run2`)


1. **Start Fusion.** `start_fusion` with a fresh engine session id, then poll `fusion_status`
   until the status is `active`.
2. **New document, model from spec** (`model.ts`, `buildPart(FEATURES)`). The outline is a sketch on
   XY extruded to the part thickness. Each pocket is a rounded-rectangle sketch on an offset
   construction plane at its `z_top`, cut down to `z_bottom`. Holes are circle sketches cut through,
   0.5 mm past the bottom. For SM-101 this gives 30 faces and 167.5 cm³: 452 g in 6061, against the drawing's 0.45 kg reference weight.
3. **Screenshot** with `MCP.IO` (`screenshot`, `isoTopRight`, signed URL) → `model.png`.
4. **Program a strategy** (`cam.ts`, `program(FEATURES, STRATEGY)`):
   - One milling setup on the body. Stock offsets come from the spec's stock box against the part box.
     WCS is the model's top centre, work offset G54.
   - Tools from Fusion's `Samples/Milling Tools (Metric)` library, matched by description and
     renumbered T1–T4: 50 mm face mill, 10, 6 and 5 mm flat end mills. Spindle speed and cutting /
     entry / exit / plunge / ramp feeds come from the strategy.
   - Operations: Face → **Adaptive clearing** (optimal load and max stepdown from the variant; 0.2 mm
     radial, 0 mm vertical stock to leave) or, for the baseline, 2D pocket + 2D contour roughing →
     Slot (2D pocket, Ø6) → Finish pocket walls (2D contour, chain reversed) → Finish outside profile
     → Bore holes (Ø5 end mill).
   - Geometry is selected from the B-rep: planar faces by Z level (pocket floor, slot floor, part
     bottom), hole cylinders by diameter.
   - `generateAllToolpaths`, polled until done (90 s cap). Each operation reports
     `hasToolpath && isToolpathValid`, its warning and its error.
5. **Post** (`post("1001")`). Fusion's library post `HAAS (pre-NGC)`, millimetres, output to
   `cam.temporaryFolder`. The script waits while `app.hasActiveJobs`, then reads the `.nc` back with
   `fs.readFileSync`.
6. **Tool table** (`toolTable`): diameter, flutes, flute length and type of each tool, converted to
   our simulator's `tools.json`.
7. **Verify** the posted program with our simulator (see [VERIFIER.md](VERIFIER.md)). Repeat 4–7 for
   every strategy variant.
8. **Re-program the winner and save.** `MCP.Documents` `saveAs` to Fusion Team as
   `"SM-101 - Instant Machinist"`, so the saved document holds the verified strategy.

Measured on SM-101 (`out/run2/events.jsonl`): model built 5.6 s after the session start request.
Each strategy takes about 20 s for toolpath generation (1.7–6.2 s inside Fusion), post (about 8 s)
and our verification (1.3–2.7 s). Programming plus saving the file took 2:34 in total, including the
22 s drawing read.

## Gotchas we hit (and how the code handles them)

| Gotcha | Handling |
|---|---|
| The Fusion API works in **centimetres**. | `common.ts` defines `MM = 0.1`. Every coordinate goes through `P(x, y, z)` and every length is multiplied by `MM`. |
| Unknown CAM parameter names are not an error: the value never applies. | `addOp` and `sp()` push `"no param X"` / expression errors into `LOG`, which every script returns. The first SM-101 program's slot used two such names; it came out 7 mm wide instead of 8 ([VERIFIER.md](VERIFIER.md#example-what-the-verifier-caught-in-fusions-first-sm-101-program)). |
| Some operation parameters only take effect after the operation exists. | `addOp` sets every parameter on the `OperationInput` and again on the created operation. |
| A 2D contour's cutting side follows the chain direction. A pocket wall chain taken from the floor's outer loop cuts **outside** the pocket. | `selChain(..., reverse=true)` sets `isReverted` for the pocket wall finish. Our verifier found this as an 8 mm gouge at `N37935`. |
| Floor stock to leave silently keeps the 0.2 mm finishing allowance. | `verticalStockToLeave: '0 mm'` is set explicitly on every roughing operation and the slot. |
| Design Automation has no in-process stock: face reports *"In-process stock calculation is not available in Design Automation for Fusion"* and adaptive warns *"Failed to generate rest material"*. The toolpaths are still valid. | Operations use `useStockContours: false` and machine from the setup stock. The stock state is tracked by **our** simulator, not Fusion's. |
| Toolpath generation and posting are asynchronous. | `wait(ms)` spins on `adsk.doEvents()`; the script polls `isGenerationCompleted` and `app.hasActiveJobs`. |
| The posted file name varies (`1001` or `1001.nc`). | `post()` tries both and returns the folder listing in `LOG` if neither exists. |
| `fusion_status` returns JSON text; an early string match missed `"status": "active"`. | The status check normalises the JSON spacing before matching. |
| The first cloud Fusion start of the day took 5 min 28 s to a built model in an early run. Later starts took 6–10 s (start + STEP import 9.7 s on FTC-10). | Each run uses its own engine session id (`im-<unix time>`), so runs never share document state. |
| A customer STEP arrives in whatever orientation its CAD system used (FTC-10 is Y-up). | `orientImported()` rotates by the part's `step_rot_x_deg` and moves the top centre to the origin. Simulator, setup and drawing then share one coordinate frame. |
| 3D toolpath generation stalls between script calls: it only advances while a script pumps events. | `genOp()` generates one operation per call in 25 s slices; Python repeats the call until `isGenerationCompleted`. |
| A program's toolpaths can each be valid and still collide with what the earlier operations left (FTC-10 baseline: 6 rapids into stock). | Verified by our material-aware simulator, since Design Automation has no in-process stock. |
| Screenshot delivery is a signed URL, not inline bytes. | `FusionProgrammer.screenshot` downloads the URL; the output directory is created up front. |

## Run it

```bash
export ANTHROPIC_API_KEY=...            # drawing read
# token at ~/.adsk/token.json (see Authentication)
.venv/bin/python -m instant_machinist.pipeline --part parts/ftc-10 --engine fusion --out out/ftc-10   # STEP + drawing
.venv/bin/python -m instant_machinist.pipeline --part parts/sm-101 --engine fusion --out out/sm-101   # 2.5D from the drawing
# --no-read  skip the drawing read (use features.json)
# --no-video skip the simulation video
```

Outputs per strategy in `out/<job>/fusion/<strategy>/`: `1001.nc` (Haas G-code), `tools.json`,
`ops.json` (operations, validity, Fusion warnings), and `sim/` (verifier report, maps, video data).
Plus `out/<job>/summary.json`, `events.jsonl`, `spec.json`, and the Fusion document in Fusion Team.
