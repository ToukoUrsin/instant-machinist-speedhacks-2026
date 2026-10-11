// 3D top-side program for an imported STEP part (OP1): face, adaptive rough, rest rough, 3D finishing, bore vertical holes.
function holeFacesZ(dmin: number, dmax: number): any[] {
  const out: any[] = []; const fs = body().faces;
  for (let i = 0; i < fs.count; i++) { const f = fs.item(i); const g: any = f.geometry;
    if (g.surfaceType === adsk.core.SurfaceTypes.CylinderSurfaceType && Math.abs(Math.abs(g.axis.z) - 1) < 1e-6) {
      const d = g.radius * 2 / MM; if (d >= dmin && d <= dmax && f.boundingBox.maxPoint.z / MM > -31 + 1) out.push(f); } }
  return out;
}
function program3d(F: any, S: any) {
  const cam = getCam();
  while (cam.setups.count) cam.setups.item(0).deleteMe();
  const si = cam.setups.createInput(adsk.cam.OperationTypes.MillingOperation); si.models = [body()];
  const s = cam.setups.add(si); s.name = 'OP1 top ' + S.name;
  const st = F.stock, pb = F.part_bbox;
  sp(s, 'job_stockMode', "'default'"); sp(s, 'job_stockOffsetMode', "'simple'");
  sp(s, 'job_stockOffsetSides', (st.x[1] - pb.x[1]) + ' mm'); sp(s, 'job_stockOffsetTop', (st.z[1] - pb.z[1]) + ' mm');
  sp(s, 'job_stockOffsetBottom', (pb.z[0] - st.z[0]) + ' mm');
  sp(s, 'wcs_origin_mode', "'modelPoint'"); sp(s, 'wcs_origin_boxPoint', "'top center'"); sp(s, 'job_workOffset', '1');
  const T = S.tools; const tools: any = {};
  for (const k of Object.keys(T)) { tools[k] = findTool(T[k].desc); tools[k].parameters.itemByName('tool_number').expression = k; }
  const setFeeds = (op: any, k: string) => { const f = T[k]; if (f.rpm) sp(op, 'tool_spindleSpeed', f.rpm + ' rpm');
    if (f.feed) { sp(op, 'tool_feedCutting', f.feed + ' mm/min'); sp(op, 'tool_feedEntry', Math.round(f.feed * 0.5) + ' mm/min'); sp(op, 'tool_feedExit', f.feed + ' mm/min');
      sp(op, 'tool_feedPlunge', Math.round(f.feed * 0.3) + ' mm/min'); sp(op, 'tool_feedRamp', Math.round(f.feed * 0.5) + ' mm/min'); } };
  const ops: any[] = [];
  const bottom = (pb.z[0] - 0.5) + ' mm';
  const o1 = addOp(s, 'face', tools['1'], 'Face top', { useStockContours: 'false', stepover: '0.75 * tool_diameter' }); setFeeds(o1, '1'); ops.push(o1);
  if (S.rough === 'adaptive') {
    const o = addOp(s, 'adaptive', tools['2'], 'Adaptive clearing', { optimalLoad: S.optimalLoad + ' mm', maximumStepdown: S.stepdown + ' mm', stockToLeave: '0.3 mm', verticalStockToLeave: '0.2 mm', flatAreaMachining: 'true', useStockContours: 'false' });
    sp(o, 'bottomHeight_mode', "'from model bottom'"); setFeeds(o, '2'); ops.push(o);
  } else {
    const o = addOp(s, 'pocket_new', tools['2'], 'Pocket clearing', { maximumStepover: S.stepover + ' mm', maximumStepdown: S.stepdown + ' mm', stockToLeave: '0.3 mm', verticalStockToLeave: '0.2 mm', useStockContours: 'false' });
    setFeeds(o, '2'); ops.push(o);
  }
  const o4 = addOp(s, 'contour_new', tools['3'], 'Finish walls', { maximumStepdown: S.wallStepdown + ' mm', useStockContours: 'false' }); setFeeds(o4, '3'); ops.push(o4);
  const o5 = addOp(s, 'parallel_new', tools['5'], 'Finish fins (ball)', { stepover: S.finishStepover + ' mm', useStockContours: 'false' }); setFeeds(o5, '5'); ops.push(o5);
  const holes: any[] = [];
  const t0 = Date.now();
  const res = ops.map((o: any) => ({ name: o.name, valid: o.hasToolpath && o.isToolpathValid, generating: o.isGenerating, warning: o.warning || '', error: o.error || '' }));
  return { setup: s.name, gen_ms: Date.now() - t0, done: false, holes: holes.length, ops: res };
}
function camStatus() {
  const cam = getCam(); const s = cam.setups.item(0); const out: any[] = [];
  for (let i = 0; i < s.operations.count; i++) { const o: any = s.operations.item(i); out.push({ name: o.name, valid: o.hasToolpath && o.isToolpathValid, generating: o.isGenerating, error: o.error || '' }); }
  return { ops: out };
}
// Toolpath generation only advances while a script pumps events; run this in short slices until nothing is generating.
function pump(ms: number) {
  const t0 = Date.now(); let st: any = camStatus();
  while (st.ops.some((o: any) => o.generating) && Date.now() - t0 < ms) { wait(500); st = camStatus(); }
  return st;
}

function genOp(i: number, ms: number) {
  const cam = getCam(); const op: any = cam.setups.item(0).operations.item(i); const t0 = Date.now();
  const fut = cam.generateToolpath(op);
  while (!fut.isGenerationCompleted && Date.now() - t0 < ms) wait(250);
  return { name: op.name, done: fut.isGenerationCompleted, ms: Date.now() - t0, valid: op.hasToolpath && op.isToolpathValid, error: op.error || '', warning: op.warning || '' };
}
