// Instant Machinist machining-sim renderer. Deterministic: window.renderFrame(i) draws output frame i.
// Data (written by video.py) is served next to this page under ../data/.
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/RoomEnvironment.js';
import { LineSegments2 } from 'three/addons/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/addons/LineMaterial.js';

const DATA = '../data/';
const $ = (id) => document.getElementById(id);
const clamp01 = (x) => Math.min(1, Math.max(0, x));
const smooth = (x) => { x = clamp01(x); return x * x * x * (x * (x * 6 - 15) + 10); };
const lerp = (a, b, t) => a + (b - a) * t;

async function getJSON(u) { return (await fetch(DATA + u)).json(); }
async function getBin(u) { return (await fetch(DATA + u)).arrayBuffer(); }

const meta = await getJSON('meta.json');
const W = meta.width, H = meta.height;
document.documentElement.style.setProperty('--s', String(H / 1080));
const heightsQ = new Uint16Array(await getBin('heights.bin'));
const trail = new Float32Array(await getBin('trail.bin'));           // N x 7: a(3) b(3) cumLenEnd
const masks = meta.has_masks ? new Uint8Array(await getBin('masks.bin')) : null; // ny*nx: 1 gouge, 2 leftover
const nSeg = trail.length / 7;

// ---------------------------------------------------------------- renderer / scene
const canvas = $('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(meta.pixel_ratio || 1);
renderer.setSize(W, H, false);
renderer.setClearColor(0x000000, 0);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.95;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.75;

const g = meta.grid;
const nx = g.nx, ny = g.ny, cell = g.cell, celly = g.cell_y || g.cell;
const xmin = g.x0 - cell / 2, xmax = g.x0 + (nx - 0.5) * cell;
const ymin = g.y0 - celly / 2, ymax = g.y0 + (ny - 0.5) * celly;
const cx = (xmin + xmax) / 2, cy = (ymin + ymax) / 2;
const sx = xmax - xmin, sy = ymax - ymin;
const zbot = meta.zbot, ztop0 = meta.ztop0;
const [zq0, zq1] = meta.zq;
const zscale = (zq1 - zq0) / 65534;

// lights
const key = new THREE.DirectionalLight(0xfff4e8, 2.6);
key.position.set(cx - 0.9 * sx, cy - 1.3 * sy, ztop0 + 2.2 * sx);
key.target.position.set(cx, cy, zbot);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
const sc = key.shadow.camera; const ext = Math.max(sx, sy) * 0.95;
sc.left = -ext; sc.right = ext; sc.top = ext; sc.bottom = -ext; sc.near = 1; sc.far = 6 * sx;
key.shadow.bias = -0.0004; key.shadow.normalBias = 0.25; key.shadow.radius = 4;
scene.add(key, key.target);
const rim = new THREE.DirectionalLight(0x9cc8ff, 1.6);
rim.position.set(cx + 1.2 * sx, cy + 1.6 * sy, ztop0 + 0.8 * sx);
scene.add(rim);
const fill = new THREE.HemisphereLight(0xdfe8ff, 0x16181c, 0.35);
fill.up.set(0, 0, 1); fill.position.set(0, 0, 1);
scene.add(fill);

// procedural brushed-metal roughness texture (streaks along X)
function brushedTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 512;
  const ctx = c.getContext('2d');
  let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  ctx.fillStyle = 'rgb(215,215,215)'; ctx.fillRect(0, 0, 512, 512);
  for (let i = 0; i < 2600; i++) {
    const y = rnd() * 512, v = 175 + rnd() * 80, len = 60 + rnd() * 420, x = rnd() * 512;
    ctx.strokeStyle = `rgba(${v},${v},${v},${0.25 + rnd() * 0.4})`; ctx.lineWidth = 0.5 + rnd() * 1.2;
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + len, y + (rnd() - 0.5) * 2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x - 512, y); ctx.lineTo(x - 512 + len, y); ctx.stroke();
  }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8;
  return t;
}
const brushed = brushedTexture();

