// CAM programming in cloud Fusion: one top setup, strategy variant injected as STRATEGY.
const LIB_URL = 'systemlibraryroot://Samples/Milling Tools (Metric).json';
function findTool(desc: string): any {
  const lib = adsk.cam.CAMManager.get().libraryManager.toolLibraries.toolLibraryAtURL(adsk.core.URL.create(LIB_URL));
  for (let i = 0; i < lib.count; i++) { const t: any = lib.item(i); if (t.parameters.itemByName('tool_description').value.value.trim() === desc) return t; }
  throw new Error('tool not found: ' + desc);
}
function body(): any { return design().rootComponent.bRepBodies.item(0); }
function planarFacesAt(z: number): any[] {
  const out: any[] = []; const fs = body().faces;
  for (let i = 0; i < fs.count; i++) { const f = fs.item(i); const g: any = f.geometry;
    if (g.surfaceType === adsk.core.SurfaceTypes.PlaneSurfaceType && Math.abs(Math.abs(g.normal.z) - 1) < 1e-6 && Math.abs(f.pointOnFace.z / MM - z) < 1e-3) out.push(f); }
  return out.sort((a: any, b: any) => b.area - a.area);
}
function holeFaces(d: number): any[] {
  const out: any[] = []; const fs = body().faces;
  for (let i = 0; i < fs.count; i++) { const g: any = fs.item(i).geometry;
    if (g.surfaceType === adsk.core.SurfaceTypes.CylinderSurfaceType && Math.abs(g.radius / MM * 2 - d) < 1e-3) out.push(fs.item(i)); }
  return out;
}
function outerEdges(face: any): any[] { const out: any[] = []; for (let i = 0; i < face.loops.count; i++) { const l = face.loops.item(i); if (l.isOuter) for (let j = 0; j < l.edges.count; j++) out.push(l.edges.item(j)); } return out; }
function innerEdges(face: any): any[][] { const out: any[][] = []; for (let i = 0; i < face.loops.count; i++) { const l = face.loops.item(i); if (!l.isOuter) { const e: any[] = []; for (let j = 0; j < l.edges.count; j++) e.push(l.edges.item(j)); out.push(e); } } return out; }
function addOp(s: any, strategy: string, tool: any, name: string, params: any): any {
  const oi = s.operations.createInput(strategy); oi.tool = tool; oi.displayName = name;
  for (const k of Object.keys(params || {})) { const p = oi.parameters.itemByName(k); if (p) { try { p.expression = String(params[k]); } catch (e: any) { LOG.push(name + '.' + k + ': ' + e.message); } } else LOG.push(name + ': no param ' + k); }
  const op = s.operations.add(oi);
  for (const k of Object.keys(params || {})) { const p = op.parameters.itemByName(k); if (p) { try { p.expression = String(params[k]); } catch (e: any) {} } }
  return op;
}
function selPockets(op: any, faces: any[]) { const cs = op.parameters.itemByName('pockets').value; const sel = cs.getCurveSelections(); const ps = sel.createNewPocketSelection(); ps.inputGeometry = faces; cs.applyCurveSelections(sel); }
function selChain(op: any, edges: any[], reverse = false) { const cs = op.parameters.itemByName('contours').value; const sel = cs.getCurveSelections(); sel.clear(); const c = sel.createNewChainSelection(); c.inputGeometry = edges; if (reverse) c.isReverted = true; cs.applyCurveSelections(sel); }
function selHoles(op: any, faces: any[]) { op.parameters.itemByName('circularFaces').value.value = faces; }

