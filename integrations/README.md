# Shop-floor integrations

Programming the part is one step of a job. These integrations carry the same job through the rest of
the shop: material, suppliers, billing, and the shop's memory. Each one reads the core pipeline's
outputs (`instant-machinist/out/<run>/spec.json`, `events.jsonl`, `summary.json`) and never changes
the core, so the CAM engine stays independently testable.

```
CAM job (spec.json) ──► shop/material_gap.py ──► what stock is missing
                                   │
            ┌──────────────────────┼─────────────────────────┐
            ▼                      ▼                         ▼
   Darwin: find a sourcing   Dial: phone suppliers     Sparta: test the quote →
   / freight provider        for live quotes           deposit-invoice agent
            └──────────────────────┼─────────────────────────┘
                                   ▼
             Keewano: every step as typed events; ask the shop questions
             Alike: shared memory for the agents that built all of this
```

| Integration | What it does for the job | Evidence |
|---|---|---|
| [Darwin](darwin/) | Searches 5 shop needs for the FTC-10 job; connects read-only to 7 providers with 0 custom integrations; live freight rate ($8.89) and should-cost | `darwin/evidence/` |
| [Dial](dial/) | AI shop line phones two suppliers in parallel; 6 live calls; best FTC-10 quote $47.60 | `dial/evidence/` (recordings, transcripts) |
| [Sparta](sparta/) | Quote → 50 % deposit-invoice agent tested in a deterministic Stripe-style world. v1 double-bills on retry (9/28 checks fail); v2 idempotency fix passes 3/3 reruns plus interruption, crash and ambiguous cases | `sparta/evidence/traces/` |
| [Keewano](keewano/) | ~11.9k typed shop events; `shop_brain.py` answers plain-English questions and shortlists CAM strategies from verified past runs | `keewano/evidence/` |
| [Alike](alike/) | Shared decisions and live work for the many Claude Code and Codex sessions that built this repo in one day | `alike/evidence/` |

## Layout
- `shop/`: `material_gap.py` (+ `shop_inventory.json`). `python3 -m shop.material_gap <spec.json>` → gap JSON.
- `<name>/`: code, `README.md` (how to run) and `evidence/` from real runs.
- `out/<job>/<name>.events.jsonl`: typed events in the same shape as the core events (`t, ts, step, msg` + typed fields). Keewano ingests these together with the core `events.jsonl`.

API keys are read from environment variables; none are stored in this repository.