// ---------------------------------------------------------------- stock height field
const nV = nx * ny;
const pos = new Float32Array(nV * 3), uv = new Float32Array(nV * 2), col = new Float32Array(nV * 3);
for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
  const k = j * nx + i;
  pos[3 * k] = g.x0 + i * cell; pos[3 * k + 1] = g.y0 + j * celly; pos[3 * k + 2] = ztop0;
  uv[2 * k] = pos[3 * k] / 45; uv[2 * k + 1] = pos[3 * k + 1] / 45;
}
const idx = new Uint32Array((nx - 1) * (ny - 1) * 6);
{ let p = 0; for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
  const a = j * nx + i, b = a + 1, c = a + nx, d = c + 1;
  idx[p++] = a; idx[p++] = b; idx[p++] = d; idx[p++] = a; idx[p++] = d; idx[p++] = c; } }
const topGeo = new THREE.BufferGeometry();
topGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
topGeo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
topGeo.setAttribute('color', new THREE.BufferAttribute(col, 3).setUsage(THREE.DynamicDrawUsage));
topGeo.setIndex(new THREE.BufferAttribute(idx, 1));
topGeo.boundingSphere = new THREE.Sphere(new THREE.Vector3(cx, cy, (zbot + ztop0) / 2), Math.hypot(sx, sy, ztop0 - zbot));
const alu = new THREE.MeshPhysicalMaterial({
  color: 0xd2d6dc, metalness: 1.0, roughness: 0.34, roughnessMap: brushed, flatShading: true, vertexColors: true,
  clearcoat: 0.15, clearcoatRoughness: 0.25,
});
const topMesh = new THREE.Mesh(topGeo, alu);
topMesh.castShadow = topMesh.receiveShadow = true;
scene.add(topMesh);

// side walls (skirt): perimeter ring of the grid, top follows the boundary heights
const ring = [];
for (let i = 0; i < nx; i++) ring.push([i, 0]);
for (let j = 1; j < ny; j++) ring.push([nx - 1, j]);
for (let i = nx - 2; i >= 0; i--) ring.push([i, ny - 1]);
for (let j = ny - 2; j >= 1; j--) ring.push([0, j]);
const nR = ring.length;
const wallPos = new Float32Array((nR + 1) * 2 * 3), wallUv = new Float32Array((nR + 1) * 2 * 2);
const wallIdx = [];
function ringXY(r) {
  const [i, j] = ring[r % nR];
  // push perimeter vertices out to the true stock edge so walls are flush with the block outline
  let x = g.x0 + i * cell, y = g.y0 + j * celly;
  if (i === 0) x = xmin; if (i === nx - 1) x = xmax; if (j === 0) y = ymin; if (j === ny - 1) y = ymax;
  return [x, y];
}
let perim = 0;
for (let r = 0; r <= nR; r++) {
  const [x, y] = ringXY(r);
  if (r > 0) { const [px, py] = ringXY(r - 1); perim += Math.hypot(x - px, y - py); }
  wallPos.set([x, y, ztop0, x, y, zbot], 6 * r);
  wallUv.set([perim / 45, ztop0 / 45, perim / 45, zbot / 45], 4 * r);
  if (r < nR) { const a = 2 * r, b = 2 * r + 1, c = 2 * r + 2, d = 2 * r + 3; wallIdx.push(a, b, d, a, d, c); }
}
const wallGeo = new THREE.BufferGeometry();
wallGeo.setAttribute('position', new THREE.BufferAttribute(wallPos, 3).setUsage(THREE.DynamicDrawUsage));
wallGeo.setAttribute('uv', new THREE.BufferAttribute(wallUv, 2));
wallGeo.setIndex(wallIdx);
wallGeo.boundingSphere = topGeo.boundingSphere.clone();
const sawn = new THREE.MeshPhysicalMaterial({ color: 0xbfc4ca, metalness: 1.0, roughness: 0.46, roughnessMap: brushed, flatShading: true, side: THREE.DoubleSide });
const wallMesh = new THREE.Mesh(wallGeo, sawn);
wallMesh.castShadow = wallMesh.receiveShadow = true;
scene.add(wallMesh);
// snap perimeter vertices of the top mesh to the true edge too
for (let r = 0; r < nR; r++) { const [i, j] = ring[r]; const [x, y] = ringXY(r); const k = j * nx + i; pos[3 * k] = x; pos[3 * k + 1] = y; }

