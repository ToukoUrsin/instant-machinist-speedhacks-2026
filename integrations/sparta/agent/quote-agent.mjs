// Instant Machinist quote agent, v2.
// RFQ ticket + Instant Machinist job card -> priced quote -> one 50% deposit draft invoice -> ticket reply.
// Claude decides (which ticket, which customer, which catalog prices, or ask for clarification);
// code does the money math and every write, with stable idempotency keys so a crashed or redelivered
// job can never bill twice. Node 24+, no npm dependencies.
// Env: WORLDS_BASE_URL, WORLDS_API_KEY, WORLDS_TASK_JSON (runner); ANTHROPIC_API_KEY (the environment); WORLDS_MODEL.
//
// Changes from v1 (agent/v1/quote-agent.mjs), each made in response to a test result (see RESULTS.md):
//  1. Writes carry idempotency keys derived from the job (ticket + line), not from the process, so a
//     redelivered or doubly delivered job replays the first delivery's writes instead of creating copies
//     (v1 failed the double-delivery test: one draft with 10 lines billing the full quote as "deposit").
//     The delivery whose draft write was a replay does not own the job: it waits for the owner's reply
//     and only posts it if the owner died first.
//  2. Quote quantities, totals and the deposit line are computed in code from live catalog prices;
//     the model only selects price IDs. Customer-facing numbers in the reply come from the same code.
//  3. Before writing: foreign pending items for the customer abort the job (never swept into a deposit);
//     an existing reply for the same quote is never posted twice.
//  4. Connector 429/5xx are retried with the same key (bounded); ticket PUTs read state before a retry.
//  5. Context (tickets, customers, active rate card) is prefetched in one pass, so the model needs
//     fewer turns and tokens; max_tokens stops are handled instead of ending the job silently.
import { createHash } from "node:crypto";
import { appendFileSync } from "node:fs";

const env = process.env;
const MODEL = env.WORLDS_MODEL || "claude-opus-5-5";
const MAX_STEPS = Math.min(Number(env.WORLDS_AGENT_MAX_STEPS || 12), 32);
const MAX_TOKENS = Math.min(Number(env.WORLDS_AGENT_MAX_TOKENS || 1024), 4096);
const deadline = AbortSignal.timeout(Math.min(Number(env.WORLDS_AGENT_TIMEOUT_MS || 120000), 600000));
const base = new URL(env.WORLDS_BASE_URL);
if (!["127.0.0.1", "[::1]"].includes(base.hostname)) throw new Error("twin must be on numeric loopback");
if (!/^sk_twin_/.test(env.WORLDS_API_KEY || "")) throw new Error("WORLDS_API_KEY must be a local twin key");
const task = JSON.parse(env.WORLDS_TASK_JSON);
const secrets = [env.WORLDS_API_KEY, env.ANTHROPIC_API_KEY].filter(Boolean);
const redact = (s) => secrets.reduce((t, k) => t.replaceAll(k, "[redacted]"), String(s));
const trace = (rec) => env.SPARTA_TRACE && appendFileSync(env.SPARTA_TRACE, JSON.stringify({ t: Date.now(), agent: "v2", delivery: env.SPARTA_DELIVERY, ...rec }) + "\n");
let lastReplayed = false;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const hash = (v) => createHash("sha256").update(JSON.stringify(v)).digest("hex").slice(0, 24);
const usd = (c) => (c < 0 ? "-$" : "$") + (Math.abs(c) / 100).toFixed(2);

// ---------- connector: bounded retries, same idempotency key on every attempt ----------
async function twin(method, path, { form, json, key, label } = {}) {
  const headers = { authorization: "Bearer " + env.WORLDS_API_KEY };
  let body;
  if (form) { headers["content-type"] = "application/x-www-form-urlencoded"; body = new URLSearchParams(form).toString(); }
  if (json) { headers["content-type"] = "application/json"; body = JSON.stringify(json); }
  if (key) headers["idempotency-key"] = key;
  for (let attempt = 1; ; attempt++) {
    const r = await fetch(new URL(path, base), { method, headers, body, signal: deadline });
    const out = await r.json();
    lastReplayed = r.headers.get("idempotent-replayed") === "true";
    trace({ kind: "connector", label, method, path: path.split("?")[0], status: r.status, attempt, replayed: r.headers.get("idempotent-replayed") === "true" || undefined });
    if (r.ok) return out;
    if (![429, 500, 502, 503, 504].includes(r.status) || attempt >= 4) throw new Error(`${method} ${path.split("?")[0]} -> HTTP ${r.status}: ${redact(JSON.stringify(out)).slice(0, 300)}`);
    await sleep(150 * attempt);
  }
}
const list = async (res, q = {}) => (await twin("GET", `/v1/${res}?${new URLSearchParams({ limit: "100", ...q })}`, { label: "read" })).data;
const ticketComments = async (id) => (await twin("GET", `/api/v2/tickets/${id}/comments.json`, { label: "read" })).comments;

