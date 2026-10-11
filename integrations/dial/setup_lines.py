"""Idempotent line setup: shop agent line (the signup number) + one Dial number per demo supplier persona.
Writes non-secret line metadata to dial/lines.json. Buying a number costs $20 of Dial credit (coupon-funded).

  python3 setup_lines.py
"""
import json, pathlib
import dial_api as d
from personas import SUPPLIERS, SHOP_LINE, SHOP_INBOUND

OUT = pathlib.Path(__file__).parent / "lines.json"
CONSENT = "the team Ursin (account owner) authorized buying demo numbers for SpeedHacks 2026-10-11"


def main():
    nums = d.numbers()
    by_nick = {n.get("nickname"): n for n in nums}
    lines = {}
    shop = by_nick.get(SHOP_LINE) or next((n for n in nums if not n.get("nickname")), None)
    if shop is None:
        raise SystemExit("no free number for the shop line")
    d.update_number(shop["id"], nickname=SHOP_LINE, inboundInstruction=SHOP_INBOUND, inboundLanguage="en-US")
    lines["shop"] = {"nickname": SHOP_LINE, "id": shop["id"], "number": shop["number"]}
    for nick, p in SUPPLIERS.items():
        n = by_nick.get(nick)
        if n is None:
            n = d.provision(nick, p["instruction"], CONSENT, area_code="510", voice=p["voice"])
        else:
            d.update_number(n["id"], inboundInstruction=p["instruction"], inboundVoiceGender=p["voice"],
                            inboundLanguage="en-US")
        lines[nick] = {"nickname": nick, "id": n["id"], "number": n["number"], "persona": p["name"]}
    OUT.write_text(json.dumps(lines, indent=1))
    print(json.dumps(lines, indent=1))


if __name__ == "__main__":
    main()
