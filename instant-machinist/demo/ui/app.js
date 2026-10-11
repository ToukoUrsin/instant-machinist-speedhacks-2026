// Instant Machinist replay: renders the UI as a pure function of video time v (seconds).
// window.__render(v) is used by the headless recorder; otherwise it autoplays.
// URL params: ?speed=N (constant replay speed, run seconds per video second) — default is VO-synced pacing.
(() => {
  const RUN = window.RUN, E = RUN.events, S = RUN.summary;
  const qs = new URLSearchParams(location.search);
  const $ = (id) => document.getElementById(id);
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const ease = (x) => 1 - Math.pow(1 - clamp(x), 3);
  const prog = (v, t0, d = 0.45) => ease((v - t0) / d);
  const mmss = (s) => s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}` : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const ev = (step, pred = () => true) => E.find((e) => e.step === step && pred(e));

  // ---- key run times (real) ----
  const tRead = ev("drawing").t;
  const specEv = E.find((e) => e.step === "drawing" && (e.spec || e.notes || e.questions));
  const tSpec = specEv.t;
  const spec = specEv.spec || (() => {   // drawing read without a feature list (e.g. GD&T-only sheets): use what Claude returned
    const sf = RUN.spec_file || {}, tol = (specEv.msg.match(/±([\d.]+) mm/) || [])[1];
    return { part_number: sf.part_number, name: sf.name, units: sf.units, setup: sf.setup, material: specEv.material || sf.material,
             general_tolerance_mm: tol ? +tol : null, features: [], notes: specEv.notes || [], questions_for_customer: specEv.questions || [] };
  })();
  // GD&T callouts Claude wrote into its machining notes (in-scope notes only), plus the count of flagged out-of-scope items
  const gdtChips = [];
  let outOfScope = 0;
  {
    const D = "(?:Ø|[Dd]ia\\.?)\\s*", N = "(\\d+(?:\\.\\d+)?)";
    for (const n of (specEv.notes || spec.notes || [])) {
      if (/^(OUT OF SCOPE|Out of scope|NOT machinable)/i.test(n)) {
        const body = n.includes(":") ? n.slice(n.indexOf(":") + 1) : "";
        const k = body.split(";").map((x) => x.trim()).filter(Boolean).length;
        outOfScope += /^OUT OF SCOPE/.test(n) && k <= 1 ? 0 : Math.max(1, k); continue;
      }
      if (/^(General|Untoleranced)/i.test(n)) continue;
      const pre = [], tol = [];
      let m;
      if ((m = n.match(/^Datum ([A-Z])\b/) || n.match(/datum feature ([A-Z])\b/i))) pre.push(`Datum ${m[1]}`);
      else if (/^(F\d+\s*)?(top\s+)?pocket/i.test(n)) pre.push("Pocket");
      if ((m = n.match(new RegExp(`(\\d+)X\\s*${D}${N}\\s*\\+\\/-\\s*${N}`)))) pre.push(`${m[1]}× Ø${m[2]} ±${m[3]}`);
      else if ((m = n.match(new RegExp(`${D}${N}\\s*\\+\\/-\\s*${N}`)))) pre.push(`Ø${m[1]} ±${m[2]}`);
      if ((m = n.match(new RegExp(`flatness\\s*${N}`, "i")))) tol.push(`flatness ${m[1]}`);
      if ((m = n.match(new RegExp(`profile (?:of a surface\\s*)?${N}`, "i")))) tol.push(`profile ${m[1]}`);
      if ((m = n.match(new RegExp(`perpendicular(?:ity)?[^Ø\\d]*${D}${N}`, "i")))) tol.push(`⊥ Ø${m[1]}`);
      if ((m = n.match(new RegExp(`position\\s*${D}${N}`, "i")))) tol.push(`pos Ø${m[1]}`);
      if (pre.length && tol.length) gdtChips.push({ k: pre.shift(), v: [...pre, ...tol].join(" · ") });
    }
  }
  const tFusion = ev("fusion").t;
  const modelEv = ev("model", (e) => e.faces);
  const tModel = modelEv.t;
  const resultEv = ev("result");
  const tResult = resultEv.t;
  const doneEv = ev("done"), tDone = doneEv.t;
  const saveEv = E.find((e) => e.step === "fusion" && /Saved/.test(e.msg));
  const strategies = [];
  for (const e of E) {
    if (e.t > tResult) break;
    if (e.step === "toolpaths") strategies.push({ id: e.strategy, tTp: e.t, ops: e.ops.length, msg: e.msg });
    const s = strategies.find((x) => x.id === e.strategy);
    if (s && e.step === "post") { s.tPost = e.t; s.lines = +(e.msg.match(/(\d+) lines/) || [])[1]; }
    if (s && e.step === "verify") { s.tVer = e.t; s.cycle = e.cycle_s; s.pass = e.pass; s.base = e.baseline; s.checks = e.checks; s.label = e.label; }
  }
  const baseCycle = S.baseline.cycle_s, bestId = S.best.strategy;

  // ---- time map: video seconds -> run seconds ----
  const speed = parseFloat(qs.get("speed") || "0");
  // sync anchors (video seconds) from the narration's word timings; defaults match the original take
  const A = { drop: 3.4, spec: 6.9, fusion: 10.9, model: 14.2, tp: 17.2, result: 29.6 };
  if (RUN.vo && RUN.vo.solution) {
    const W = RUN.vo.solution, off = RUN.vo.offset || 0.8;
    const at = (re, after = 0) => { const w = W.find((x) => x[1] >= after && re.test(x[0])); return w ? w[1] + off : null; };
    const dw = at(/^drawing/), ma = at(/^material/), dr = at(/^drives/), md = at(/^(3D|model|customer)/i, dr - off), tl = at(/^toolpaths/), on = at(/^only/i);
    if (dw && ma && dr && md && tl && on) Object.assign(A, { drop: dw + 0.2, spec: ma - 0.1, fusion: dr, model: md - 0.1, tp: tl - 0.6, result: on - 0.4 });
  }
  const T_DROP = A.drop;
  const knots = speed ? null : [[T_DROP, 0], [T_DROP + 0.5, tRead], [A.spec, tSpec], [A.fusion, tFusion], [A.model, tModel],
    [A.tp, strategies[0].tTp], [A.tp + 1.8, strategies[0].tVer], [A.result, tResult], [A.result + 3.0, tDone]];
  function rOf(v) {
    if (speed) return Math.max(0, (v - T_DROP) * speed);
    if (v <= knots[0][0]) return 0;
    for (let i = 1; i < knots.length; i++) {
      const [v0, r0] = knots[i - 1], [v1, r1] = knots[i];
      if (v <= v1) return r0 + (r1 - r0) * (v - v0) / (v1 - v0);
    }
    return tDone + (v - knots[knots.length - 1][0]) * 0; // hold
  }
  function vOf(r) {
    if (speed) return T_DROP + r / speed;
    for (let i = 1; i < knots.length; i++) {
      const [v0, r0] = knots[i - 1], [v1, r1] = knots[i];
      if (r <= r1) return v0 + (v1 - v0) * (r - r0) / (r1 - r0 || 1);
    }
    return knots[knots.length - 1][0];
  }
  const V_RESULT = parseFloat(qs.get("result") || "") || vOf(tDone) + 1.8;

  // ---- part / static content ----
  const P = RUN.part || {};
  $("dwgimg").src = P.drawing; $("bigimg").src = P.drawing; $("modelimg").src = P.model;
  $("cust").textContent = P.customer || "Customer";
  $("ptitle").textContent = P.title || [spec.part_number, spec.name].filter(Boolean).join(" ");
  $("dfsub").textContent = [spec.part_number, P.file_kb ? `${P.file_kb} KB` : ""].filter(Boolean).join(" · ");
  document.title = `Instant Machinist · ${P.title || spec.part_number}`;
  $("dropmeta").textContent = "";
  const fmtFeat = (f) => {
    const r = f.rect || {};
    try {
    if (f.type === "face") return ["Face", "top"];
    if (f.type === "profile") return ["Profile", `${r.w}×${r.h} R${r.r}`];
    if (f.type === "pocket") {
      const depth = -f.z_bottom;
      return r.h === 2 * r.r ? ["Slot", `${r.w}×${r.h}, ${depth} deep`] : ["Pocket", `${r.w}×${r.h}, ${depth} deep`];
    }
    if (f.type === "hole") return ["Holes", `${f.positions.length}× Ø${f.d}${f.through ? " thru" : ""}`];
    } catch (e) {}
    const t = String(f.type || "feature"); return [t.charAt(0).toUpperCase() + t.slice(1), f.d ? `Ø${f.d}` : (f.label || f.note || "")];
  };
  const isSM = /SM-101/i.test(spec.part_number || "");   // drawing boxes are only placed for the sheet we measured
  const mat = /not specified/i.test(spec.material || "") ? "not given · asked customer" : String(spec.material || "").replace(/\s*\((assumed)[^)]*\)/i, " · $1");
  const std = ((specEv.notes || spec.notes || []).join(" ").match(/ASME Y14\.5M?-\d{4}/) || [])[0];
  const specChips = [
    spec.material && { k: "Material", v: mat, box: [1167, 1160, 1470, 1205] },
    spec.quantity && { k: "Qty", v: String(spec.quantity), box: [1666, 1205, 1750, 1256] },
    spec.general_tolerance_mm && { k: "Tolerance", v: `±${spec.general_tolerance_mm} mm`, box: [1167, 1018, 1470, 1075] },
    spec.surface_finish_ra_um && { k: "Finish", v: `Ra ${spec.surface_finish_ra_um} µm`, box: [1167, 1203, 1470, 1256] },
    !spec.surface_finish_ra_um && spec.units && { k: "Units", v: spec.units },
    std && { k: "Standard", v: std },
    spec.setup && { k: "Setup", v: String(spec.setup).split(/[(,;]/)[0].trim() },
  ].filter(Boolean).slice(0, 5);
  specChips.forEach((c, i) => { c.off = [0, 0.5, 1.0, 1.3, 1.55][i]; if (!isSM) delete c.box; });
  const featBoxes = {
    F1: [[262, 862, 1052, 1000]], F2: [[262, 166, 1052, 696]], F3: [[446, 311, 868, 552]], F4: [[523, 596, 791, 656]],
    F5: [[311, 215, 355, 259, "r"], [959, 215, 1003, 259, "r"], [311, 604, 355, 648, "r"], [959, 604, 1003, 648, "r"]],
    F6: [[501, 406, 553, 458, "r"], [761, 406, 813, 458, "r"]],
  };
  const FEATS = spec.features.slice(0, 10);
  let featChips = FEATS.map((f) => { const [k, v] = fmtFeat(f); return { id: f.id, k, v }; });
  const featLabel = featChips.length ? `${spec.features.length} features` : `${gdtChips.length} GD&T callouts read`;
  if (!featChips.length) featChips = gdtChips.map((c) => ({ id: c.k, k: "", v: c.v }));
  if (outOfScope) featChips.push({ id: "", k: "", v: `${outOfScope} out-of-scope items flagged`, warn: true });
  featChips.forEach((c, i) => { c.off = 1.75 + Math.min(0.17, 1.3 / Math.max(1, featChips.length)) * i; });

  // boxes on drawing
  const boxesEl = $("boxes"), boxEls = [];
  const addBox = (b, t) => {
    const d = document.createElement("div");
    d.className = "box" + (b[4] === "r" ? " round" : "");
    Object.assign(d.style, { left: (b[0] / 20) + "%", top: (b[1] / 12.93) + "%", width: ((b[2] - b[0]) / 20) + "%", height: ((b[3] - b[1]) / 12.93) + "%" });
    boxesEl.appendChild(d); boxEls.push({ el: d, t });
  };
  const vSpec = vOf(tSpec);
  if (isSM) { specChips.forEach((c) => c.box && addBox(c.box, vSpec + c.off)); featChips.forEach((c) => (featBoxes[c.id] || []).forEach((b) => addBox(b, vSpec + c.off))); }

  // questions
  const qs_ = specEv.questions || spec.questions_for_customer || [];
  $("qcount").textContent = `${qs_.length} drafted`;
  const qEls = qs_.map((q, i) => {
    const d = document.createElement("div"); d.className = "q";
    d.innerHTML = `<span class="qn">${i + 1}</span><span class="qt"></span>`;
    d.querySelector(".qt").textContent = q; $("qlist").appendChild(d); return d;
  });

  // feed items
  const feed = $("feed");
  const items = [];
  const mkItem = (o) => {
    const d = document.createElement("div"); d.className = "item";
    d.innerHTML = `<div class="ico"></div><div class="ibody"><div class="ititle"><span class="t"></span><span class="ts"></span></div><div class="isub"></div></div>`;
    feed.appendChild(d); o.el = d; o.ico = d.querySelector(".ico"); o.tEl = d.querySelector(".t"); o.tsEl = d.querySelector(".ts"); o.sub = d.querySelector(".isub");
    items.push(o); return o;
  };
  mkItem({ t0: 0, t1: tRead, title: ["Drawing received", "Drawing received"], sub: [P.file, spec.part_number, P.customer].filter(Boolean).join(" · ") });
  const readItem = mkItem({ t0: tRead, t1: tSpec, title: ["Claude is reading the drawing…", "Drawing read by Claude Opus 5.5"], sub: "" });
  { // chips
    const box = document.createElement("div"); box.className = "chips";
    specChips.forEach((c) => { const s = document.createElement("span"); s.className = "chip"; s.innerHTML = `<span class="k">${c.k}</span>${c.v}`; box.appendChild(s); c.el = s; });
    const lab = document.createElement("div"); lab.className = "chiplabel"; lab.textContent = featLabel; if (!featChips.length) lab.style.display = "none"; box.appendChild(lab); readItem.lab = lab;
    featChips.forEach((c) => { const s = document.createElement("span"); s.className = "chip f" + (c.warn ? " warn" : ""); s.innerHTML = (c.id ? `<span class="k">${c.id}</span>` : "") + [c.k, c.v].filter(Boolean).join(" "); box.appendChild(s); c.el = s; });
    readItem.el.querySelector(".ibody").appendChild(box);
  }
  mkItem({ t0: tFusion, t1: tModel, title: ["Starting Autodesk Fusion in the cloud…", "Autodesk Fusion running in the cloud"], sub: "Fusion Compute MCP · Design Automation" });
  const st = (() => { const r = (window.RUN_SPEC_STOCK || null); return r; })();
  const imported = /STEP|import/i.test(modelEv.msg);
  mkItem({ t0: tModel, t1: tModel, title: imported ? ["Customer STEP imported", "Customer 3D model imported into Fusion"] : ["3D model built", "3D model built from the drawing"], sub: `${modelEv.faces} faces · ${(modelEv.volume_mm3 / 1000).toFixed(1)} cm³ · stock, WCS and fixture set` });
  const parms = (s) => {
    const lab = s.label || (S.variants.find((v) => v.strategy === s.id) || {}).label || "";
    if (lab.includes(":")) return lab.split(":").slice(1).join(":").trim().replace(/, /g, " · ");
    if (/^Adaptive/i.test(lab)) return lab.replace(/^Adaptive( clearing)?,?\s*/i, "").replace(/, /g, " · ");
    const m = s.id.match(/L([\d.]+)-D(\d+)/); return m ? `${m[1]} mm load · ${m[2]} mm steps` : lab;
  };
  const shortChecks = (c) => String(c).replace(/rapid crashes/g, "crashes").replace(/short plunges flagged/g, "plunges flagged").replace(/left for next setups/g, "for later setups").replace(/, /g, " · ");
  const niceName = (s) => s.base ? "Typical manual program" : "Adaptive clearing";
  strategies.forEach((s, i) => {
    s.item = mkItem({ t0: s.tTp, t1: s.tVer, strat: s, title: [`Program ${i + 1} of ${strategies.length} · ${niceName(s)}`, `Program ${i + 1} of ${strategies.length} · ${niceName(s)}`], sub: "" });
  });
  const winItem = mkItem({ t0: tResult, t1: tResult, win: true, title: ["", `Winner: program ${strategies.findIndex((s) => s.id === bestId) + 1}, fastest verified`],
    sub: `${mmss(S.best.cycle_s)} cycle vs ${mmss(baseCycle)} typical manual (our estimate) · ${Math.round(S.machining_saved_pct)}% less machine time` });
  mkItem({ t0: saveEv.t, t1: saveEv.t, title: ["", "Editable Fusion file saved"], sub: `${(saveEv.msg.match(/'([^']+)'/) || [, "Instant Machinist"])[1]} · Fusion Team` });
  mkItem({ t0: tDone, t1: tDone, title: ["", `Programmed in ${mmss(tDone)}`], sub: "Ready for review" });

  // strategy rows
  const rows = $("rows");
  strategies.forEach((s) => {
    const d = document.createElement("div"); d.className = "trow r" + (s.base ? " base" : "");
    const nm = s.base ? `Typical manual<small>our estimate</small>` : (() => { const m = s.id.match(/L([\d.]+)-D(\d+)/); return m ? `Adaptive ${m[1]} mm, ${m[2]} mm steps` : niceName(s); })();
    d.innerHTML = `<span class="nm">${nm}</span><span class="ops">${s.ops}</span><span class="c-bar"><span class="bar"><i></i></span><span class="cyc2">—</span></span><span class="sim pend">…</span>`;
    rows.appendChild(d); s.row = d; s.bar = d.querySelector(".bar i"); s.cyc = d.querySelector(".cyc2"); s.sim = d.querySelector(".sim");
  });

  // gcode
  const esc = (x) => x.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  const hl = (line) => {
    if (/^\s*\(/.test(line)) return `<span class="c">${esc(line)}</span>`;
    return esc(line).replace(/\b(N\d+)\b/g, '<span class="ln">$1</span>').replace(/\b(G\d+)\b/g, '<span class="g">$1</span>')
      .replace(/\b(M\d+)\b/g, '<span class="m">$1</span>').replace(/\b(T\d+)\b/g, '<span class="t">$1</span>')
      .replace(/\b([FS][\d.]+)/g, '<span class="f">$1</span>');
  };
  $("gpre").innerHTML = RUN.gcode.map(hl).join("\n");
  

  const res = S;
  $("rprog").textContent = mmss(tDone);
  $("rbest").textContent = mmss(res.best.cycle_s);
  $("rbase").textContent = mmss(baseCycle);
  $("rpct").textContent = `−${Math.round(res.machining_saved_pct)}%`;
  { const br = RUN.reports[bestId]; document.querySelector(".r-stat:nth-of-type(3) .r-note, #rpctnote") ; const n = document.getElementById("rpctnote"); if (n) n.textContent = br ? `every part, ${br.gouge} gouges` : "every part, verified"; }

  const fade = (el, p, dy = 6) => { el.style.opacity = p; el.style.transform = p >= 1 ? "" : `translateY(${(1 - p) * dy}px)`; };


  // ---- camera: gentle push-ins, rendered in-page so text stays crisp (2x DPR) ----
  const CAM = qs.get("cam") === "0" ? null : [
    [0, 1, 480, 270], [A.drop - 1.4, 1, 480, 270], [A.drop - 0.4, 1.42, 200, 250], [A.spec - 1.3, 1.42, 200, 250], [A.spec - 0.1, 1.34, 330, 250],
    [A.fusion - 0.7, 1.34, 360, 250], [A.fusion + 0.7, 1.0, 480, 270], [A.model - 0.8, 1.0, 480, 270], [A.model + 0.6, 1.28, 760, 230], [A.tp + 0.2, 1.28, 760, 260],
    [A.tp + 1.6, 1.12, 640, 300], [A.result - 1.0, 1.12, 640, 300], [A.result + 0.8, 1.36, 790, 440], [V_RESULT - 1.0, 1.36, 790, 440], [V_RESULT, 1.0, 480, 270]];
  function camAt(v) {
    if (!CAM) return [1, 480, 270];
    if (v <= CAM[0][0]) return CAM[0].slice(1);
    for (let i = 1; i < CAM.length; i++) {
      const a = CAM[i - 1], b = CAM[i];
      if (v <= b[0]) { const x = (v - a[0]) / (b[0] - a[0]); const k = x * x * (3 - 2 * x);
        return [a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k, a[3] + (b[3] - a[3]) * k]; }
    }
    return CAM[CAM.length - 1].slice(1);
  }
  function applyCam(v) {
    const [sc, cx, cy] = camAt(v);
    const tx = Math.min(0, Math.max(960 - 960 * sc, 480 - cx * sc)), ty = Math.min(0, Math.max(540 - 540 * sc, 270 - cy * sc));
    const app = document.getElementById("app");
    app.style.transformOrigin = "0 0"; app.style.transform = `translate(${tx}px, ${ty}px) scale(${sc})`;
  }
  // ---- render ----
  function render(v) {
    applyCam(v);
    const r = rOf(v);
    // header timer
    const tr = Math.min(r, tDone);
    $("timerv").textContent = mmss(v < T_DROP ? 0 : tr);
    $("timer").classList.toggle("done", r >= tDone);

    // drag file
    const df = $("dragfile");
    const a0 = T_DROP - 1.3, a1 = T_DROP;
    if (v < a0 - 0.2 || v > a1 + 0.35) df.style.opacity = 0;
    else {
      const p = ease((v - a0) / (a1 - a0));
      const x = 40 + (70 - 40) * p, y = 520 + (140 - 520) * p;
      df.style.opacity = v > a1 ? clamp(1 - (v - a1) / 0.35) : clamp((v - a0 + 0.2) / 0.3);
      df.style.transform = `translate(${x}px, ${y}px) scale(${v > a1 ? 1 - 0.15 * clamp((v - a1) / 0.35) : 1}) rotate(${(1 - p) * -4}deg)`;
    }
    const dz = $("dropzone");
    dz.classList.toggle("hot", v > a1 - 0.5 && v < a1 + 0.1);
    dz.classList.toggle("filled", v >= a1 + 0.1);
    $("dzEmpty").style.opacity = v >= a1 + 0.1 ? 0 : 1;
    $("dwg").style.opacity = prog(v, a1 + 0.05, 0.35);
    $("dropmeta").textContent = v >= a1 ? "drawing.pdf · 1 sheet" : "";
    // big drawing lightbox: the sheet pops out while Claude reads it, then settles into the card
    {
      const g0 = T_DROP + 0.1, g1 = g0 + 0.6, h1 = vSpec - 0.7, s1 = h1 + 0.6;
      const big = $("bigdwg"), dim = $("bigdim");
      if (v < g0 || v > s1 + 0.2 || qs.get("lightbox") === "0") { big.style.opacity = 0; dim.style.opacity = 0; }
      else {
        const zr = dz.getBoundingClientRect();
        const im = $("bigimg"), ar = (im.naturalWidth || 4) / (im.naturalHeight || 3);
        let bw = 880, bh = bw / ar; if (bh > 452) { bh = 452; bw = bh * ar; }
        const B = [480 - bw / 2, 284 - bh / 2, bw, bh];
        const zh = zr.width / ar, Z = [zr.left, zr.top + (zr.height - zh) / 2, zr.width, zh];
        const k = v < h1 ? ease((v - g0) / (g1 - g0)) : 1 - ease((v - h1) / (s1 - h1));
        const R = Z.map((z, i) => z + (B[i] - z) * k);
        Object.assign(big.style, { left: R[0] + "px", top: R[1] + "px", width: R[2] + "px", height: R[3] + "px", borderRadius: (7 + 3 * k) + "px" });
        big.style.opacity = v > s1 ? clamp(1 - (v - s1) / 0.2) : clamp((v - g0) / 0.12);
        dim.style.opacity = k;
        const ph = clamp((v - g1) / (h1 - g1));
        $("bigscan").style.opacity = v > g1 && v < h1 ? 0.85 : 0;
        $("bigscan").style.top = `calc(${ph * 100}% - 40px)`;
        $("bigtag").style.opacity = clamp((v - g1) / 0.3) * clamp((h1 - v) / 0.2);
      }
    }
    // scanning while Claude reads
    const scan = $("scan");
    if (r > tRead && v < vSpec + 2.6) {
      const ph = ((v - vOf(tRead)) / 1.6) % 1;
      scan.style.opacity = 0.9 * clamp((vSpec + 2.6 - v) / 0.4);
      scan.style.top = `calc(${ph * 100}% - 26px)`;
    } else scan.style.opacity = 0;
    boxEls.forEach((b) => { const p = prog(v, b.t, 0.3); const fadeOut = clamp((vSpec + 4.2 - v) / 0.6); b.el.style.opacity = p * fadeOut; });

    // questions
    fade($("questions"), prog(v, vSpec + 2.6, 0.5) * (1 - prog(v, V_RESULT - 0.3, 0.4)));
    qEls.forEach((q, i) => fade(q, prog(v, vSpec + 2.8 + i * 0.18, 0.4), 4));

    // feed
    $("feedmeta").textContent = v < T_DROP ? "waiting for drawing" : r >= tDone ? `done · ${mmss(tDone)}` : "running";
    const spin = (v * 360 * 1.4) % 360;
    items.forEach((it) => {
      const vis = r >= it.t0 && v >= T_DROP;
      const p = vis ? prog(v, vOf(it.t0), 0.4) : 0;
      fade(it.el, p);
      it.el.style.display = vis ? "" : "none";
      if (!vis) return;
      const done = r >= it.t1;
      it.ico.className = "ico " + (it.win ? "win" : done ? "done" : "run");
      it.ico.style.setProperty("--spin", spin + "deg");
      it.tEl.textContent = done ? it.title[1] : it.title[0];
      it.tsEl.textContent = it.strat && done ? "" : `${(done ? it.t1 : it.t0).toFixed(1)} s`;
      if (it.strat) {
        const s = it.strat;
        if (done) { it.tsEl.innerHTML = `<span class="cyc" style="color:${!s.pass ? "#F26D6D" : s.base ? "#E7C38A" : "#3DD68C"}">${mmss(s.cycle)} ${s.pass ? "✓" : "✗"}</span>`; }
        const rep = RUN.reports[s.id];
        it.sub.innerHTML = `${parms(s)}<br>` + (r < s.tPost ? `Fusion generating ${s.ops} toolpaths…` : !done ? `${s.lines.toLocaleString()} lines of Haas G-code · simulating…`
          : `${s.ops} ops · ${s.lines.toLocaleString()} lines · ` + (s.checks ? (s.pass ? "" : `<span style="color:#F26D6D">Verifier caught it, not shipped:</span> `) + shortChecks(s.checks) : rep ? `${rep.gouge} gouges · ${rep.leftover} leftover · ${rep.rapid_into_stock} crashes` : `verified by simulator`));
      } else it.sub.textContent = it.sub_ || it.sub.textContent || "";
    });
    items.forEach((it) => { if (!it.strat && it.subText === undefined) { } });
    // chips
    [...specChips, ...featChips].forEach((c) => fade(c.el, prog(v, vSpec + c.off, 0.3), 3));
    fade(readItem.lab, prog(v, vSpec + 1.6, 0.3), 2);
    // feed autoscroll: keep last visible item in view (reserve space under result card)
    const wrapH = feed.parentElement.clientHeight;
    const reserve = v >= V_RESULT ? 104 * prog(v, V_RESULT, 0.6) : 0;
    const h = feed.scrollHeight;
    const target = Math.max(0, h - (wrapH - reserve));
    feed._y = target; // deterministic
    feed.style.transform = `translateY(${-target}px)`;

    // model card
    $("vpwait").style.opacity = 1 - prog(v, vOf(tFusion), 0.4); $("viewport").style.opacity = prog(v, vOf(tFusion), 0.5);
    const pm = prog(v, vOf(tModel), 0.8);
    $("modelimg").style.opacity = pm;
    $("modelimg").style.transform = `translate(-50%, -50%) scale(${0.92 + 0.08 * pm})`;
    $("modelmeta").textContent = r >= tModel ? `● ${modelEv.faces} faces · ${(modelEv.volume_mm3 / 1000).toFixed(1)} cm³` : r >= tFusion ? "building…" : "waiting";
    $("modelmeta").classList.toggle("on", r >= tModel);

    // strategy table
    
    let nDone = 0;
    strategies.forEach((s) => {
      const vis = r >= s.tTp;
      fade(s.row, vis ? prog(v, vOf(s.tTp), 0.35) : 0, 4);
      if (r >= s.tVer) {
        nDone++;
        const p = prog(v, vOf(s.tVer), 0.7);
        s.bar.style.width = (100 * p * s.cycle / baseCycle) + "%";
        s.cyc.textContent = mmss(s.cycle); s.cyc.style.opacity = clamp(p * 2);
        s.sim.textContent = s.pass ? "✓" : "✗"; s.sim.className = "sim " + (s.pass ? "ok" : "bad");
      } else { s.bar.style.width = "0%"; s.cyc.textContent = vis ? "…" : "—"; s.sim.textContent = r >= (s.tPost || 1e9) ? "sim" : "…"; s.sim.className = "sim pend"; }
      const win = s.id === bestId && r >= tResult;
      s.row.classList.toggle("win", win);
      const nm = s.row.querySelector(".nm");
      
    });
    $("stratmeta").textContent = r >= strategies[0].tTp ? `${strategies.filter((x) => r >= x.tVer && x.pass).length}/${strategies.length} passed` : "waiting";

    // gcode
    $("gmeta").textContent = r >= tResult ? `${RUN.gcode_total.toLocaleString()} lines · winner` : "waiting";
    $("gpre").style.opacity = prog(v, vOf(tResult) + 0.2, 0.5); $("gwait").style.opacity = 1 - prog(v, vOf(tResult), 0.3);
    const gl = Math.max(0, (v - vOf(tResult) - 0.6) * 16);
    $("gpre").style.transform = `translateY(${-gl * 12.5}px)`;

    // result card
    const pr = prog(v, V_RESULT, 0.6);
    const rc = $("result");
    rc.style.opacity = pr; rc.style.transform = `translateY(${(1 - pr) * 24}px) scale(${0.98 + 0.02 * pr})`;
  }
  window.__render = render;
  window.__duration = parseFloat(qs.get("dur") || "") || (V_RESULT + 4.5);
  window.__ready = document.fonts.ready.then(() => Promise.all([...document.images].map((im) => im.decode().catch(() => {}))));
  if (!qs.has("manual")) {
    const t0 = performance.now();
    const loop = () => { render((performance.now() - t0) / 1000); requestAnimationFrame(loop); };
    window.__ready.then(loop);
  }
})();
