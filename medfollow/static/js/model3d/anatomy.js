/**
 * Repère anatomique d'un couple d'arcades (supérieure + inférieure), pour orienter les
 * vues Face / Dessus / Gauche / Droite sur la bouche plutôt que sur les axes du fichier.
 *
 * Les scanners n'exportent pas tous dans le même repère (ici Z vers le haut, ailleurs Y) :
 * on le déduit de la forme des arcades.
 * Les deux arcades sont toujours utilisées ensemble : un scan peut être incomplet.
 * - haut : axe de plus faible étendue des arcades (elles sont « plates »), orienté de
 *          l'arcade inférieure vers la supérieure ;
 * - avant : dans le plan d'occlusion, axe secondaire des couronnes, orienté vers le sommet
 *           de la courbe de l'arcade (incisives) — l'arrière est le bout ouvert.
 */

import * as THREE from '../three/three.module.min.js';

const MAX_SAMPLES = 20000;

/** Rôle d'un modèle d'après son nom de fichier. */
export function jawRole(name) {
  const n = (name || '').toLowerCase();
  if (/upper|maxil|sup[eé]r|\bsup\b|haut/.test(n)) return 'upper';
  if (/lower|mandib|inf[eé]r|\binf\b|\bbas\b/.test(n)) return 'lower';
  if (/total|bite|occlu|buccal|articul/.test(n)) return 'bite';
  return null;
}

function samplePoints(geometry, matrix) {
  const pos = geometry.getAttribute('position');
  const step = Math.max(1, Math.floor(pos.count / MAX_SAMPLES));
  const out = [];
  const v = new THREE.Vector3();
  for (let i = 0; i < pos.count; i += step) {
    v.fromBufferAttribute(pos, i);
    if (matrix) v.applyMatrix4(matrix);
    out.push(v.clone());
  }
  return out;
}


function centroid(points) {
  const c = new THREE.Vector3();
  points.forEach((p) => c.add(p));
  return c.divideScalar(points.length || 1);
}

/** Vecteurs propres (triés par valeur propre décroissante) d'une matrice 3×3 symétrique — Jacobi. */
function eigenSymmetric(m) {
  const a = m.map((r) => r.slice());
  const v = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  for (let sweep = 0; sweep < 50; sweep++) {
    let off = 0;
    for (let p = 0; p < 3; p++) for (let q = p + 1; q < 3; q++) off += a[p][q] * a[p][q];
    if (off < 1e-18) break;
    for (let p = 0; p < 3; p++) {
      for (let q = p + 1; q < 3; q++) {
        if (Math.abs(a[p][q]) < 1e-30) continue;
        const theta = (a[q][q] - a[p][p]) / (2 * a[p][q]);
        const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
        const c = 1 / Math.sqrt(t * t + 1), s = t * c;
        for (let k = 0; k < 3; k++) {
          const akp = a[k][p], akq = a[k][q];
          a[k][p] = c * akp - s * akq; a[k][q] = s * akp + c * akq;
        }
        for (let k = 0; k < 3; k++) {
          const apk = a[p][k], aqk = a[q][k];
          a[p][k] = c * apk - s * aqk; a[q][k] = s * apk + c * aqk;
        }
        for (let k = 0; k < 3; k++) {
          const vkp = v[k][p], vkq = v[k][q];
          v[k][p] = c * vkp - s * vkq; v[k][q] = s * vkp + c * vkq;
        }
      }
    }
  }
  return [0, 1, 2]
    .map((i) => ({ value: a[i][i], vector: new THREE.Vector3(v[0][i], v[1][i], v[2][i]).normalize() }))
    .sort((x, y) => y.value - x.value);
}

function principalAxes(points, c) {
  const m = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  const d = new THREE.Vector3();
  points.forEach((p) => {
    d.subVectors(p, c);
    const arr = [d.x, d.y, d.z];
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) m[i][j] += arr[i] * arr[j];
  });
  return eigenSymmetric(m);
}

/** Coefficient quadratique de la parabole des moindres carrés f ≈ a·s² + b·s + c. */
function fitParabolaA(proj) {
  // Équations normales : [Σs⁴ Σs³ Σs²; Σs³ Σs² Σs; Σs² Σs n]·[a b c] = [Σs²f Σsf Σf]
  let s1 = 0, s2 = 0, s3 = 0, s4 = 0, f0 = 0, f1 = 0, f2 = 0;
  proj.forEach(({ s, f }) => {
    const ss = s * s;
    s1 += s; s2 += ss; s3 += ss * s; s4 += ss * ss;
    f0 += f; f1 += s * f; f2 += ss * f;
  });
  const n = proj.length;
  const det3 = (m) => m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
    - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
    + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
  const M = [[s4, s3, s2], [s3, s2, s1], [s2, s1, n]];
  const D = det3(M);
  if (!D) return 0;
  return det3([[f2, s3, s2], [f1, s2, s1], [f0, s1, n]]) / D;   // règle de Cramer
}

/** Valeur au centile q (0–1) d'une liste de nombres. */
function percentile(values, q) {
  if (!values.length) return 0;
  const sorted = Float64Array.from(values).sort();
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(q * (sorted.length - 1))))];
}