// ---------------------------------------------------------------- vise + table
const steelDark = new THREE.MeshPhysicalMaterial({ color: 0x1c1f24, metalness: 0.6, roughness: 0.55, envMapIntensity: 0.5 });
const steelMid = new THREE.MeshPhysicalMaterial({ color: 0x3a3f47, metalness: 0.8, roughness: 0.38, envMapIntensity: 0.6 });
const jawH = Math.min(12, (ztop0 - zbot) * 0.45);
const jawTop = zbot + jawH;
const baseT = 26;
function box(w, d, h, x, y, z, m) {
  const b = new THREE.Mesh(new THREE.BoxGeometry(w, d, h), m); b.position.set(x, y, z); b.castShadow = b.receiveShadow = true; scene.add(b); return b;
}
const floorZ = zbot - 7;
box(sx * 0.82, sy * 0.62, 7, cx, cy, zbot - 3.5, steelMid);                         // parallel under the stock
for (const s of [-1, 1]) {
  box(16, sy + 26, jawTop - floorZ, cx + s * (sx / 2 + 8 + 1.6), cy, (jawTop + floorZ) / 2, steelDark); // jaws
  box(1.6, sy + 26, jawTop - floorZ - 1, cx + s * (sx / 2 + 0.8), cy, (jawTop - 1 + floorZ) / 2, steelMid); // jaw plates
}
const ground = new THREE.Mesh(new THREE.PlaneGeometry(sx * 12, sx * 12), new THREE.ShadowMaterial({ opacity: 0.55 }));
ground.position.set(cx, cy, floorZ); ground.receiveShadow = true; scene.add(ground);

// ---------------------------------------------------------------- tools
const carbide = new THREE.MeshPhysicalMaterial({ color: 0xa9afb7, metalness: 1, roughness: 0.22, clearcoat: 0.3 });
const tinGold = new THREE.MeshPhysicalMaterial({ color: 0xe0b45a, metalness: 1, roughness: 0.25, clearcoat: 0.4 });
const altinDark = new THREE.MeshPhysicalMaterial({ color: 0x4a4458, metalness: 1, roughness: 0.28, clearcoat: 0.5 });
const shankMat = new THREE.MeshPhysicalMaterial({ color: 0xd8dce1, metalness: 1, roughness: 0.16 });
const holderMat = new THREE.MeshPhysicalMaterial({ color: 0x23262b, metalness: 0.9, roughness: 0.32 });
const nutMat = new THREE.MeshPhysicalMaterial({ color: 0x9aa1aa, metalness: 1, roughness: 0.2 });

