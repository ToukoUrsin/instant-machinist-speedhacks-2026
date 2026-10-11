# Dial: the CAM job phones the metal supplier

Instant Machinist knows the exact stock blank a part needs. When the shop is short, the shop's **Dial** line
(an AI voice agent) calls suppliers, asks the questions a buyer asks (size, qty, cut-to-length, price, lead time,
delivery), accepts the nearest standard size only if it still covers the blank, and gets a quote number.
Opus turns each call transcript into a structured quote; the quotes are compared and logged as typed events.

Demo suppliers are **fictional counters played by Dial inbound agents** on our own Dial numbers
(Pacific Metals Supply, San Leandro; Bay Alloy & Steel, Hayward). We never dial a real business.

## Files
- `source_call.py` main flow: gap -> instruction -> parallel Dial calls -> transcript -> Opus quote -> compare.
- `dial_api.py` minimal REST client (`/api/v1/numbers`, `/calls`, `/account`, `/billing`).
- `personas.py` supplier inbound instructions (stock list, prices, cut charges, lead times, quote-number format).
- `setup_lines.py` idempotent: names the shop line, buys/updates one number per supplier persona, writes `lines.json`.
- `signup.py` REST signup used once (email OTP + phone OTP + coupon); pipes the API key into the environment.
- `evidence/<slug>/` per run: `gap.json`, `outbound_instruction.txt`, `<line>.call.json` (metadata, numbers masked),
  `<line>.transcript.json` (timed turns), `<line>.quote.json`, `summary.json`.
  plus `<line>.recording.mp3` (Dial call recording via `GET /api/v1/calls/{id}/recording`).
- Events: `../out/<slug>/dial.events.jsonl` (`gap`, `calling`, `call_placed`, `call_state`, `call_ended`, `recording`,
  `quote`, `result`; newer events carry a `run` id).
- `segment/` 1-min demo video: `segment.html` (seekable), `build_data.py <slug>`, `render.js`, `make_video.sh`,

## Live runs (2026-10-11, all real Dial calls, both suppliers in parallel)
| Run | Calls | Result |
|---|---|---|
| `evidence/ftc-10/` (primary) | Pacific 212 s, Bay 289 s | Bay Alloy precision-cut blank 1.75 x 3.25 x 6.5 in, $22.60 ($47.60 delivered), 2 d, BAS-41729. Pacific 2 x 4 bar $86.70 delivered, PMS-4279 |
| `evidence/sm-101/run1/` | Pacific 242 s, Bay 300 s (hit cap) | Buyer accepted an under-width Bay blank (3.125 < 3.31 in); Opus flagged `covers_blank=false` and excluded it. Best: Pacific 1-1/4 x 3-1/2 bar, $401.80 delivered, PMS-4172 |
| `evidence/sm-101/` (run 2, tighter buyer prompt) | Bay 280 s, Pacific 300 s | Buyer now checks all 3 dims out loud and rejected Pacific's 1 in bar. Best: Bay 1.125 x 3.5 x 5 in blanks x25, $299.40, BAS-40312 |

## Run
```bash
export XDG_RUNTIME_DIR=/run/user/1000
cd sponsors
python3 dial/setup_lines.py            # once (already done)
python3 dial/source_call.py ../instant-machinist/parts/ftc-10/features.json --dry-run   # show the agent prompt
\
  python3 dial/source_call.py ../instant-machinist/parts/ftc-10/features.json --slug ftc-10
\
  python3 dial/source_call.py ../instant-machinist/out/demo-native/spec.json --slug sm-101
```
Any spec accepted by `shop.material_gap` works (part-agnostic). `--suppliers a,b` picks lines, `--sequential`
places calls one at a time. Calls are capped at 300 s each. A call POST is never retried blindly.

## Account
Dial account `shop@example.com` (created 2026-10-11, coupon `DIAL_FOR_SPEEDHACKS` = $100 credit, expires end of day).
Credentials come from environment variables. Lines: see `lines.json`.
