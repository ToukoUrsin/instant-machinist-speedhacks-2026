// STEP upload without external hosting: the file is streamed into Fusion's temp folder in chunks, then imported.
function stepPath(name: string): string { return String(getCam().temporaryFolder).replace(/\\/g, '/') + '/' + name; }
function writeChunk(name: string, text: string, first: boolean) {
  const fs: any = (globalThis as any).fs; const p = stepPath(name);
  const prev = first ? '' : fs.readFileSync(p, 'utf8'); fs.writeFileSync(p, prev + text, 'utf8');
  return { path: p, size: (prev + text).length, fsKeys: Object.keys(fs).join(',') };
}
function importStep(name: string, rotXdeg: number) {
  const p = stepPath(name); const im = app.importManager; const opts = im.createSTEPImportOptions(p);
  const d: any = design(); const root = d.rootComponent;
  im.importToTarget(opts, root);
  const bodies = adsk.core.ObjectCollection.create();
  const occ = root.occurrences; let body: any = null;
  for (let i = 0; i < root.bRepBodies.count; i++) bodies.add(root.bRepBodies.item(i));
  if (bodies.count === 0 && occ.count > 0) { for (let i = 0; i < occ.item(0).bRepBodies.count; i++) bodies.add(occ.item(0).bRepBodies.item(i)); }
  const m = adsk.core.Matrix3D.create();
  m.setToRotation(rotXdeg * Math.PI / 180, adsk.core.Vector3D.create(1, 0, 0), adsk.core.Point3D.create(0, 0, 0));
  const mi = root.features.moveFeatures.createInput2(bodies); mi.defineAsFreeMove(m); root.features.moveFeatures.add(mi);
  body = bodies.item(0) as any; let bb = body.boundingBox;
  const t = adsk.core.Matrix3D.create(); t.translation = adsk.core.Vector3D.create(-(bb.minPoint.x + bb.maxPoint.x) / 2, -(bb.minPoint.y + bb.maxPoint.y) / 2, -bb.maxPoint.z);
  const mi2 = root.features.moveFeatures.createInput2(bodies); mi2.defineAsFreeMove(t); root.features.moveFeatures.add(mi2);
  bb = body.boundingBox;
  return { bodies: bodies.count, faces: body.faces.count, volume_mm3: Math.round(body.volume * 1000),
           bbox_mm: [bb.minPoint.x / MM, bb.minPoint.y / MM, bb.minPoint.z / MM, bb.maxPoint.x / MM, bb.maxPoint.y / MM, bb.maxPoint.z / MM] };
}
function uploadAndImport(chunks: string[], rotXdeg: number) {
  const fs: any = (globalThis as any).fs; const p = stepPath('part.stp');
  fs.writeFileSync(p, chunks.join(''), 'utf8');
  app.userInterface.workspaces.itemById('FusionSolidEnvironment').activate();
  return importStep('part.stp', rotXdeg);
}
function orientImported(rotXdeg: number) {
  const d: any = design(); const root = d.rootComponent;
  const bodies = adsk.core.ObjectCollection.create();
  for (let i = 0; i < root.bRepBodies.count; i++) bodies.add(root.bRepBodies.item(i));
  for (let j = 0; j < root.occurrences.count && bodies.count === 0; j++) { const o = root.occurrences.item(j); for (let i = 0; i < o.bRepBodies.count; i++) bodies.add(o.bRepBodies.item(i)); }
  const m = adsk.core.Matrix3D.create();
  m.setToRotation(rotXdeg * Math.PI / 180, adsk.core.Vector3D.create(1, 0, 0), adsk.core.Point3D.create(0, 0, 0));
  const mi = root.features.moveFeatures.createInput2(bodies); mi.defineAsFreeMove(m); root.features.moveFeatures.add(mi);
  const body: any = bodies.item(0); let bb = body.boundingBox;
  const t = adsk.core.Matrix3D.create(); t.translation = adsk.core.Vector3D.create(-(bb.minPoint.x + bb.maxPoint.x) / 2, -(bb.minPoint.y + bb.maxPoint.y) / 2, -bb.maxPoint.z);
  const mi2 = root.features.moveFeatures.createInput2(bodies); mi2.defineAsFreeMove(t); root.features.moveFeatures.add(mi2);
  bb = body.boundingBox;
  return { bodies: bodies.count, inOccurrence: root.bRepBodies.count === 0, faces: body.faces.count, volume_mm3: Math.round(body.volume * 1000),
           bbox_mm: [bb.minPoint.x / MM, bb.minPoint.y / MM, bb.minPoint.z / MM, bb.maxPoint.x / MM, bb.maxPoint.y / MM, bb.maxPoint.z / MM].map((v: number) => Math.round(v * 100) / 100) };
}
