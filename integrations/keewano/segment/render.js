// Headless render of segment.html?cut=N (window.__seek/__duration) to JPEG frames; ffmpeg turns them into MP4.
//   node render.js OUTDIR FPS CUT            |   node render.js OUTDIR stills t1,t2,... CUT
const path = require('path'), fs = require('fs');
const { chromium } = require('playwright-core');
(async () => {
  const [outArg, fpsArg, a3, a4] = process.argv.slice(2);
  const stills = fpsArg === 'stills', cut = Number(stills ? a4 : a3) || 60;
  const out = path.resolve(outArg); fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch({ executablePath: process.env.CHROME || undefined, headless: true,
    args: ['--allow-file-access-from-files', '--font-render-hinting=none'] });
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  p.on('pageerror', e => { console.log('PAGEERROR', e.message); process.exitCode = 1; });
  await p.goto('file://' + path.join(__dirname, 'segment.html') + '?cut=' + cut);
  await p.waitForFunction(() => window.__ready === true);
  await p.evaluate(() => document.fonts.ready);
  const dur = await p.evaluate(() => window.__duration);
  const shot = async (t, f) => { await p.evaluate(t => window.__seek(t), t); await p.screenshot({ path: f, type: 'jpeg', quality: 92 }); };
  if (stills) {
    for (const t of a3.split(',').map(Number)) {
      await shot(t, path.join(out, `c${cut}_${String(t.toFixed(1)).padStart(5, '0')}.jpg`));
      const bad = await p.evaluate(() => [...document.querySelectorAll('.card,.term,.strip,.chip,.qrow,.sl,.vb,.bar,.mr,h1,.end > div')]
        .filter(e => e.offsetParent && (e.scrollHeight > e.clientHeight + 2 || e.scrollWidth > e.clientWidth + 2))
        .map(e => `${e.className || e.tagName}#${e.id} ${e.scrollWidth}x${e.scrollHeight} > ${e.clientWidth}x${e.clientHeight}`));
      if (bad.length) console.log('OVERFLOW', cut, t, JSON.stringify(bad));
    }
  } else {
    const fps = Number(fpsArg || 30), n = Math.round(dur * fps);
    for (let i = 0; i < n; i++) await shot(i / fps, path.join(out, `f${String(i).padStart(5, '0')}.jpg`));
  }
  console.log('done cut', cut, 'duration', dur);
  await b.close();
})();