function flutedGeometry(R, L, flutes, tipKind, tipAngle, helixDeg) {
  const na = 96, nz = Math.max(24, Math.round(L / 0.5));
  const twist = Math.tan(THREE.MathUtils.degToRad(helixDeg)) / R; // rad per mm
  const verts = [], ind = [];
  const tipH = tipKind === 'cone' ? R / Math.tan(THREE.MathUtils.degToRad(tipAngle / 2)) : tipKind === 'ball' ? R : 0;
  const profile = (u) => { // u in [0,1) within one flute pitch: edge, land, gully
    if (u < 0.18) return 1.0;
    if (u < 0.30) return lerp(1.0, 0.62, smooth((u - 0.18) / 0.12));
    if (u < 0.82) return 0.62 - 0.04 * Math.sin(Math.PI * (u - 0.30) / 0.52);
    return lerp(0.62, 1.0, smooth((u - 0.82) / 0.18));
  };
  for (let iz = 0; iz <= nz; iz++) {
    const z = (iz / nz) * L;
    let cap = R;
    if (tipKind === 'cone' && z < tipH) cap = R * z / tipH;
    if (tipKind === 'ball' && z < R) cap = Math.sqrt(Math.max(0, R * R - (R - z) * (R - z)));
    for (let ia = 0; ia <= na; ia++) {
      const th = (ia / na) * Math.PI * 2;
      const u = (((th - twist * z) * flutes / (2 * Math.PI)) % 1 + 1) % 1;
      const r = Math.min(R * profile(u), cap);
      verts.push(r * Math.cos(th), r * Math.sin(th), z);
    }
  }
  for (let iz = 0; iz < nz; iz++) for (let ia = 0; ia < na; ia++) {
    const a = iz * (na + 1) + ia, b = a + 1, c = a + na + 1, d = c + 1;
    ind.push(a, b, d, a, d, c);
  }
  if (tipKind === 'flat') { // bottom cap
    const c0 = verts.length / 3; verts.push(0, 0, 0);
    for (let ia = 0; ia < na; ia++) ind.push(c0, ia + 1, ia);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
  geo.setIndex(ind); geo.computeVertexNormals();
  return geo;
}

function cyl(r0, r1, h, z0, m, seg = 64) {
  const c = new THREE.Mesh(new THREE.CylinderGeometry(r1, r0, h, seg), m);
  c.rotation.x = Math.PI / 2; c.position.z = z0 + h / 2; c.castShadow = true; return c;
}

function buildTool(t) {
  const grp = new THREE.Group(), spin = new THREE.Group(); grp.add(spin);
  const D = t.diam, R = D / 2;
  let top;
  if (t.type === 'face_mill') {
    const bodyH = 40;
    const body = cyl(R * 0.92, R * 0.8, bodyH, 1.2, holderMat, 96); spin.add(body);
    const nIns = t.flutes || 5;
    for (let k = 0; k < nIns; k++) {
      const a = (k / nIns) * Math.PI * 2;
      const ins = new THREE.Mesh(new THREE.BoxGeometry(D * 0.18, D * 0.05, 7), altinDark);
      ins.position.set(Math.cos(a) * (R - D * 0.09), Math.sin(a) * (R - D * 0.09), 3.5);
      ins.rotation.z = a + Math.PI / 2; ins.castShadow = true; spin.add(ins);
      const gash = new THREE.Mesh(new THREE.BoxGeometry(D * 0.2, D * 0.12, 14), steelDark);
      gash.position.set(Math.cos(a + 0.35) * (R * 0.82), Math.sin(a + 0.35) * (R * 0.82), 7);
      gash.rotation.z = a + 0.35 + Math.PI / 2; spin.add(gash);
    }
    spin.add(cyl(R * 0.45, R * 0.45, 30, bodyH + 1.2, shankMat));
    top = bodyH + 31;
  } else {
    const isDrill = t.type === 'drill' || t.type === 'spot_drill';
    const fl = t.flute_length || (isDrill ? Math.max(4 * D, 20) : Math.max(2.5 * D, 12));
    const tipKind = isDrill ? 'cone' : t.type === 'ball' ? 'ball' : 'flat';
    const flutes = t.flutes || (isDrill ? 2 : 3);
    const helix = isDrill ? 30 : 38;
    const mat = t.type === 'drill' ? tinGold : t.type === 'spot_drill' ? altinDark : carbide;
    const body = new THREE.Mesh(flutedGeometry(R, fl, flutes, tipKind, t.tip_angle || 118, helix), mat);
    body.castShadow = true; spin.add(body);
    const shankR = Math.max(R, 3);
    const shankL = Math.max(14, D * 2.2);
    spin.add(cyl(R, shankR, Math.min(2, shankR - R + 0.6), fl, shankMat));
    spin.add(cyl(shankR, shankR, shankL, fl, shankMat));
    top = fl + shankL;
  }
  // collet nut + holder (non-spinning visually identical; keep in group)
  const nutR = Math.max(R * 1.6, 12);
  grp.add(cyl(nutR, nutR * 0.92, 14, top, nutMat, 64));
  grp.add(cyl(nutR * 0.95, nutR * 1.35, 30, top + 14, holderMat, 64));
  grp.add(cyl(nutR * 1.35, nutR * 2.6, 30, top + 44, holderMat, 64));
  grp.add(cyl(nutR * 2.6, nutR * 2.6, 200, top + 74, holderMat, 64));
  grp.userData.spin = spin;
  return grp;
}
const tools = {};
for (const [id, t] of Object.entries(meta.tools)) { const m = buildTool(t); m.visible = false; scene.add(m); tools[id] = m; }

// ---------------------------------------------------------------- toolpath trail (glow + core)
function mkLine(width, opacity) {
  const m = new LineMaterial({ linewidth: width, vertexColors: true, transparent: true, opacity, depthWrite: false,
    blending: THREE.AdditiveBlending, worldUnits: false });
  m.resolution.set(W, H);
  const l = new LineSegments2(new LineSegmentsGeometry(), m);
  l.frustumCulled = false; l.renderOrder = 5; scene.add(l); return l;
}
const glow = mkLine(9 * H / 1080, 0.35), core = mkLine(2.4 * H / 1080, 0.95);
const trailColor = new THREE.Color(meta.trail_color || '#39c6ff');
function lowerBound(arr, stride, off, n, v) { let lo = 0, hi = n; while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m * stride + off] < v) lo = m + 1; else hi = m; } return lo; }
function setTrail(segEnd, hs, head, segMin = 0) {
  // feed segments [s0, segEnd) completed; plus the in-progress move from hs to the tool tip
  const base = segEnd > 0 ? trail[(segEnd - 1) * 7 + 6] : 0;
  const lenHead = base + (hs ? Math.hypot(head[0] - hs[0], head[1] - hs[1], head[2] - hs[2]) : 0);
  const L = meta.trail_len_mm;
  const s0 = Math.max(segMin, lowerBound(trail, 7, 6, segEnd, lenHead - L));
  const n = segEnd - s0 + (hs ? 1 : 0);
  if (n <= 0) { glow.visible = core.visible = false; return; }
  const P = new Float32Array(n * 6), C = new Float32Array(n * 6);
  let p = 0;
  const lift = 0.15;
  const put = (ax, ay, az, bx, by, bz, la, lb) => {
    P.set([ax, ay, az + lift, bx, by, bz + lift], p * 6);
    const fa = Math.pow(clamp01(1 - (lenHead - la) / L), 1.6), fb = Math.pow(clamp01(1 - (lenHead - lb) / L), 1.6);
    C.set([trailColor.r * fa, trailColor.g * fa, trailColor.b * fa, trailColor.r * fb, trailColor.g * fb, trailColor.b * fb], p * 6);
    p++;
  };
  for (let s = s0; s < segEnd; s++) {
    const o = s * 7, le = trail[o + 6];
    const ls = le - Math.hypot(trail[o + 3] - trail[o], trail[o + 4] - trail[o + 1], trail[o + 5] - trail[o + 2]);
    put(trail[o], trail[o + 1], trail[o + 2], trail[o + 3], trail[o + 4], trail[o + 5], ls, le);
  }
  if (hs) put(hs[0], hs[1], hs[2], head[0], head[1], head[2], base, lenHead);
  for (const l of [glow, core]) { l.geometry.dispose(); l.geometry = new LineSegmentsGeometry(); l.geometry.setPositions(P); l.geometry.setColors(C); l.visible = true; }
}

