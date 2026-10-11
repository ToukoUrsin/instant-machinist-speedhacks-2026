# Keewano: the shop's memory, and the agent that plans from it

**Keewano project: `Instant Machinist Shop Floor`** (id `3c71f27a-eb5c-4a7d-ac74-6cab42e77661`, org , signed up
as shop@example.com; `#SpeedHacks` unlock sent in the in-app chat on 2026-10-11).

Every CAM job (drawing in, verified G-code out) and every integration step around the order (Darwin sourcing, Dial supplier
calls and quotes, Sparta deposit-invoice tests) becomes small typed Keewano events. **Shop Brain** (Claude Opus 5.5) has no
memory of its own. It answers shop questions and plans the next job only from live Keewano SQL (through the Keewano MCP server),
then writes its decision back to Keewano. Remove Keewano and Shop Brain cannot rank strategies, pick a supplier or name the
bottleneck. It has no other data.

## Loop
1. `ingest.py` maps `instant-machinist/out/*/events.jsonl`, `runs/*/events.jsonl` and `integrations/out/<part>/<sponsor>.events.jsonl`
   to 47 typed custom events (ids 2000–2046: `Part`, `Strategy`, `CycleSeconds`, `StrategyVerified`, `VerifyCheckFailed`,
   `JobProgrammedSeconds`, `BaselineCycleSeconds`, `BestCycleSeconds`, `BlanksShort`, `Supplier`, `SupplierQuotedCents`,
   `SupplierLeadDays`, `StepName`/`StepSeconds`, `AgentDecision`, ...). Entities: one per CAM job, one per (part, sponsor agent),
   one per agent decision. It is idempotent: `runtime/ledger.json` stores the last timestamp sent per entity, and every
   timing event is emitted at its own event, so a re-run only sends what is new and never double counts.
2. `shop_brain.py ask "<question>"`: Opus plus two tools, `sql` (Keewano `run_sql_query` over MCP) and `event_types`.
   It prints the answer and saves the question, every SQL statement, its result and the answer to `evidence/`.
3. `shop_brain.py decide --part <dir> [--run]`: for a new part, Shop Brain queries Keewano for (a) the strategies that won and
   passed verification on the most similar past parts, (b) the supplier with the best delivered price against lead time, (c) the
   slowest step and (d) before and after. It returns a plan: a strategy shortlist, a supplier and the bottleneck. With `--run`
   it runs the real core pipeline with the CAM variant search **limited to that shortlist** (`shim/sitecustomize.py`). The
   outcome lands in `runs/` and is ingested, and the decision itself is written back as `AgentDecision` events. The next
   decision can then check how the last one turned out.

## Run
```bash
cd integrations/keewano
export XDG_RUNTIME_DIR=/run/user/1000
python3 ingest.py                 # send new events (python3 ingest.py --dry-run to preview)
python3 shop_brain.py ask "Which supplier for the FTC-10 blank?"
python3 shop_brain.py decide --part runs/parts/sm-107 --run
python3 ingest.py                 # push the agent-planned job's outcome
python3 segment_data.py               # live numbers -> demo/segment.json
```
New events can take about 5 minutes to become queryable. Needs the core venv (`instant-machinist/.venv`) for `--run`, plus
`anthropic` (system python3).

Secrets: `KEEWANO_API_KEY` (project SDK key, ingest), `KEEWANO_PAT` (personal access token, MCP/SQL),
`KEEWANO_PASSWORD` (account login, headless browser only), `ANTHROPIC_API_KEY`.

## What is real
- CAM jobs: `instant-machinist/out/{demo-native,readme-native,run1,run2,run3}` are core pipeline runs. `run3` is NIST FTC-10 on
  Autodesk Fusion. `runs/*` are native-engine pipeline runs made here, with real CAM and real simulator verification.
- **Disclosed:** parts SM-102…SM-107 (`runs/parts/`, made by `tools/make_variants.py`) are geometry variants derived from
  SM-101 so the history holds more than one plate. Their events carry `DataSource = "variant_part"`, and every cycle time and
  verification result for them comes from real runs. SM-105's variant geometry put two holes outside the shrunken pocket, and
  the simulator caught it as a gouge. That is a real failure and is kept in the data.
- `ManualProgrammingEstimateSeconds` = 14 400 s (4 h) is the shop's stated estimate for manual CAM programming, not a
  measurement. Darwin's `SourcingManualEstimateSeconds` is Darwin's own estimate.
- Sparta events are reliability tests of the deposit-invoice agent in a simulated Stripe world (`DataSource = "agent_test"`),
  not real invoices.
- No `demo_seed` or back-filled synthetic history was sent.

## Files
`ingest.py` · `shop_brain.py` · `kmcp.py` (minimal Keewano MCP client, Streamable HTTP) · `segment_data.py` · `shim/` ·
`tools/make_variants.py` · `runs/` (job outputs; sims and G-code gitignored) · `evidence/` (live Q&A with SQL) ·
scripts, the ingest ledger and a cached copy of the SQL guide.