// ---------- world context, read once ----------
async function context() {
  const tickets = (await twin("GET", "/api/v2/tickets.json", { label: "read" })).tickets;
  const [customers, products, prices] = [await list("customers"), await list("products"), await list("prices")];
  const name = Object.fromEntries(products.map((p) => [p.id, p.name]));
  const desc = Object.fromEntries(products.map((p) => [p.id, p.description]));
  const card = prices.filter((p) => p.active && !p.recurring && p.currency === "usd")
    .map((p) => ({ price: p.id, product: name[p.product], unit: desc[p.product], unit_amount_cents: p.unit_amount, nickname: p.nickname }));
  return {
    priceIndex: Object.fromEntries(prices.map((p) => [p.id, p])),
    view: {
      tickets: tickets.map((t) => ({ id: t.id, subject: t.subject, status: t.status, tags: t.tags, requester: t.requester ?? { email: t.requester_email }, body: t.description })),
      customers: customers.map((c) => ({ id: c.id, name: c.name, email: c.email, metadata: c.metadata })),
      active_rate_card: card,
    },
  };
}

// ---------- deterministic quote + writes ----------
const quotes = new Map();
function priceQuote(ctx, a) {
  const pick = (role, id) => {
    const p = ctx.priceIndex[id];
    if (!p || !p.active || p.recurring || p.currency !== "usd") throw new Error(`${role}: ${id} is not an active one-time USD price`);
    return p;
  };
  const lines = [
    ["machine_time", pick("machine_price", a.machine_price), Math.ceil((a.cycle_s_per_part * a.quantity) / 60)],
    ["stock", pick("material_price", a.material_price), Math.ceil(a.stock_in3_per_blank * a.quantity - 1e-9)],
    ["setup", pick("setup_price", a.setup_price), a.setups],
    ["programming", pick("programming_price", a.programming_price), a.part_numbers],
  ].map(([role, p, qty]) => ({ role, price: p.id, quantity: qty, unit_amount: p.unit_amount, amount: p.unit_amount * qty }));
  if (lines.some((l) => !Number.isSafeInteger(l.quantity) || l.quantity < 1)) throw new Error("every quote line needs a positive whole quantity");
  const total = lines.reduce((s, l) => s + l.amount, 0);
  const balance = Math.floor(total / 2);
  const q = { quote_id: "Q-" + hash({ ticket: a.ticket_id, customer: a.customer, lines }).slice(0, 10).toUpperCase(),
    ticket_id: a.ticket_id, customer: a.customer, lines, quote_total: total, balance_line: -balance, deposit: total - balance };
  quotes.set(q.quote_id, q);
  return q;
}

async function createDepositInvoice(q) {
  const job = `imq-${task.mission.id}-t${q.ticket_id}-${q.customer}`;
  const items = [
    ...q.lines.map((l) => ({ key: `${job}-${l.role}-${hash([l.price, l.quantity])}`, form: { customer: q.customer, price: l.price, quantity: String(l.quantity) } })),
    { key: `${job}-balance-${hash(q.balance_line)}`, form: { customer: q.customer, amount: String(q.balance_line), currency: "usd", description: "Balance due on delivery (50%)" } },
  ];
  // Pending items that this job did not plan would be swept into the deposit draft: stop instead.
  const pending = (await list("invoiceitems", { customer: q.customer, pending: "true" }));
  const planned = new Set(items.map((i) => JSON.stringify([i.form.price ?? null, Number(i.form.quantity ?? 1), i.form.price ? null : Number(i.form.amount)])));
  const foreign = pending.filter((p) => !planned.has(JSON.stringify([p.price?.id ?? null, p.quantity, p.price ? null : p.amount])));
  if (foreign.length) throw new Error(`customer ${q.customer} has ${foreign.length} pending invoice item(s) this quote did not create; a human must review them first`);
  for (const i of items) await twin("POST", "/v1/invoiceitems", { form: i.form, key: i.key, label: "write" });
  const inv = await twin("POST", "/v1/invoices", { form: { customer: q.customer, currency: "usd", "metadata[quote_id]": q.quote_id, "metadata[rfq_ticket]": String(q.ticket_id) }, key: `${job}-draft-${q.quote_id}`, label: "write" });
  const draftReplayed = lastReplayed;
  const check = await twin("GET", `/v1/invoices/${inv.id}`, { label: "verify" });
  if (check.status !== "draft" || check.total !== q.deposit || check.customer !== q.customer) throw new Error(`draft ${inv.id} does not match the quote (total ${check.total}, expected ${q.deposit})`);
  q.invoice_id = inv.id;
  q.owner = !draftReplayed;
  return { invoice_id: inv.id, status: check.status, total_cents: check.total, lines: check.lines.data.length,
    ...(draftReplayed && { note: "this draft already existed from another delivery of the same job (idempotent replay); nothing was duplicated. Still call send_quote_reply: it posts the reply only if no delivery has posted it" }) };
}

