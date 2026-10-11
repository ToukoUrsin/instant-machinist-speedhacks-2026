// Headless render of segment.html (window.__seek/__duration) to JPEG frames; ffmpeg turns them into MP4.
//   V=30|60|30h node render.js OUTDIR [FPS]   |   V=60 node render.js OUTDIR stills t1,t2
const path = require('path'), fs = require('fs');
const { chromium } = require('playwright-core');
const LOCAL = process.env.HOME + '/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome';
const CHROME = process.env.CHROME || (fs.existsSync(LOCAL) ? LOCAL : undefined);  // undefined: playwright resolves its own
(async () => {
  const [outArg, fpsArg, times] = process.argv.slice(2);
  const out = path.resolve(outArg); fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--allow-file-access-from-files', '--font-render-hinting=none'] });
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  p.on('pageerror', e => console.log('PAGEERROR', e.message));
  await p.goto('file://' + path.join(__dirname, 'segment.html') + '?v=' + (process.env.V || '30'));
  await p.waitForFunction(() => window.__ready === true);
  const dur = await p.evaluate(() => window.__duration);
  const shot = async (t, f) => { await p.evaluate(t => window.__seek(t), t); await p.screenshot({ path: f, type: 'jpeg', quality: 90 }); };
  if (fpsArg === 'stills') {
    for (const t of times.split(',').map(Number)) await shot(t, path.join(out, `still_v${process.env.V || '30'}_${String(t).padStart(5, '0')}.jpg`));
  } else {
    const fps = Number(fpsArg || 30), n = Math.round(dur * fps);
    for (let i = 0; i <= n; i++) await shot(i / fps, path.join(out, `f${String(i).padStart(5, '0')}.jpg`));
  }
  console.log('done', dur);
  await b.close();
})();
