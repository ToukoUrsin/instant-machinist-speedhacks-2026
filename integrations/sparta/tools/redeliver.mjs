// At-least-once job delivery harness (agent-agnostic). Job queues and help-desk triggers deliver a job
// at least once, so the same RFQ job can reach the agent twice against the SAME world:
//   node ../../tools/redeliver.mjs crash <n> <agent.mjs>   worker killed right after its nth write commits
//                                                            (response lost), then the job is redelivered
//   node ../../tools/redeliver.mjs double <agent.mjs>      a second delivery starts 1.5 s after the first
//                                                            while the first is still running (trigger fired twice)
// Exit code: nonzero if the final delivery (crash) or either delivery (double) fails.
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
const [mode, ...rest] = process.argv.slice(2);
const node = process.execPath;
if (mode === "crash") {
  const [n, agent] = rest;
  const inject = fileURLToPath(new URL("./fault-crash.mjs", import.meta.url));
  const first = spawnSync(node, ["--import", inject, agent], { stdio: "inherit", env: { ...process.env, SPARTA_CRASH_AFTER_WRITES: n } });
  process.stderr.write(`[redeliver] delivery 1 ended (${first.signal || "exit " + first.status}); redelivering the same job\n`);
  const second = spawnSync(node, [agent], { stdio: "inherit", env: { ...process.env, SPARTA_CRASH_AFTER_WRITES: "" } });
  process.exit(second.status ?? 1);
} else if (mode === "double") {
  const [agent] = rest;
  const run = (tag) => new Promise((done) => {
    const p = spawn(node, [agent], { stdio: ["ignore", "inherit", "inherit"], env: { ...process.env, SPARTA_DELIVERY: tag } });
    p.on("exit", (code, sig) => { process.stderr.write(`[redeliver] delivery ${tag} ended (${sig || "exit " + code})\n`); done(code ?? 1); });
  });
  const a = run("1");
  await new Promise((r) => setTimeout(r, 1500));
  process.stderr.write("[redeliver] trigger fired again: delivery 2 starts while delivery 1 is running\n");
  const codes = await Promise.all([a, run("2")]);
  process.exit(codes.some((c) => c !== 0) ? 1 : 0);
} else {
  process.stderr.write("usage: redeliver.mjs crash <n> <agent> | double <agent>\n");
  process.exit(2);
}