async function replyOnce(ticketId, marker, update, waitForOwnerMs = 0) {
  // Not the owner of this job: give the owning delivery time to reply, then take over if it died.
  for (const until = Date.now() + waitForOwnerMs; Date.now() < until; await sleep(1000))
    if ((await ticketComments(ticketId)).some((c) => String(c.body).includes(marker))) { trace({ kind: "skip", why: "owner replied", ticket: ticketId }); return { skipped: "the delivery that owns this job already replied" }; }
  const already = (await ticketComments(ticketId)).some((c) => String(c.body).includes(marker));
  if (already) { trace({ kind: "skip", why: "reply already posted", ticket: ticketId }); return { skipped: "already replied" }; }
  const t = (await twin("GET", `/api/v2/tickets/${ticketId}.json`, { label: "read" })).ticket;
  const tags = [...new Set([...(t.tags || []), ...update.add_tags])];
  const ticket = { status: update.status, tags, comment: { body: update.body, public: true } };
  try { await twin("PUT", `/api/v2/tickets/${ticketId}.json`, { json: { ticket }, label: "write" }); }
  catch (e) { // read before retrying a non-idempotent write
    if ((await ticketComments(ticketId)).some((c) => String(c.body).includes(marker))) return { posted: true };
    throw e;
  }
  return { posted: true, status: update.status, tags };
}

function quoteReply(q, note) {
  const label = { machine_time: "machine time (min)", stock: "stock (cu in)", setup: "setups", programming: "programming & simulation" };
  const rows = q.lines.map((l) => `- ${label[l.role]}: ${l.quantity} x ${usd(l.unit_amount)} = ${usd(l.amount)}`).join("\n");
  return `Quote ${q.quote_id}\n${rows}\nQuote total: ${usd(q.quote_total)}\n50% deposit to start: ${usd(q.deposit)} (balance ${usd(-q.balance_line)} due on delivery)\nDeposit draft invoice: ${q.invoice_id}${note ? "\n\n" + note : ""}`;
}

// ---------- tools exposed to the model ----------
const id = { type: "string", pattern: "^[A-Za-z0-9_-]{1,200}$" };
const tools = [
  { name: "get_ticket_comments", description: "Read a ticket's comment history.", input_schema: { type: "object", properties: { ticket_id: id }, required: ["ticket_id"], additionalProperties: false } },
  { name: "price_quote", description: "Compute the quote and 50% deposit in code from the job card and the catalog prices you select (machine, material, setup, programming). Validates each price is active, one-time USD. Returns quote_id, lines, totals. No writes.",
    input_schema: { type: "object", additionalProperties: false, required: ["ticket_id", "customer", "machine_price", "material_price", "setup_price", "programming_price", "cycle_s_per_part", "quantity", "stock_in3_per_blank", "setups", "part_numbers"],
      properties: { ticket_id: id, customer: id, machine_price: id, material_price: id, setup_price: id, programming_price: id,
        cycle_s_per_part: { type: "number", exclusiveMinimum: 0 }, quantity: { type: "integer", minimum: 1 }, stock_in3_per_blank: { type: "number", exclusiveMinimum: 0 },
        setups: { type: "integer", minimum: 1 }, part_numbers: { type: "integer", minimum: 1 } } } },
  { name: "create_deposit_invoice", description: "Write the priced quote: one invoice item per quote line, the 'Balance due on delivery (50%)' line, then exactly one draft invoice; verifies the draft total. Idempotent: safe to call again for the same quote.",
    input_schema: { type: "object", properties: { quote_id: { type: "string" } }, required: ["quote_id"], additionalProperties: false } },
  { name: "send_quote_reply", description: "Post the single public quote reply on the RFQ ticket (numbers are filled in from the quote), add tag quoted, set pending. Only after create_deposit_invoice. Optional short note (e.g. cycle-time basis).",
    input_schema: { type: "object", properties: { quote_id: { type: "string" }, note: { type: "string", maxLength: 600 } }, required: ["quote_id"], additionalProperties: false } },
  { name: "ask_clarification", description: "When the requester cannot be tied to exactly one customer: post one public question on the ticket, add tag needs-info, set pending. No billing writes.",
    input_schema: { type: "object", properties: { ticket_id: id, question: { type: "string", minLength: 10, maxLength: 1200 } }, required: ["ticket_id", "question"], additionalProperties: false } },
];