// ---------------------------------------------------------------- chips (deterministic particles)
const CHIP_HIST = 6, CHIP_PER = 7, nChips = CHIP_HIST * CHIP_PER;
const chipGeo = new THREE.BoxGeometry(1.4, 0.55, 0.18);
const chipMat = new THREE.MeshPhysicalMaterial({ color: 0xe8ecf0, metalness: 1, roughness: 0.18 });
const chips = new THREE.InstancedMesh(chipGeo, chipMat, nChips);
chips.instanceMatrix.setUsage(THREE.DynamicDrawUsage); chips.castShadow = false; chips.frustumCulled = false;
scene.add(chips);
const hash = (a, b) => { let h = (a * 374761393 + b * 668265263) | 0; h = (h ^ (h >>> 13)) * 1274126177; h ^= h >>> 16; return (h >>> 0) / 4294967296; };
const _m = new THREE.Matrix4(), _q = new THREE.Quaternion(), _e = new THREE.Euler(), _v = new THREE.Vector3(), _s = new THREE.Vector3();
function setChips(i) {
  let n = 0;
  const fps = meta.fps;
  for (let k = 0; k < CHIP_HIST; k++) {
    const b = i - k;
    if (b < 0 || !F.cut[b]) continue;
    const tb = meta.tools[String(F.tool[b])]; const R = (tb ? tb.diam : 6) / 2;
    const p = F.pos[b];
    for (let c = 0; c < CHIP_PER; c++) {
      const r1 = hash(b, c * 7 + 1), r2 = hash(b, c * 7 + 2), r3 = hash(b, c * 7 + 3), r4 = hash(b, c * 7 + 4);
      const age = (k + r4) / fps;
      const a = r1 * Math.PI * 2;
      const sp = 70 + 150 * r2, up = 50 + 140 * r3;
      const tx = -Math.sin(a), ty = Math.cos(a);           // tangential throw (spindle CW from above)
      const x = p[0] + Math.cos(a) * R + (tx * 0.8 + Math.cos(a) * 0.4) * sp * age;
      const y = p[1] + Math.sin(a) * R + (ty * 0.8 + Math.sin(a) * 0.4) * sp * age;
      const z = Math.max(p[2] + 0.5 + up * age - 0.5 * 3200 * age * age, zbot - 7);
      _e.set(r1 * 9 + age * 40 * r2, r2 * 9 + age * 30, r3 * 9 + age * 50 * r1);
      const sc = 0.6 + 0.9 * r3;
      _m.compose(_v.set(x, y, z), _q.setFromEuler(_e), _s.set(sc, sc, sc));
      chips.setMatrixAt(n++, _m);
    }
  }
  chips.count = n; chips.instanceMatrix.needsUpdate = true; chips.visible = n > 0;
}

