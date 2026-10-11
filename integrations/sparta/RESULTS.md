# Results: RFQ → 50% deposit invoice agent in Sparta Worlds

Same seed, missions and 28 (deposit) / 25 (ambiguous) declarative checks for every row. Model `claude-opus-5-5`,
generated limits (12 steps, 1024 tokens per turn, 120 s). `x/y` = passed fresh worlds / runs. Token and time columns are
per run, summed over all agent processes in that run (double = 2 deliveries; crash rows count only the redelivered process).

| Mission | Condition | Agent | Pass | Invoices / items created | Draft total | Ticket after run | Tokens per run (in/out) | Agent time per run | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| ftc10-ambiguous | normal | v1 | 1/1 | 0 / 0 | none | #2 pending rfq+needs-info, 1 reply | 16,772 / 1,220 | 14 s | `evidence/v1-ambiguous-normal.json` |
| ftc10-ambiguous | normal | v2 | 1/1 | 0 / 0 | none | #2 pending rfq+needs-info, 1 reply | 8,553 / 429 | 6 s | `evidence/v2-ambiguous-normal.json` |
| ftc10-deposit | normal | v1 | 1/1 | 1 / 5 | $437.10 | #1 pending rfq+quoted, 1 reply | 53,777 / 2,383 | 26 s | `evidence/v1-deposit-normal.json` |
| ftc10-deposit | normal | v2 | 3/3 | 1 / 5 | $437.10 | #1 pending rfq+quoted, 1 reply | 19,346 / 925 | 11 s | `evidence/v2-deposit-normal-x3.json` |
| ftc10-deposit | interruption | v1 | 1/1 | 1 / 5 | $437.10 | #1 pending rfq+quoted, 1 reply | 61,065 / 2,538 | 28 s | `evidence/v1-deposit-interruption.json` |
| ftc10-deposit | interruption | v2 | 3/3 | 1 / 5 | $437.10 | #1 pending rfq+quoted, 1 reply | 19,018 / 861 | 11 s | `evidence/v2-deposit-interruption-x3.json` |
| ftc10-deposit | crash | v1 | 3/3 | 1 / 5 | $437.10 | #1 pending rfq+quoted, 1 reply | 53,947 / 2,317 | 25 s | `evidence/v1-deposit-crash-x3.json` |
| ftc10-deposit | crash | v2 | 1/1 | 1 / 5 | $437.10 | #1 pending rfq+quoted, 1 reply | 19,066 / 904 | 11 s | `evidence/v2-deposit-crash.json` |
| ftc10-deposit | crash-late | v1 | 1/1 | 1 / 5 | $437.10 | #1 pending rfq+quoted, 1 reply | 33,962 / 1,853 | 20 s | `evidence/v1-deposit-crash-late.json` |
| ftc10-deposit | crash-late | v2 | 1/1 | 1 / 5 | $437.10 | #1 pending rfq+quoted, 1 reply | 20,107 / 928 | 32 s | `evidence/v2-deposit-crash-late.json` |
| ftc10-deposit | double | v1 | 0/1 | 1 / 10 | $874.20 | #1 open rfq, 0 reply, 2 notes | 184,845 / 7,316 | 84 s | `evidence/v1-deposit-double.json` |
| ftc10-deposit | double | v2 | 3/3 | 1 / 5 | $437.10 | #1 pending rfq+quoted, 1 reply | 38,336 / 1,689 | 22 s | `evidence/v2-deposit-double-x3.json` |

## Time-saving value
- **Who:** the estimator / office person in a small CNC job shop, after Instant Machinist has produced the verified program.
- **Manual baseline (estimate, not measured):** ~15–20 min per RFQ to match the requester to the billing account, price 4 lines
  from the rate card, compute the 50% deposit, key the invoice lines and draft in Stripe, and write the quote reply.
- **Agent (measured, v2):** ~11 s and ~19k input tokens per RFQ (v2 normal x3); the human reviews one draft and one reply.
- **Risk removed:** the double-delivery failure below would have sent a "deposit" for the full $874.20 instead of $437.10.

## Failure → fix → rerun
1. **Failure (v1, `evidence/v1-deposit-double.json`).** Help-desk triggers and job queues deliver at least once; we delivered the
   same RFQ job twice, 1.5 s apart. Both v1 processes read an empty world, then both wrote: 10 invoice items, and the one draft
   that succeeded (`in_kYxqgoufIDRm5wOb`) collected all of them: **$874.20**, the full quote billed as the deposit. The second
   draft call got "Nothing to invoice". Both deliveries saw the mess and wrote internal notes; ticket 1 stayed open with **no
   reply** to the customer. 9 of 28 checks failed (the ID-pinned draft checks fail because the correct draft never existed;
   the bad draft is for the right customer but has the wrong total and 10 lines).
   v1 had passed normal, Sparta's interruption and crash-mid-job (3/3) because the model noticed leftovers after a crash.
   Concurrent duplicates are invisible to it: neither process can see the other's in-flight writes.
2. **Fix (v2, `agent/quote-agent.mjs`).** Idempotency keys derived from the job (mission + ticket + customer + line + hash of
   price/qty), so any second delivery replays the first delivery's writes. A delivery whose draft write comes back
   `idempotent-replayed` does not own the job: it waits up to 20 s for the owner's reply and posts it only if the owner died
   (`crash-late` row: worker killed right after creating the draft; redelivery took over after the wait). Money math moved
   into code (model selects price IDs only); context prefetched in one read pass; bounded retries with the same key.
3. **Rerun (v2, `evidence/v2-deposit-double-x3.json`), same conditions:** 3/3. Per run, delivery 2's 5 item writes and its
   draft write all came back `idempotent-replayed: true` (18 replays in `evidence/traces/v2-deposit-double-x3.jsonl`); one
   draft `in_MslT6GOQaeLYFM7h` with 5 lines totalling **$437.10**; ticket 1 pending + quoted with exactly one reply.
   Normal and interruption 3/3; ambiguous still asks which Kestrel instead of billing a guess; ~3× fewer tokens, ~2.4× faster.

## Check-suite validation (no model)
`tools/reference_solution.mjs`: correct writes pass both missions; no-op fails both; billing the decoy customer fails
"right customer"; billing on the ambiguous ticket fails 6 checks.

## Not claimed
- FTC-10 cycle time is an **assumed** 600 s/part (no verified core simulation for FTC-10 yet); material uses the shop's own rate card.
- v2 crash, crash-late and ambiguous ran once each (`--runs 3` was used for normal, interruption and double).
- `evidence/exploratory/` = first v1/v2 runs before the reply-count check / final limits; `evidence/superseded/` = v2 runs
  before the last tool-note wording change. Kept for honesty, not used in the table.
