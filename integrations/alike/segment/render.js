// Headless render of segment.html / overlay.html (window.__seek/__duration) to frames; ffmpeg turns them into video.
//   NODE_PATH=<dir with playwright-core> node render.js PAGE OUTDIR [FPS] [jpeg|png-alpha]   |   node render.js PAGE OUTDIR stills t1,t2
//   PAGE may carry a query string, e.g. "overlay.html?key=1" (green key background).
const path = require('path'), fs = require('fs');
const { chromium } = require('playwright-core');
const LOCAL = process.env.HOME + '/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome';
const CHROME = process.env.CHROME || (fs.existsSync(LOCAL) ? LOCAL : undefined);
(async () => {
  const [page, outArg, fpsArg, fmtOrTimes] = process.argv.slice(2);
  const out = path.resolve(outArg); fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--allow-file-access-from-files', '--font-render-hinting=none'] });
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  p.on('pageerror', e => console.log('PAGEERROR', e.message));
  await p.goto('file://' + path.join(__dirname, page));
  await p.waitForFunction(() => window.__ready === true);
  await p.evaluate(() => document.fonts.ready);
  const dur = await p.evaluate(() => window.__duration);
  const alpha = fmtOrTimes === 'png-alpha';
  const shot = async (t, f) => {
    await p.evaluate(t => window.__seek(t), t);
    await p.screenshot(alpha ? { path: f, type: 'png', omitBackground: true } : { path: f, type: 'jpeg', quality: 92 });
  };
  if (fpsArg === 'stills') {
    for (const t of fmtOrTimes.split(',').map(Number)) await shot(t, path.join(out, `still_${String(t.toFixed(2)).padStart(5, '0')}.jpg`));
  } else {
    const fps = Number(fpsArg || 30), n = Math.round(dur * fps), ext = alpha ? 'png' : 'jpg';
    for (let i = 0; i < n; i++) await shot(i / fps, path.join(out, `f${String(i).padStart(5, '0')}.${ext}`));
  }
  console.log('done', page, dur);
  await b.close();
})();
