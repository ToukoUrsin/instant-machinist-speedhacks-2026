# Darwin sponsor track: sourcing agent

When a CAM job finishes, Instant Machinist knows what the shop is missing: raw stock (from `shop.material_gap`), cutters (from the posted program's tool list), finishing, backup capacity, and freight. `find_sources.py` takes each need to **Darwin Search**, collects and dedupes the agents it returns, connects to each one live through a single generic MCP client and a single generic A2A client (read-only), and has **Claude Opus (`claude-opus-5-5`)** rank the options for this job. No integration is written for any one provider.

Everything is read-only. The script never calls quote, order, checkout or contact tools, and it never sends personal data to a provider.

## Run (from `integrations/`)
```bash
export XDG_RUNTIME_DIR=/run/user/1000
# primary demo part (NIST FTC-10, 1 blank short)
\
  python3 darwin/find_sources.py ../instant-machinist/parts/ftc-10/features.json --slug ftc-10 --part-mass-kg 0.51
# second run (SM-101, 25 blanks short, tool list read from the posted program)
\
  python3 darwin/find_sources.py ../instant-machinist/out/demo-native/spec.json --slug sm-101
python3 darwin/segment_data.py ftc-10        # compact data
python3 darwin/explore.py   # broad machine-shop coverage scan
```
The script works with any spec. Pass any `spec.json` or `features.json` that has the same schema. Other options: `--nc PROGRAM.nc` (tool list), `--no-probe`, `--no-llm`, `--from-zip/--to-zip` (sample ZIPs for the rate probe; defaults are LA 90058 and SF 94107). Without `DARWIN_API_KEY`, Search runs at the anonymous limit.

## Pipeline
1. `shop.material_gap` gives the stock ask. The tool list comes from `(T1 D50. FACE MILL ...)` in the posted NC.
2. Darwin `POST /api/v3/search` runs once per need, with a `context` item. It retries on 500, falls back to rephrased queries, and does one `previousResponseId` refinement when the status is `needs_input`. It never answers with an email address.
3. For each capability the script reads `GET /api/v2/search/capabilities/{id}` (owner, protocols, route decision).
4. **Connect.** Darwin's `connectionMethods` is empty, so MCP endpoints are resolved through the official MCP Registry. For A2A, the script fetches the agent card. It then runs `initialize` and `tools/list` on each server, calls 1–2 read-only search tools with the need's terms, and calls need-specific calculators (Costable `estimate_part`, A2A `get_parcel_quote`).
5. Opus ranks per need: fit, verdict (`ready` / `usable_with_human` / `no_fit`), connect and blocker notes, and the next step.

## Outputs
- `../out/<slug>/darwin.events.jsonl`: typed events for Keewano. Steps: `darwin.start|gap|tools|search|search_error|question|agent|found|connect|probe|live_call|rank|plan|verdict`.
- `evidence/<slug>/plan.json`: full sourcing plan (needs, candidates, live probe results, Opus ranking, metrics).
- `evidence/<slug>/searches/<need>.json`: sanitized Darwin responses (no `searchToken`, no long prompts).
- `evidence/<slug>/probes.json`: every live MCP/A2A call and its result.
- `evidence/<slug>/segment.json`: compact data.
- `evidence/explore.json`: 18-query coverage scan across 9 machine-shop categories.

Files: `find_sources.py` (main), `mcp_probe.py` (minimal streamable-HTTP MCP client), `segment_data.py`, `explore.py`. `tmp/` is gitignored and holds headless sign-in scratch only.

## Secrets
`DARWIN_API_KEY` is the Darwin Search key for application "Instant Machinist" (scope `directory:read`, expires 2027-01-09). It is stored in the environment. `ANTHROPIC_API_KEY` was already there.
