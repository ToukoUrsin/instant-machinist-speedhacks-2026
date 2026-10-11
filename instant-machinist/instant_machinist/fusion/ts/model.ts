// Builds the part from the features JSON (injected as FEATURES) — the drawing-to-model step.
function roundedRect(sk: any, cx: number, cy: number, w: number, h: number, r: number) {
  const L = sk.sketchCurves.sketchLines, A = sk.sketchCurves.sketchArcs;
  const x0 = cx - w / 2, x1 = cx + w / 2, y0 = cy - h / 2, y1 = cy + h / 2;
  if (r <= 0) { L.addTwoPointRectangle(P(x0, y0), P(x1, y1)); return; }
  const seg = (a: any, b: any) => { if (Math.hypot(a[0] - b[0], a[1] - b[1]) > 1e-6) L.addByTwoPoints(P(a[0], a[1]), P(b[0], b[1])); };
  seg([x0 + r, y0], [x1 - r, y0]); seg([x1, y0 + r], [x1, y1 - r]); seg([x1 - r, y1], [x0 + r, y1]); seg([x0, y1 - r], [x0, y0 + r]);
  A.addByCenterStartSweep(P(x1 - r, y0 + r), P(x1 - r, y0), Math.PI / 2);
  A.addByCenterStartSweep(P(x1 - r, y1 - r), P(x1, y1 - r), Math.PI / 2);
  A.addByCenterStartSweep(P(x0 + r, y1 - r), P(x0 + r, y1), Math.PI / 2);
  A.addByCenterStartSweep(P(x0 + r, y0 + r), P(x0, y0 + r), Math.PI / 2);
}
function planeAt(root: any, z: number): any {
  if (Math.abs(z) < 1e-9) return root.xYConstructionPlane;
  const pi = root.constructionPlanes.createInput();
  pi.setByOffset(root.xYConstructionPlane, adsk.core.ValueInput.createByReal(z * MM));
  return root.constructionPlanes.add(pi);
}
function smallestProfile(sk: any): any {
  let best: any = null, area = 1e99;
  for (let i = 0; i < sk.profiles.count; i++) { const p = sk.profiles.item(i); const a = p.areaProperties().area; if (a < area) { area = a; best = p; } }
  return best;
}
function buildPart(F: any) {
  const d: any = design(); d.designType = adsk.fusion.DesignTypes.ParametricDesignType;
  const root = d.rootComponent; const ex = root.features.extrudeFeatures;
  const NEW = adsk.fusion.FeatureOperations.NewBodyFeatureOperation, CUT = adsk.fusion.FeatureOperations.CutFeatureOperation;
  const prof = F.features.find((f: any) => f.type === 'profile');
  const sk0 = root.sketches.add(root.xYConstructionPlane); sk0.name = 'Outline';
  roundedRect(sk0, prof.rect.cx, prof.rect.cy, prof.rect.w, prof.rect.h, prof.rect.r);
  const body = ex.addSimple(sk0.profiles.item(0), adsk.core.ValueInput.createByReal((prof.z_bottom - prof.z_top) * MM), NEW).bodies.item(0);
  body.name = F.part_number;
  for (const f of F.features) {
    if (f.type === 'pocket') {
      const sk = root.sketches.add(planeAt(root, f.z_top)); sk.name = f.id;
      roundedRect(sk, f.rect.cx, f.rect.cy, f.rect.w, f.rect.h, f.rect.r);
      const ei = ex.createInput(smallestProfile(sk), CUT); ei.setDistanceExtent(false, adsk.core.ValueInput.createByReal((f.z_bottom - f.z_top) * MM));
      ei.participantBodies = [body]; ex.add(ei).name = f.id;
    } else if (f.type === 'hole') {
      const sk = root.sketches.add(planeAt(root, f.z_top)); sk.name = f.id;
      for (const p of f.positions) sk.sketchCurves.sketchCircles.addByCenterRadius(P(p[0], p[1]), f.d / 2 * MM);
      const profs = adsk.core.ObjectCollection.create();
      for (let i = 0; i < sk.profiles.count; i++) profs.add(sk.profiles.item(i));
      const ei = ex.createInput(profs, CUT); ei.setDistanceExtent(false, adsk.core.ValueInput.createByReal((f.z_bottom - f.z_top - 0.5) * MM));
      ei.participantBodies = [body]; ex.add(ei).name = f.id;
    }
  }
  const bb = body.boundingBox;
  return { body: body.name, volume_mm3: Math.round(body.volume * 1000), faces: body.faces.count,
           bbox_mm: [bb.minPoint.x / MM, bb.minPoint.y / MM, bb.minPoint.z / MM, bb.maxPoint.x / MM, bb.maxPoint.y / MM, bb.maxPoint.z / MM] };
}
function newDoc(name: string) {
  const doc: any = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType);
  try { doc.name = name; } catch (e) {}
  return { doc: doc.name };
}
