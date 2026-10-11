// Records the live page in headless Chrome while a real run happens: node demo/live/record_live.mjs <url> <outdir>
// Waits for the next job, saves a 1920x1080 frame every 0.5 s until 20 s after the agent replied (or 30 min).
import { chromium } from "playwright";
import fs from "fs";
const [url, outdir] = process.argv.slice(2);
const api = async (p) => (await fetch(url.replace(/\/$/, "") + p)).json();
const first = (await api("/api/latest")).id;
console.log("waiting for a new job (latest:", first, ")");
const b = await chromium.launch({ headless: true, executablePath: "/usr/bin/google-chrome", args: ["--autoplay-policy=no-user-gesture-required"] });
const p = await b.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1.2 });
p.on("pageerror", (e) => console.log("pageerror:", e.message));
await p.goto(url);
fs.mkdirSync(outdir, { recursive: true });
let job = null, i = 0, endAt = null;
const t0 = Date.now();
while (true) {
  const t = Date.now();
  if (!job) { const l = (await api("/api/latest")).id; if (l && l !== first) { job = l; console.log("job", job); } }
  if (job) {
    const buf = await p.screenshot({ type: "jpeg", quality: 92 });
    fs.writeFileSync(`${outdir}/f${String(i++).padStart(5, "0")}.jpg`, buf);
    if (i % 60 === 0) {
      const s = await api(`/api/run/${job}`);
      console.log(`frame ${i}, events ${s.events.length}, replied ${s.replied}, exit ${s.exit}`);
      if ((s.replied || (s.exit && s.exit !== "0") || s.render_error) && !endAt) endAt = Date.now() + 20000;
    }
    if ((endAt && Date.now() > endAt) || Date.now() - t0 > 30 * 60e3) break;
  }
  await new Promise((r) => setTimeout(r, Math.max(0, 500 - (Date.now() - t))));
}
await b.close();
console.log("done", i, "frames");
