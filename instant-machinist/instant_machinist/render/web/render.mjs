// Headless Chrome driver: renders output frames [start, end) of the scene to PNGs.
// node render.mjs --data DIR --outdir DIR --size 1920x1080 [--workers N] [--start A --end B] [--still PNG --frame I]
import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { execSync } from 'node:child_process';
import path from 'node:path';
import http from 'node:http';
import { fileURLToPath } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : 'true']);
  return acc;
}, []));
const require = createRequire(import.meta.url);
let playwright;
try { playwright = require('playwright'); } catch {
  const root = execSync('npm root -g').toString().trim();
  playwright = require(path.join(root, 'playwright'));
}
const here = path.dirname(fileURLToPath(import.meta.url));
const renderRoot = path.resolve(here, '..');
const dataDir = path.resolve(args.data);
const [W, H] = (args.size || '1920x1080').split('x').map(Number);
const workers = Number(args.workers || 1);

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.otf': 'font/otf', '.bin': 'application/octet-stream' };
// local static server (route.fulfill chokes on ~100 MB bodies)
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  const file = p.startsWith('/data/') ? path.join(dataDir, p.slice(6)) : path.join(renderRoot, p);
  try {
    const body = await readFile(file);
    res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' }); res.end(body);
  } catch { res.writeHead(404); res.end('nf ' + p); }
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const BASE = `http://127.0.0.1:${server.address().port}`;

const browser = await playwright.chromium.launch({
  headless: true,
  executablePath: args.chrome || undefined,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl', '--disable-gpu-vsync', '--hide-scrollbars'],
});

async function openPage() {
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  page.on('crash', () => console.error('[crash] renderer crashed'));
  page.on('pageerror', (e) => console.error('[pageerror]', e.message));
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.error('[console]', m.text()); });
  await page.goto(`${BASE}/web/index.html`);
  await page.waitForFunction(() => window.sceneReady === true, null, { timeout: 180000 });
  return page;
}

const t0 = Date.now();
if (args.still) {
  const page = await openPage();
  const n = await page.evaluate(() => window.nFrames);
  const i = args.frame !== undefined ? Number(args.frame) : n - 1;
  await page.evaluate((i) => window.renderFrame(i), i);
  await page.screenshot({ path: args.still, type: 'png' });
  console.error(`still frame ${i} -> ${args.still}`);
} else {
  await mkdir(args.outdir, { recursive: true });
  const probe = await openPage();
  const n = await probe.evaluate(() => window.nFrames);
  const start = Number(args.start || 0), end = Math.min(n, Number(args.end || n));
  const pages = [probe];
  for (let w = 1; w < workers; w++) pages.push(await openPage());
  const list = args.list ? args.list.split(',').map(Number) : null;
  let next = list ? 0 : start, done = 0;
  const stop = list ? list.length : end;
  await Promise.all(pages.map(async (page) => {
    while (true) {
      const k = next++;
      if (k >= stop) return;
      const i = list ? list[k] : k;
      await page.evaluate((i) => window.renderFrame(i), i);
      const buf = await page.screenshot({ type: 'png' });
      await writeFile(path.join(args.outdir, `f${String(i).padStart(5, '0')}.png`), buf);
      done++;
      if (done % 30 === 0) console.error(`  ${done}/${stop - (list ? 0 : start)} frames, ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    }
  }));
  console.error(`rendered ${done} frames in ${((Date.now() - t0) / 1000).toFixed(1)}s`);
}
await browser.close();
server.close();
