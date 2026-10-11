// Check-suite fixture only (not the agent): hard-coded correct writes for the ftc10 missions,
// used to prove the checks pass for a known-correct world and fail for a no-op / wrong one.
// Usage (from the project dir): node ../../tools/reference_solution.mjs [deposit|ambiguous|noop|wrong-customer]
const B = process.env.WORLDS_BASE_URL, H = { authorization: "Bearer " + process.env.WORLDS_API_KEY };
const mode = process.argv[2] || "deposit";
async function call(method, path, body, json = false) {
  for (let i = 0; i < 3; i++) {
    const r = await fetch(B + path, { method, headers: { ...H, "content-type": json ? "application/json" : "application/x-www-form-urlencoded", "idempotency-key": "ref-" + method + path + JSON.stringify(body) }, body: body ? (json ? JSON.stringify(body) : new URLSearchParams(body).toString()) : undefined });
    const b = await r.json();
    if (r.ok) return b;
    if (r.status < 500) throw new Error(path + " " + r.status + " " + JSON.stringify(b));
  }
}
if (mode !== "noop") {
  const cus = mode === "wrong-customer" ? "cus_kestrel_sys" : "cus_kestrel";
  if (mode === "ambiguous") {
    await call("PUT", "/api/v2/tickets/2.json", { ticket: { status: "pending", tags: ["rfq", "needs-info"], comment: { body: "Which company should we invoice?", public: true } } }, true);
  } else {
    for (const [price, quantity] of [["price_vmc3_min_2026", 100], ["price_6061_cuin", 344], ["price_setup", 3], ["price_program_sim", 1]])
      await call("POST", "/v1/invoiceitems", { customer: cus, price, quantity });
    await call("POST", "/v1/invoiceitems", { customer: cus, amount: -43710, currency: "usd", description: "Balance due on delivery (50%)" });
    const inv = await call("POST", "/v1/invoices", { customer: cus, currency: "usd" });
    console.log("invoice", inv.id, inv.total);
    await call("PUT", "/api/v2/tickets/1.json", { ticket: { status: "pending", tags: ["rfq", "quoted"], comment: { body: "Quote 874.20, deposit 437.10, draft " + inv.id, public: true } } }, true);
  }
}
console.log("done", mode);
