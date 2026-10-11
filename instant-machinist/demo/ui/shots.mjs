// node shots.mjs out_dir v1 v2 ...  -> PNG stills of the replay UI at given video times (headless)
import { chromium } from "playwright";
import path from "path"; import fs from "fs";
const [outDir, ...ts] = process.argv.slice(2);
fs.mkdirSync(outDir, { recursive: true });
const b = await chromium.launch({ headless: true });
const p = await b.newPage({ viewport: { width: 960, height: 540 }, deviceScaleFactor: 2 });
p.on("console", (m) => console.log("console:", m.text())); p.on("pageerror", (e) => console.log("pageerror:", e.message));
await p.goto("file://" + (process.env.HTML ? path.resolve(process.env.HTML) : path.resolve(path.dirname(new URL(import.meta.url).pathname), "index.html")) + "?manual=1&" + (process.env.Q || ""));
await p.evaluate(() => window.__ready);
for (const t of ts) { await p.evaluate((v) => window.__render(v), +t); await p.screenshot({ path: `${outDir}/ui_${t}.png` }); }
await b.close();
