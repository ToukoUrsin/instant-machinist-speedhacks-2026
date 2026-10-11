// Shared helpers prepended to every Instant Machinist Fusion script. Fusion API lengths are cm.
const app: any = adsk.core.Application.get();
const MM = 0.1;
const LOG: string[] = [];
function wait(ms: number) { const t = Date.now(); while (Date.now() - t < ms) adsk.doEvents(); }
function P(x: number, y: number, z = 0) { return adsk.core.Point3D.create(x * MM, y * MM, z * MM); }
function design(): any { return app.activeDocument.products.itemByProductType('DesignProductType') as any; }
function getCam(): any {
  const doc: any = app.activeDocument; let c: any = null;
  try { c = doc.products.itemByProductType('CAMProductType'); } catch (e) {}
  if (!c) { app.userInterface.workspaces.itemById('CAMEnvironment').activate(); adsk.doEvents(); c = doc.products.itemByProductType('CAMProductType'); }
  return c;
}
function sp(o: any, n: string, e: string) {
  const p = o.parameters.itemByName(n);
  if (!p) { LOG.push(o.name + ': no param ' + n); return; }
  try { p.expression = e; } catch (ex: any) { LOG.push(o.name + '.' + n + ': ' + ex.message); }
}
