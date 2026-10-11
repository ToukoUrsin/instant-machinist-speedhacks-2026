// Fault injector (test harness, agent-agnostic). Loaded with `node --import`, it lets the agent's
// Nth successful write (POST/PUT) to the local world commit, then kills the process before the
// agent sees the response: the "worker died mid-job" case (OOM, deploy restart, timeout).
const n = Number(process.env.SPARTA_CRASH_AFTER_WRITES || 0);
const base = process.env.WORLDS_BASE_URL;
if (n > 0 && base) {
  const real = globalThis.fetch;
  let writes = 0;
  globalThis.fetch = async (url, init = {}) => {
    const res = await real(url, init);
    const m = (init.method || "GET").toUpperCase();
    if (String(url).startsWith(base) && (m === "POST" || m === "PUT") && res.ok && ++writes >= n) {
      process.stderr.write(`[fault] killed after write #${writes} committed (${m} ${new URL(String(url)).pathname}); response lost\n`);
      process.kill(process.pid, "SIGKILL");
    }
    return res;
  };
}
