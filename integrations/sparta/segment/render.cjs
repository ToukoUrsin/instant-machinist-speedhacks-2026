// Headless render of segment.html (window.__seek/__duration) to JPEG frames; ffmpeg turns them into MP4.
//   node render.cjs OUTDIR [FPS]   |   node render.cjs OUTDIR stills t1,t2
// (.cjs because sparta/package.json is "type": "module")
const path = require('path'), fs = require('fs');
const { chromium } = require('playwright-core');
const LOCAL = process.env.HOME + '/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome';
const CHROME = process.env.CHROME || (fs.existsSync(LOCAL) ? LOCAL : undefined);
(async () => {
  const [outArg, fpsArg, times] = process.argv.slice(2);
  const out = path.resolve(outArg); fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--allow-file-access-from-files', '--font-render-hinting=none'] });
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  p.on('pageerror', e => { console.log('PAGEERROR', e.message); process.exitCode = 1; });
  await p.goto('file://' + path.join(__dirname, 'segment.html'));
  await p.waitForFunction(() => window.__ready === true);
  await p.evaluate(() => document.fonts.ready);
  const dur = await p.evaluate(() => window.__duration);
  // overflow audit: any visible element whose content spills out of a card/scene
  const audit = async t => p.evaluate(t => {
    window.__seek(t); const bad = [];
    document.querySelectorAll('.card, .pill, .code, .scene > div').forEach(el => {
      if (el.offsetParent === null) return;
      if (el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2) bad.push((el.id || el.className) + ` ${el.scrollWidth}x${el.scrollHeight} > ${el.clientWidth}x${el.clientHeight}`);
      const r = el.getBoundingClientRect(); if (r.bottom > 1000 || r.right > 1860) bad.push((el.id || el.className) + ` box ${Math.round(r.right)},${Math.round(r.bottom)}`);
    });
    const hit = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
    document.querySelectorAll('.stamp').forEach(st => { if (st.offsetParent === null) return; const r = st.getBoundingClientRect();
      st.parentElement.querySelectorAll('.ln, .mono, .lab, .dl, .tot').forEach(x => { if (hit(r, x.getBoundingClientRect())) bad.push('stamp overlaps ' + (x.id || x.className) + ': ' + x.textContent.slice(0, 40)); }); });
    document.querySelectorAll('.ln').forEach(el => { if (el.offsetParent !== null && el.scrollWidth > el.clientWidth + 1) bad.push('invoice line overflow ' + el.textContent.slice(0, 40)); });
    const f = document.getElementById('foot'), fl = document.getElementById('footl').getBoundingClientRect(), fr = document.getElementById('footr').getBoundingClientRect();
    if (f.scrollWidth > f.clientWidth + 1 || fl.right + 30 > fr.left) bad.push('footer too long');
    const fam = getComputedStyle(document.body).fontFamily; if (!document.fonts.check('16px Inter')) bad.push('Inter not available: ' + fam);
    const h = document.getElementById('h1').getBoundingClientRect(); if (h.bottom > 262) bad.push('h1 bottom ' + Math.round(h.bottom));
    return bad;
  }, t);
  const shot = async (t, f) => { await p.evaluate(t => window.__seek(t), t); await p.screenshot({ path: f, type: 'jpeg', quality: 90 }); };
  for (const t of [9.9, 19.9, 26.9, 34.9, 44.9, 52.9, 59.9]) { const bad = await audit(t); console.log('audit t=' + t, bad.length ? 'OVERFLOW ' + JSON.stringify(bad) : 'ok'); }
  for (const t of []) { const bad = await audit(t); if (bad.length) console.log('OVERFLOW t=' + t, JSON.stringify(bad)); }
  if (fpsArg === 'stills') {
    for (const t of times.split(',').map(Number)) await shot(t, path.join(out, `still_${String(t).padStart(5, '0')}.jpg`));
  } else {
    const fps = Number(fpsArg || 30), n = Math.round(dur * fps);
    for (let i = 0; i < n; i++) await shot(i / fps, path.join(out, `f${String(i).padStart(5, '0')}.jpg`));
  }
  console.log('done', dur);
  await b.close();
})();