// ---------------------------------------------------------------- camera
const camera = new THREE.PerspectiveCamera(meta.fov || 28, W / H, 5, 5000);
camera.up.set(0, 0, 1);
const target = new THREE.Vector3(cx, cy, lerp(zbot, ztop0, 0.55));
const diag = Math.hypot(sx, sy);
function placeCamera(u, b = 0) {
  const s = smooth(u);
  target.z = lerp(zbot, ztop0, 0.55) - smooth(b) * (ztop0 - zbot) * 0.9;
  const az = THREE.MathUtils.degToRad(lerp(-122, -64, s));
  const el = THREE.MathUtils.degToRad(lerp(33, 46, s));
  const dist = diag * lerp(2.6, 2.55, s) * (meta.cam_zoom || 1);
  camera.position.set(target.x + dist * Math.cos(el) * Math.cos(az), target.y + dist * Math.cos(el) * Math.sin(az), target.z + dist * Math.sin(el));
  camera.lookAt(target);
}

// ---------------------------------------------------------------- per-frame update
const F = meta.frames;
const nFrames = F.sim.length;
let lastSim = -1, lastMaskAmt = -1;
function setHeights(si, maskAmt) {
  if (si === lastSim && maskAmt === lastMaskAmt) return;
  lastSim = si; lastMaskAmt = maskAmt;
  const off = si * nV;
  for (let k = 0; k < nV; k++) {
    const q = heightsQ[off + k];
    const dead = q === 65535;
    const z = dead ? zbot : zq0 + q * zscale;
    pos[3 * k + 2] = z;
    let r, gg, b;
    if (dead) { r = gg = b = 0.12; }
    else if (z < ztop0 - 0.05) { r = gg = b = 0.94; }         // freshly machined: brighter
    else { r = 0.76; gg = 0.775; b = 0.80; }                    // mill-finish stock
    if (masks && maskAmt > 0 && masks[k]) {
      const m = masks[k] === 1 ? [1.0, 0.18, 0.15] : [1.0, 0.65, 0.1];
      r = lerp(r, m[0], maskAmt); gg = lerp(gg, m[1], maskAmt); b = lerp(b, m[2], maskAmt);
    }
    col[3 * k] = r; col[3 * k + 1] = gg; col[3 * k + 2] = b;
  }
  topGeo.attributes.position.needsUpdate = true;
  topGeo.attributes.color.needsUpdate = true;
  for (let r = 0; r <= nR; r++) {
    const [i, j] = ring[r % nR];
    const q = heightsQ[off + j * nx + i];
    wallPos[6 * r + 2] = q === 65535 ? zbot : zq0 + q * zscale;
  }
  wallGeo.attributes.position.needsUpdate = true;
}

