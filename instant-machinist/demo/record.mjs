// Deterministic headless recorder: node record.mjs <html> <out.mp4> [query] [fps]
// Page must expose window.__render(v), window.__duration and window.__ready. 960x540 CSS at 2x DPR -> 1920x1080.
import { chromium } from "playwright";
import { spawn } from "child_process";
import path from "path";
const [html, out, query = "", fpsArg = "30"] = process.argv.slice(2);
const fps = +fpsArg;
const b = await chromium.launch({ headless: true });
const p = await b.newPage({ viewport: { width: 960, height: 540 }, deviceScaleFactor: 2 });
p.on("pageerror", (e) => console.log("pageerror:", e.message));
await p.goto("file://" + path.resolve(html) + "?manual=1" + (query ? "&" + query : ""));
await p.evaluate(() => window.__ready);
const dur = await p.evaluate(() => window.__duration);
const n = Math.round(dur * fps);
const ff = spawn("nice", ["-n", "19", "ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(fps), "-i", "-",
  "-c:v", "libx264", "-threads", "4", "-preset", "fast", "-crf", "14", "-pix_fmt", "yuv420p", "-r", String(fps), out], { stdio: ["pipe", "inherit", "inherit"] });
for (let i = 0; i < n; i++) {
  await p.evaluate((v) => window.__render(v), i / fps);
  const buf = await p.screenshot({ type: "png" });
  if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once("drain", r));
  if (i % 150 === 0) console.log(`${out}: frame ${i}/${n}`);
}
ff.stdin.end();
await new Promise((r) => ff.on("close", r));
await b.close();
console.log("wrote", out, n, "frames");