function program(F: any, S: any) {
  const cam = getCam();
  while (cam.setups.count) cam.setups.item(0).deleteMe();
  const si = cam.setups.createInput(adsk.cam.OperationTypes.MillingOperation); si.models = [body()];
  const s = cam.setups.add(si); s.name = 'OP1 ' + S.name;
  const st = F.stock, pb = F.part_bbox;
  sp(s, 'job_stockMode', "'default'"); sp(s, 'job_stockOffsetMode', "'simple'");
  sp(s, 'job_stockOffsetSides', (st.x[1] - pb.x[1]) + ' mm'); sp(s, 'job_stockOffsetTop', (st.z[1] - pb.z[1]) + ' mm');
  sp(s, 'job_stockOffsetBottom', (pb.z[0] - st.z[0]) + ' mm');
  sp(s, 'wcs_origin_mode', "'modelPoint'"); sp(s, 'wcs_origin_boxPoint', "'top center'"); sp(s, 'job_workOffset', '1');
  const T = S.tools; const tools: any = {};
  for (const k of Object.keys(T)) { tools[k] = findTool(T[k].desc); const tp = tools[k].parameters;
    tp.itemByName('tool_number').expression = k; }
  const ops: any[] = [];
  const setFeeds = (op: any, k: string) => { const f = T[k]; if (f.rpm) sp(op, 'tool_spindleSpeed', f.rpm + ' rpm'); if (f.feed) sp(op, 'tool_feedCutting', f.feed + ' mm/min');
    if (f.feed) { sp(op, 'tool_feedEntry', Math.round(f.feed * 0.5) + ' mm/min'); sp(op, 'tool_feedExit', f.feed + ' mm/min'); sp(op, 'tool_feedPlunge', Math.round(f.feed * 0.3) + ' mm/min'); sp(op, 'tool_feedRamp', Math.round(f.feed * 0.5) + ' mm/min'); } };
  const op1 = addOp(s, 'face', tools['1'], 'Face top', { useStockContours: 'false', stepover: '0.75 * tool_diameter' }); setFeeds(op1, '1'); ops.push(op1);
  if (S.rough === 'adaptive') {
    const o = addOp(s, 'adaptive', tools['2'], 'Adaptive clearing', { optimalLoad: S.optimalLoad + ' mm', maximumStepdown: S.stepdown + ' mm', stockToLeave: '0.2 mm', verticalStockToLeave: '0 mm', flatAreaMachining: 'true', useStockContours: 'false' });
    setFeeds(o, '2'); ops.push(o);
  } else {
    const floor = planarFacesAt(-8)[0];
    const o = addOp(s, 'pocket2d', tools['2'], 'Pocket clearing', { maximumStepover: S.stepover + ' mm', maximumStepdown: S.stepdown + ' mm', stockToLeave: '0.2 mm', verticalStockToLeave: '0 mm', useStockContours: 'false', doMultipleDepths: 'true' });
    selPockets(o, [floor]); setFeeds(o, '2'); ops.push(o);
    const bottom = planarFacesAt(-20)[0];
    const c = addOp(s, 'contour2d', tools['2'], 'Profile roughing', { useStockToLeave: 'true', stockToLeave: '0.2 mm', verticalStockToLeave: '0 mm', doMultipleDepths: 'true', maximumStepdown: S.stepdown + ' mm', useStockContours: 'false' });
    selChain(c, outerEdges(bottom)); setFeeds(c, '2'); ops.push(c);
  }
  const slotFloor = planarFacesAt(-4)[0];
  const o3 = addOp(s, 'pocket2d', tools['3'], 'Slot', { maximumStepover: '2 mm', maximumStepdown: S.slotStepdown + ' mm', doMultipleDepths: 'true', useStockContours: 'false', stockToLeave: '0 mm', verticalStockToLeave: '0 mm' });
  selPockets(o3, [slotFloor]); setFeeds(o3, '3'); ops.push(o3);
  const pf = planarFacesAt(-8)[0];
  const o4 = addOp(s, 'contour2d', tools['2'], 'Finish pocket walls', { useStockContours: 'false' }); selChain(o4, outerEdges(pf), true); setFeeds(o4, '2'); ops.push(o4);
  const o5 = addOp(s, 'contour2d', tools['2'], 'Finish outside profile', { useStockContours: 'false' }); selChain(o5, outerEdges(planarFacesAt(-20)[0])); setFeeds(o5, '2'); ops.push(o5);
  const o6 = addOp(s, 'bore', tools['4'], 'Bore holes', {}); selHoles(o6, holeFaces(6.6).concat(holeFaces(8))); setFeeds(o6, '4'); ops.push(o6);
  const t0 = Date.now(); const fut = cam.generateAllToolpaths(false);
  while (!fut.isGenerationCompleted && Date.now() - t0 < 90000) wait(200);
  const res = ops.map((o: any) => ({ name: o.name, valid: o.hasToolpath && o.isToolpathValid, warning: o.warning || '', error: o.error || '' }));
  return { setup: s.name, gen_ms: Date.now() - t0, ops: res };
}
function post(prog: string) {
  const cam = getCam(); while (cam.ncPrograms.count) cam.ncPrograms.item(0).deleteMe();
  const pl = (adsk.cam.CAMManager.get() as any).libraryManager.postLibrary; const q = pl.createQuery(adsk.cam.LibraryLocations.Fusion360LibraryLocation);
  const post = q.execute().find((p: any) => p.description === 'HAAS (pre-NGC)'); const TMP = cam.temporaryFolder;
  const ni = cam.ncPrograms.createInput(); const Pm = ni.parameters;
  Pm.itemByName('nc_program_filename').value.value = prog; Pm.itemByName('nc_program_name').value.value = prog;
  Pm.itemByName('nc_program_output_folder').value.value = TMP; Pm.itemByName('nc_program_unit').expression = "'Millimeters'";
  ni.operations = [cam.setups.item(0)];
  const nc = cam.ncPrograms.add(ni); nc.postConfiguration = post; nc.postProcess(adsk.cam.NCProgramPostProcessOptions.create());
  const t = Date.now(); while (app.hasActiveJobs && Date.now() - t < 30000) wait(500);
  const fs: any = (globalThis as any).fs; let text = '';
  for (const fn of [prog + '.nc', prog]) { try { text = fs.readFileSync(TMP + '/' + fn, 'utf8'); break; } catch (e) {} }
  if (!text) { try { LOG.push('tmp: ' + JSON.stringify(fs.readdirSync(TMP))); } catch (e) {} }
  return { nc: text };
}
function toolTable(S: any) {
  const out: any = {}; for (const k of Object.keys(S.tools)) { const t: any = findTool(S.tools[k].desc); const g = (n: string) => { const p = t.parameters.itemByName(n); return p ? p.value.value : null; };
    out[k] = { desc: S.tools[k].desc, fusion_type: g('tool_type'), diameter: g('tool_diameter') * 10, flutes: g('tool_numberOfFlutes'), flute_length: g('tool_fluteLength') * 10, tip_angle: g('tool_taperAngle'), corner_radius: (g('tool_cornerRadius') || 0) * 10 }; }
  return { tools: out };
}
