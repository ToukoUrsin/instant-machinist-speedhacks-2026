# Darwin: gaps we hit, and what would fix them (verified live 2026-10-11)

Evidence: `evidence/ftc-10/`, `evidence/sm-101/`, `evidence/explore.json`, `../out/<slug>/darwin.events.jsonl`.

## What worked
- Search found relevant agents for all 5 needs. 7 capabilities came back for FTC-10 and 8 for SM-101 in the final runs (6–8 across all runs).
- Every MCP/A2A endpoint we could resolve answered live within seconds, through one generic MCP client and one generic A2A client:
  - **SMKlog (A2A)** returned 5 live carrier rates for the stock box: USPS Ground Advantage $8.89, UPS Ground $11.30 (FTC-10, 90058 → 94107).
  - **Costable (MCP)** returned a should-cost of P50 $9.47/unit for FTC-10.
  - whobuildsit, Gemalli, MARS Economic and Webotee connected and listed their tools.
- Custom provider integrations written: 0.

## Gaps
1. **No executable agent for commodity shop supplies.** Darwin's top results for 6061-T6 bar stock were a space/defence directory (whobuildsit) and a general B2B catalog (Gemalli). Live `search_parts`, `search_suppliers` and `search_products` for "6061 aluminum bar" returned **0 hits** on both. Anodizing and heat treating returned no agent at all. Cutting tools returned only an Amazon research server.
   *Fix:* index metals service centers, cut-to-size retailers and industrial MRO/tooling catalogs. Many have public catalogs that could be exposed through WebMCP or an MCP wrapper. Add an "industrial supply / metals" category.
2. **Ranking does not reflect real coverage.** For commodity bar stock, Darwin ranked the defence directory #1–2 with confident `reasons`, but live probes found nothing relevant (its 29 "aluminium" hits are test chambers and vacuum valves).
   *Fix:* feed probe outcomes (hit or miss per query class) back into ranking, or show catalog scope ("space & defence only") in `uncertainties`.
3. **0 of N results thread-ready.** Every result was `readiness: unavailable` and `canStartThread: false`, with `ROUTE_VERIFICATION_EXPIRED` or `EXECUTION_METADATA_PENDING`. Yet the same endpoints answered our live calls in under 2 s.
   *Fix:* re-verify on demand when a result is selected, and expose the time of the last successful verification.
4. **No endpoint in the result.** `connectionMethods` was `[]` for every agent, and the connection prompt said "No independently usable provider endpoint is confirmed". We had to resolve MCP URLs through the official MCP Registry and A2A URLs through the agent card in the owner's website field.
   *Fix:* when a server is public and needs no auth, return `{protocol, url, transport}` in `connectionMethods`.
5. **Execution metadata disagrees with reality.**
   - Webotee is indexed as `auth none`, but its `shopping_search` and `search_products` return HTTP 401.
   - The Shipping Rates calculator is indexed as no-auth, but it only gives live rates to named assistant clients (Claude, ChatGPT, ...).
   - MARS Economic charges USDC per call, but this is visible only in the tool name.
   *Fix:* derive auth, payment and client gating from an actual call receipt, not the manifest.
6. **Search reliability.** The API returned HTTP 500 on **15–16 of 20–21** search calls in each sourcing run (retries and rephrasings recovered all 5 needs), and on **10 of 18** queries in the coverage scan, even after 3 tries. The failures depend on the query: "Anodizing service quote for aluminum parts" and "Simulate or verify CNC G-code" kept failing. Successful calls took 4–8 s. Most of the 65–99 s of search time in a run was spent on retries.
   *Fix:* return `no_match` or degraded results instead of 500, and publish a status signal.
7. **Search asks for consent too early.** For stock, Search answered `needs_input` with "provide your work email and confirm consent to share this request with suppliers". That is an RFQ step, not a discovery step. We never send an email address, so the agent ignores the question and keeps the options.
   *Fix:* keep discovery free of consent prompts and ask for consent at Act time.
8. **Signup friction.** After the magic link, a new email account got 401 "Sign in required" from `/api/customer/me` and looped back to `/signin`. `PUT /me/account-profile` returned 500 for `business` and `software`, then 200 about 20 minutes later, after which application and key creation worked.
   *Fix:* make the post-magic-link account bootstrap atomic, and show an error page instead of looping to sign-in.
9. **Act is pilot-only and in person.** Act needs an `agent:write` pilot grant from Sanjit at the venue, and we were remote. So no Darwin thread was started, and our product connects to the provider directly, read-only.
   *Fix:* self-serve sandbox Act for read-only and quote-only capabilities.
10. **Provider result quality (Costable).** Costable has no 6061 in its material DB. It used "Aluminium 1100 Sheet" and an assumed 2.4 min cycle, so its ~$9.50 is a sanity benchmark, not a quote.
    *Improvement:* Darwin could pass structured job context (alloy, our simulated cycle time) as typed `context` through to the capability's input.

## What it means for the demo
Darwin already removes per-provider integration work: one search, then one MCP client and one A2A client cover every provider. Freight and should-cost questions are answered live today. Stock, tooling and finishing still go to a human buyer. Coverage (1, 2) and readiness/endpoint metadata (3–5) would close most of that gap.