const fmtClock = (t) => { t = Math.max(0, Math.round(t)); const m = Math.floor(t / 60), s = t % 60; return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`; };
$('badgetext').textContent = meta.badge || '';
if (!meta.badge) $('badge').style.display = 'none';

window.nFrames = nFrames;
window.renderFrame = async (i) => {
  i = Math.max(0, Math.min(nFrames - 1, i));
  const si = F.sim[i], tid = String(F.tool[i]), p = F.pos[i];
  const badge = F.badge[i];
  setHeights(si, Math.round(badge * 20) / 20);
  for (const [id, m] of Object.entries(tools)) m.visible = false;
  const tool = tools[tid];
  const toolLift = F.lift[i];
  if (tool && F.tool_a[i] > 0.001) {
    tool.visible = true;
    tool.position.set(p[0], p[1], p[2] + toolLift);
    tool.userData.spin.rotation.z = -i * 0.55;
  }
  setTrail(F.seg[i], F.head[i], p, F.seg0 ? F.seg0[i] : 0);
  const trailFade = 1 - smooth(badge * 1.4);
  glow.material.opacity = 0.35 * trailFade; core.material.opacity = 0.95 * trailFade;
  setChips(i);
  placeCamera(F.cam[i], badge);
  // HUD
  const t = meta.tools[tid];
  $('toolname').querySelector('.t').textContent = `T${tid}`;
  $('tooldesc').textContent = t ? t.label : '';
  const op = F.op[i];
  $('oplabel').textContent = `Operation ${op + 1} of ${meta.ops.length} · ${meta.ops[op] ? meta.ops[op].label : ''}`;
  $('oppct').textContent = `${Math.round(F.opp[i] * 100)}%`;
  $('opbar').style.width = `${(F.opp[i] * 100).toFixed(2)}%`;
  $('clock').innerHTML = `${fmtClock(F.t[i])}`;
  if (badge > 0.001) {
    $('toolname').querySelector('.t').textContent = '';
    $('tooldesc').textContent = 'Program complete';
    $('oplabel').textContent = `${meta.ops.length} operations · ${Object.keys(meta.tools).length} tools`;
  }
  $('progbar').style.width = `${(F.prog[i] * 100).toFixed(2)}%`;
  $('progpct').textContent = `${Math.round(F.prog[i] * 100)}%`;
  const b = $('badge');
  b.style.opacity = String(smooth(badge));
  b.style.transform = `translate(-50%, ${(1 - smooth(badge)) * 24 * H / 1080}px) scale(${lerp(0.94, 1, smooth(badge))})`;
  $('fade').style.opacity = String(F.fade[i]);
  for (const id of ['bl', 'br']) $(id).style.opacity = String(1 - smooth(badge));
  renderer.render(scene, camera);
  await new Promise((r) => requestAnimationFrame(() => r()));
  return i;
};

await document.fonts.ready;
await window.renderFrame(0);
window.sceneReady = true;