/**
 * Couronnes dentaires : points des DEUX arcades proches du plan d'occlusion. Leur union dessine
 * l'arcade dentaire même si l'un des scans est incomplet, sans le palais (plus haut) ni la base
 * des modèles. Les centiles écartent les fragments isolés.
 */
function crownBand(upPts, lowPts, up) {
  const lowH = lowPts.map((p) => p.dot(up));
  const occlusal = (percentile(lowH, 0.99) + percentile(upPts.map((p) => p.dot(up)), 0.01)) / 2;
  const half = 0.5 * (percentile(lowH, 0.99) - percentile(lowH, 0.01));
  const all = upPts.concat(lowPts);
  const band = all.filter((p) => Math.abs(p.dot(up) - occlusal) < half);
  return { occlusal, crowns: band.length > 200 ? band : all };
}

/**
 * @param {THREE.BufferGeometry[]} uppers
 * @param {THREE.BufferGeometry[]} lowers
 * @returns {{up:THREE.Vector3, front:THREE.Vector3, left:THREE.Vector3}|null}
 */
export function computeMouthFrame(uppers, lowers) {
  if (!uppers.length || !lowers.length) return null;
  const lowPts = lowers.flatMap((g) => samplePoints(g));
  const upPts = uppers.flatMap((g) => samplePoints(g));
  if (lowPts.length < 50 || upPts.length < 50) return null;
  const cL = centroid(lowPts), cU = centroid(upPts);

  // Haut : axe de plus faible étendue des deux arcades réunies (une seule peut être partielle).
  const all = upPts.concat(lowPts);
  const up = principalAxes(all, centroid(all))[2].vector.clone();
  if (up.dot(new THREE.Vector3().subVectors(cU, cL)) < 0) up.negate();

  // Avant/arrière : dans le plan d'occlusion, axe secondaire des couronnes (le principal est la
  // largeur gauche-droite).
  const { crowns } = crownBand(upPts, lowPts, up);
  const flat = crowns.map((p) => p.clone().projectOnPlane(up));
  const c = centroid(flat);
  const axes = principalAxes(flat, c);
  const front = axes[1].vector.clone().projectOnPlane(up).normalize();
  const side = new THREE.Vector3().crossVectors(up, front).normalize();
  const proj = flat.map((p) => {
    const d = new THREE.Vector3().subVectors(p, c);
    return { f: d.dot(front), s: d.dot(side) };
  });
  // Parabole f = a·s² + b·s + c ajustée sur l'arcade : son sommet est du côté des incisives
  // (a < 0 → incisives vers +f). Robuste aux scans asymétriques (une branche plus longue),
  // contrairement à une comparaison des extrémités.
  if (fitParabolaA(proj) > 0) front.negate();
  const left = new THREE.Vector3().crossVectors(up, front).normalize();   // gauche du patient
  return { up, front, left };
}

/**
 * Charnière d'ouverture « en livre » : derrière les dernières molaires, au niveau du plan
 * d'occlusion. Les deux arcades pivotent en sens opposés autour de l'axe gauche-droite ; à 90°
 * chacune présente sa face occlusale de face (arcade sup. au-dessus, inf. en dessous).
 * @returns {{point:THREE.Vector3, axis:THREE.Vector3}|null}
 */
export function computeHinge(frame, uppers, lowers) {
  if (!frame) return null;
  const upPts = uppers.flatMap((g) => samplePoints(g));
  const lowPts = lowers.flatMap((g) => samplePoints(g));
  if (!upPts.length || !lowPts.length) return null;
  const { up, front, left } = frame;
  // Arrière des dents mesuré sur les couronnes des DEUX arcades (l'une peut être incomplète) ;
  // le palais, plus haut, est écarté : il déborde loin derrière les molaires.
  const { occlusal, crowns } = crownBand(upPts, lowPts, up);
  const fAll = crowns.map((p) => p.dot(front));
  const depth = percentile(fAll, 0.99) - percentile(fAll, 0.01);
  const fBack = percentile(crowns.map((p) => p.dot(front)), 0.01);
  const lMid = crowns.reduce((s, p) => s + p.dot(left), 0) / crowns.length;
  const point = new THREE.Vector3()
    .addScaledVector(front, fBack - depth * 0.03)
    .addScaledVector(up, occlusal)
    .addScaledVector(left, lMid);
  // Sens : une rotation positive amène l'avant vers le haut (arcade sup.) ; l'inf. tourne à l'inverse.
  const axis = left.clone();
  if (front.clone().applyAxisAngle(axis, Math.PI / 2).dot(up) < 0) axis.negate();
  return { point, axis };
}

/** Matrices des deux arcades pour une ouverture de `deg` degrés chacune. */
export function openMatrices(hinge, deg) {
  const make = (angle) => new THREE.Matrix4()
    .makeTranslation(hinge.point.x, hinge.point.y, hinge.point.z)
    .multiply(new THREE.Matrix4().makeRotationAxis(hinge.axis, angle))
    .multiply(new THREE.Matrix4().makeTranslation(-hinge.point.x, -hinge.point.y, -hinge.point.z));
  const a = THREE.MathUtils.degToRad(deg);
  return { upper: make(a), lower: make(-a) };
}