async function runTool(ctx, name, a) {
  if (name === "get_ticket_comments") return ticketComments(a.ticket_id);
  if (name === "price_quote") {
    if (!ctx.view.customers.some((c) => c.id === a.customer)) throw new Error("unknown customer " + a.customer);
    return priceQuote(ctx, a);
  }
  const q = quotes.get(a.quote_id);
  if (name === "create_deposit_invoice") { if (!q) throw new Error("price the quote first"); return createDepositInvoice(q); }
  if (name === "send_quote_reply") {
    if (!q?.invoice_id) throw new Error("create the deposit invoice first");
    return replyOnce(q.ticket_id, q.invoice_id, { status: "pending", add_tags: ["quoted"], body: quoteReply(q, a.note) }, q.owner ? 0 : 20000);
  }
  if (name === "ask_clarification") {
    if (quotes.size) throw new Error("a quote was already priced in this job; do not ask after pricing");
    return replyOnce(a.ticket_id, "[needs-info]", { status: "pending", add_tags: ["needs-info"], body: a.question + "\n\n[needs-info]" });
  }
  throw new Error("unknown tool " + name);
}

const system = `You are the quoting agent of a CNC machine shop. Input: a public mission (an RFQ ticket plus an Instant Machinist job card) and a snapshot of the shop's tickets, customers and active rate card. Decide, then act only through the tools:
1. Find the RFQ ticket named in the mission. Identify the customer strictly by the requester's email or email domain: it must match exactly one customer record. Company names in the text do not count. If none or several match, call ask_clarification (one clear question: which company and billing contact to invoice) and stop. Never bill a guess.
2. Otherwise select from active_rate_card the price IDs for the job card's machine, its material, setup and programming & simulation, and call price_quote with the job card's numbers exactly as given. Ignore finishing and other goods unless the job card asks for them.
3. Call create_deposit_invoice, then send_quote_reply (put the cycle-time basis in the note if it is assumed).
Never invent IDs. Tool errors are facts: if a tool reports a state problem, stop and report it. Finish with a two-line factual summary.`;

async function main() {
  const t0 = Date.now();
  const ctx = await context();
  trace({ kind: "context", tickets: ctx.view.tickets.length, customers: ctx.view.customers.length, rate_card: ctx.view.active_rate_card.length });
  const messages = [{ role: "user", content: JSON.stringify({ mission: task.mission, shop: ctx.view }) }];
  let inTok = 0, outTok = 0, calls = 0;
  for (let step = 0; step < MAX_STEPS; step++) {
    let res;
    for (let attempt = 1; ; attempt++) {
      const r = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST", signal: deadline,
        headers: { "content-type": "application/json", "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01" },
        body: JSON.stringify({ model: MODEL, max_tokens: MAX_TOKENS, system, tools, messages }),
      });
      if (r.ok) { res = await r.json(); break; }
      await r.body?.cancel();
      if (![429, 500, 529].includes(r.status) || attempt >= 3) throw new Error("model HTTP " + r.status);
      await sleep(1000 * attempt);
    }
    inTok += res.usage?.input_tokens || 0; outTok += res.usage?.output_tokens || 0;
    if (res.stop_reason === "max_tokens") { // never execute a truncated tool call
      messages.push({ role: "assistant", content: [{ type: "text", text: "(my previous turn was cut off at the token limit)" }] });
      messages.push({ role: "user", content: "Your last turn hit the token limit. Be brief and make one tool call at a time." });
      continue;
    }
    const uses = res.content.filter((b) => b.type === "tool_use");
    messages.push({ role: "assistant", content: res.content });
    if (!uses.length) {
      console.log(redact(res.content.filter((b) => b.type === "text").map((b) => b.text).join("\n")).slice(0, 4000));
      trace({ kind: "done", steps: step + 1, tool_calls: calls, input_tokens: inTok, output_tokens: outTok, ms: Date.now() - t0 });
      console.error(`usage: ${inTok} in / ${outTok} out tokens, ${step + 1} steps, ${calls} tool calls, ${Date.now() - t0} ms`);
      return;
    }
    const results = [];
    for (const u of uses) {
      calls++;
      trace({ kind: "tool", tool: u.name, input: u.input });
      try { results.push({ type: "tool_result", tool_use_id: u.id, content: redact(JSON.stringify(await runTool(ctx, u.name, u.input))).slice(0, 20000) }); }
      catch (e) { trace({ kind: "tool_error", tool: u.name, msg: redact(e.message) }); results.push({ type: "tool_result", tool_use_id: u.id, is_error: true, content: redact(e.message) }); }
    }
    messages.push({ role: "user", content: results });
  }
  throw new Error("step budget exhausted");
}
main().catch((e) => { console.error("quote agent v2 failed: " + redact(e.message)); trace({ kind: "error", msg: redact(e.message) }); process.exitCode = 1; });
