// Instant Machinist quote agent, v1 (first version, kept unchanged for the before/after comparison).
// RFQ ticket + Instant Machinist job card -> priced quote -> one 50% deposit draft invoice -> ticket reply.
// Claude reads the world through tools and does the pricing itself. Node 24+, no npm dependencies.
// Env: WORLDS_BASE_URL, WORLDS_API_KEY, WORLDS_TASK_JSON (runner); ANTHROPIC_API_KEY (the environment); WORLDS_MODEL.
import { appendFileSync } from "node:fs";

const env = process.env;
const MODEL = env.WORLDS_MODEL || "claude-opus-5-5";
const MAX_STEPS = Math.min(Number(env.WORLDS_AGENT_MAX_STEPS || 16), 32);
const MAX_TOKENS = Math.min(Number(env.WORLDS_AGENT_MAX_TOKENS || 2048), 4096);
const deadline = AbortSignal.timeout(Math.min(Number(env.WORLDS_AGENT_TIMEOUT_MS || 150000), 600000));
const base = new URL(env.WORLDS_BASE_URL);
if (!["127.0.0.1", "[::1]"].includes(base.hostname)) throw new Error("twin must be on numeric loopback");
const task = JSON.parse(env.WORLDS_TASK_JSON);
const secrets = [env.WORLDS_API_KEY, env.ANTHROPIC_API_KEY].filter(Boolean);
const redact = (s) => secrets.reduce((t, k) => t.replaceAll(k, "[redacted]"), String(s));
const trace = (rec) => env.SPARTA_TRACE && appendFileSync(env.SPARTA_TRACE, JSON.stringify({ t: Date.now(), agent: "v1", ...rec }) + "\n");

const id = { type: "string", pattern: "^[A-Za-z0-9_-]{1,200}$" };
const tools = [
  { name: "list_records", description: "List records. resource: customers | products | prices | invoices | invoiceitems | tickets. Optional customer filter for invoices/invoiceitems, email filter for customers.",
    input_schema: { type: "object", properties: { resource: { enum: ["customers", "products", "prices", "invoices", "invoiceitems", "tickets"] }, customer: id, email: { type: "string" } }, required: ["resource"] } },
  { name: "get_ticket", description: "Read one ticket with its comment history.",
    input_schema: { type: "object", properties: { ticket_id: id }, required: ["ticket_id"] } },
  { name: "create_invoice_item", description: "Create a pending invoice item for a customer: either a catalog price + quantity, or a bare amount (integer cents, may be negative) + description.",
    input_schema: { type: "object", properties: { customer: id, price: id, quantity: { type: "integer", minimum: 1 }, amount: { type: "integer" }, description: { type: "string", maxLength: 200 } }, required: ["customer"] } },
  { name: "create_draft_invoice", description: "Create one draft invoice collecting the customer's pending invoice items. Never finalize or pay.",
    input_schema: { type: "object", properties: { customer: id }, required: ["customer"] } },
  { name: "update_ticket", description: "Update a ticket: status, full tag list (replaces tags), and/or one comment {body, public}.",
    input_schema: { type: "object", properties: { ticket_id: id, status: { enum: ["open", "pending", "hold", "solved"] }, tags: { type: "array", items: { type: "string" }, maxItems: 20 }, comment: { type: "object", properties: { body: { type: "string", maxLength: 4000 }, public: { type: "boolean" } }, required: ["body", "public"] } }, required: ["ticket_id"] } },
];

function toRequest(name, a) {
  if (name === "list_records") {
    if (a.resource === "tickets") return ["GET", "/api/v2/tickets.json"];
    const q = new URLSearchParams({ limit: "100", ...(a.customer && { customer: a.customer }), ...(a.email && { email: a.email }) });
    return ["GET", `/v1/${a.resource}?${q}`];
  }
  if (name === "get_ticket") return ["GET", `/api/v2/tickets/${a.ticket_id}.json`];
  if (name === "create_invoice_item") {
    const p = { customer: a.customer };
    if (a.price) Object.assign(p, { price: a.price, quantity: String(a.quantity ?? 1) });
    else Object.assign(p, { amount: String(a.amount), currency: "usd" });
    if (a.description) p.description = a.description;
    return ["POST", "/v1/invoiceitems", new URLSearchParams(p).toString()];
  }
  if (name === "create_draft_invoice") return ["POST", "/v1/invoices", new URLSearchParams({ customer: a.customer, currency: "usd" }).toString()];
  if (name === "update_ticket") {
    const { ticket_id, ...ticket } = a;
    return ["PUT", `/api/v2/tickets/${ticket_id}.json`, JSON.stringify({ ticket }), "application/json"];
  }
  throw new Error("unknown tool " + name);
}

async function twin(name, input) {
  const [method, path, body, type] = toRequest(name, input);
  const headers = { authorization: "Bearer " + env.WORLDS_API_KEY };
  if (body) headers["content-type"] = type || "application/x-www-form-urlencoded";
  const r = await fetch(new URL(path, base), { method, headers, body, signal: deadline });
  const json = await r.json();
  trace({ kind: "connector", tool: name, method, path: path.split("?")[0], status: r.status });
  if (name === "get_ticket" && r.ok) {
    const c = await fetch(new URL(`/api/v2/tickets/${input.ticket_id}/comments.json`, base), { headers, signal: deadline });
    json.comments = (await c.json()).comments;
  }
  return json;
}

const system = `You are the quoting assistant of a CNC machine shop. You turn an RFQ ticket plus an Instant Machinist job card into a priced quote and a 50% deposit draft invoice, using only the supplied tools against the shop's systems. Follow the mission policy exactly. Read the ticket, customers and the catalog before writing. Finish with a short factual summary.`;

async function main() {
  const t0 = Date.now();
  const messages = [{ role: "user", content: JSON.stringify(task.mission) }];
  let inTok = 0, outTok = 0, calls = 0;
  for (let step = 0; step < MAX_STEPS; step++) {
    const r = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST", signal: deadline,
      headers: { "content-type": "application/json", "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01" },
      body: JSON.stringify({ model: MODEL, max_tokens: MAX_TOKENS, system, tools, messages }),
    });
    if (!r.ok) throw new Error("model HTTP " + r.status);
    const res = await r.json();
    inTok += res.usage?.input_tokens || 0; outTok += res.usage?.output_tokens || 0;
    const uses = res.content.filter((b) => b.type === "tool_use");
    messages.push({ role: "assistant", content: res.content });
    if (!uses.length) {
      const text = res.content.filter((b) => b.type === "text").map((b) => b.text).join("\n");
      console.log(redact(text).slice(0, 4000));
      trace({ kind: "done", steps: step + 1, tool_calls: calls, input_tokens: inTok, output_tokens: outTok, ms: Date.now() - t0 });
      console.error(`usage: ${inTok} in / ${outTok} out tokens, ${step + 1} steps, ${calls} tool calls, ${Date.now() - t0} ms`);
      return;
    }
    const results = [];
    for (const u of uses) {
      calls++;
      trace({ kind: "tool", tool: u.name, input: u.input });
      try { results.push({ type: "tool_result", tool_use_id: u.id, content: redact(JSON.stringify(await twin(u.name, u.input))).slice(0, 60000) }); }
      catch (e) { results.push({ type: "tool_result", tool_use_id: u.id, is_error: true, content: redact(e.message) }); }
    }
    messages.push({ role: "user", content: results });
  }
  throw new Error("step budget exhausted");
}
main().catch((e) => { console.error("quote agent v1 failed: " + redact(e.message)); trace({ kind: "error", msg: redact(e.message) }); process.exitCode = 1; });
