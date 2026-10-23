/**
 * Onglet « Modèle 3D » de la fiche patient : visionneuse de modèles .ply.
 *
 * - frise chronologique en haut (la même que l'odontogramme, `odonto/timeline.js`) :
 *   un cran par date de radio, la dernière date est affichée par défaut
 * - plusieurs modèles le même jour (ex. arcade sup. + inf.) sont rendus ensemble
 *   dans la même scène, chacun masquable
 * - rendu three.js (vendu dans /static/js/three/), à la demande (pas de boucle permanente)
 * - import d'un ou plusieurs .ply avec la date de la radio (XHR pour la progression)
 */

import * as THREE from '../three/three.module.min.js';
import { TrackballControls } from '../three/TrackballControls.js';
import { PLYLoader } from '../three/PLYLoader.js';
import { request, toast } from '../odonto/api.js';
import { esc, formatDate } from '../odonto/constants.js';
import { confirmDialog, openModal } from '../odonto/popups.js';
import { createTimeline } from '../odonto/timeline.js';
import { computeHinge, computeMouthFrame, jawRole, openMatrices } from './anatomy.js';

const BASE_COLOR = 0xf1e9da;   // ivoire, pour les scans sans couleurs
const BG_COLOR = 0xf6f9fd;
const MOUTH_OPEN_DEG = 90;      // ouverture complète : chaque arcade montre sa face occlusale
const MOUTH_ANIM_MS = 700;

const VIEWS = [
  { key: 'front', label: 'Face', dir: [0, 0, 1], up: [0, 1, 0] },
  { key: 'top', label: 'Dessus', dir: [0, 1, 0], up: [0, 0, -1] },
  { key: 'bottom', label: 'Dessous', dir: [0, -1, 0], up: [0, 0, 1] },
  { key: 'left', label: 'Gauche', dir: [-1, 0, 0], up: [0, 1, 0] },
  { key: 'right', label: 'Droite', dir: [1, 0, 0], up: [0, 1, 0] },
];

const ICON = {
  upload: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>',
  eye: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
  eyeOff: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>',
  download: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
  trash: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>',
  palette: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 22a10 10 0 1 1 10-10c0 2.8-2.2 4-4 4h-2a2 2 0 0 0-1.5 3.3A2 2 0 0 1 12 22z"/><circle cx="7.5" cy="10.5" r="1.2"/><circle cx="12" cy="7" r="1.2"/><circle cx="16.5" cy="10.5" r="1.2"/></svg>',
  mouth: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8c3-3 15-3 18 0"/><path d="M5 9.5c0 2 3 3 7 3s7-1 7-3"/><path d="M3 16c3 3 15 3 18 0"/><path d="M5 14.5c0-2 3-3 7-3s7 1 7 3"/></svg>',
  cube: '<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M12 2l9 5v10l-9 5-9-5V7z"/><path d="M12 22V12M21 7l-9 5-9-5"/></svg>',
};

const DROP_HINT = 'Cliquez ou déposez ici les fichiers du scanner (.ply et images .png), ou le dossier entier';
const IMAGE_RE = /\.(png|jpe?g)$/i;

/** Nom de l'image de couleurs déclarée dans l'en-tête PLY (« comment TextureFile … »), ou null. */
async function plyTextureRef(file) {
  const header = (await file.slice(0, 64 * 1024).text()).split('end_header')[0];
  const m = /^comment\s+TextureFile\s+(.+?)\s*$/m.exec(header);
  return m ? m[1].split(/[\\/]/).pop() : null;
}

/**
 * Associe chaque .ply à son image de couleurs parmi les fichiers choisis :
 * d'abord le nom déclaré dans l'en-tête, sinon le même nom de base (UpperJaw.ply ↔ UpperJaw.png).
 */
async function pairFiles(files) {
  const plys = files.filter((f) => /\.ply$/i.test(f.name));
  const images = files.filter((f) => IMAGE_RE.test(f.name));
  const bad = files.filter((f) => !plys.includes(f) && !images.includes(f));
  const used = new Set();
  const base = (name) => name.replace(/\.[^.]+$/, '').toLowerCase();
  const items = [];
  for (const ply of plys) {
    const ref = await plyTextureRef(ply).catch(() => null);
    const free = images.filter((img) => !used.has(img));
    const image = (ref && free.find((img) => img.name.toLowerCase() === ref.toLowerCase()))
      || free.find((img) => base(img.name) === base(ply.name)) || null;
    if (image) used.add(image);
    items.push({ ply, ref, image, sharedWith: null });
  }
  // Doublons (« LowerJaw.ply » et « LowerJaw (1).ply ») : l'image n'est envoyée qu'une fois,
  // le serveur la recopie pour le second modèle.
  items.forEach((it) => {
    if (it.image || !it.ref) return;
    const other = items.find((o) => o.image && o.image.name.toLowerCase() === it.ref.toLowerCase());
    if (other) it.sharedWith = other.image;
  });
  return { items, stray: images.filter((img) => !used.has(img)), bad };
}

/** Fichiers d'un glisser-déposer, dossiers compris (parcours récursif). */
async function droppedFiles(dataTransfer) {
  const entries = [...(dataTransfer.items || [])].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (!entries.length) return [...dataTransfer.files];
  const out = [];
  const walk = async (entry) => {
    if (entry.isFile) {
      out.push(await new Promise((res, rej) => entry.file(res, rej)));
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      for (;;) {
        const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        if (!batch.length) break;
        for (const e of batch) await walk(e);
      }
    }
  };
  for (const e of entries) await walk(e);
  return out;
}

function todayIso() {
  const d = new Date();
  const p = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function longDate(iso) {
  const d = new Date(iso + 'T00:00:00');
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' });
}

function formatSize(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} Mo`;
  return `${Math.max(1, Math.round(bytes / 1024))} Ko`;
}

function getCookie(name) {
  const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
  return m ? decodeURIComponent(m[1]) : '';
}

/** POST multipart avec progression d'envoi (fetch ne la fournit pas). */
function uploadFile(url, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.setRequestHeader('X-CSRF-Token', getCookie('csrf_token'));
    xhr.setRequestHeader('X-Requested-With', 'fetch');
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch (e) { data = null; }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error((data && (data.error || data.detail)) || `Erreur HTTP ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error('Connexion au serveur impossible'));
    xhr.send(formData);
  });
}

// ============================================================================
// Scène three.js
// ============================================================================

function createScene(wrap) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  wrap.prepend(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(BG_COLOR);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 10000);
  scene.add(camera);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x7a8ba3, 1.6));
  // Lumière « frontale » attachée à la caméra : le modèle reste éclairé sous tous les angles.
  const head = new THREE.DirectionalLight(0xffffff, 2.2);
  head.position.set(0.4, 0.6, 1);
  camera.add(head);

  // Trackball : rotation libre dans tous les sens (pas de blocage aux pôles comme avec
  // OrbitControls), avec inertie. La molette est gérée ici (zoom vers le curseur).
  const controls = new TrackballControls(camera, renderer.domElement);
  controls.rotateSpeed = 3.2;
  controls.panSpeed = 0.9;
  controls.zoomSpeed = 1.2;
  controls.staticMoving = false;
  controls.dynamicDampingFactor = 0.16;
  controls.keys = [null, null, null];   // pas de raccourcis A/S/D écoutés sur toute la page

  const group = new THREE.Group();
  scene.add(group);

  let pending = false, changed = false, interacting = false, anim = null;
  let fit = { center: new THREE.Vector3(), radius: 50, points: null };
  controls.addEventListener('change', () => { changed = true; });
  controls.addEventListener('start', () => { interacting = true; requestRender(); });
  controls.addEventListener('end', () => { interacting = false; requestRender(); });

  function tick(now) {
    pending = false;
    changed = false;
    if (anim) stepAnimation(now);
    controls.update();
    renderer.render(scene, camera);
    if (changed || interacting || anim) requestRender();
  }
  function requestRender() {
    if (!pending) { pending = true; requestAnimationFrame(tick); }
  }

  function resize() {
    const w = wrap.clientWidth, h = wrap.clientHeight;
    if (!w || !h) return;   // onglet masqué
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    controls.handleResize();
    requestRender();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(wrap);

  // --- Animations de caméra (vues, recentrage, ouverture de la bouche) ------

  function setPose(pose) {
    camera.position.copy(pose.position);
    camera.up.copy(pose.up);
    controls.target.copy(pose.target);
    camera.lookAt(pose.target);
  }

  function animateTo(pose, duration = 450) {
    if (!duration) { anim = null; setPose(pose); requestRender(); return; }
    anim = {
      t0: performance.now(), duration, to: pose,
      from: { position: camera.position.clone(), target: controls.target.clone(), up: camera.up.clone() },
    };
    requestRender();
  }

  function stepAnimation(now) {
    const k = Math.min(1, (now - anim.t0) / anim.duration);
    const e = k < 0.5 ? 4 * k * k * k : 1 - ((-2 * k + 2) ** 3) / 2;   // ease-in-out cubique
    const { from, to } = anim;
    setPose({
      position: from.position.clone().lerp(to.position, e),
      target: from.target.clone().lerp(to.target, e),
      up: from.up.clone().lerp(to.up, e).normalize(),
    });
    if (k >= 1) anim = null;
  }

  // --- Vues ------------------------------------------------------------------

  // Repère anatomique (arcades sup. + inf. reconnues) : les vues suivent la bouche, pas les axes
  // du fichier — chaque scanner exporte dans son propre repère.
  let frame = null;
  function viewAxes(view) {
    if (!frame) return { dir: new THREE.Vector3(...view.dir).normalize(), up: new THREE.Vector3(...view.up) };
    const { up, front, left } = frame;
    switch (view.key) {
      case 'top': return { dir: up.clone(), up: front.clone() };
      case 'bottom': return { dir: up.clone().negate(), up: front.clone() };
      case 'left': return { dir: left.clone(), up: up.clone() };
      case 'right': return { dir: left.clone().negate(), up: up.clone() };
      default: return { dir: front.clone(), up: up.clone() };
    }
  }

  /** Pose de caméra qui cadre les sommets de référence, vue depuis `dir` (vers le modèle). */
  function framingPose(dir, upV) {
    const vHalf = THREE.MathUtils.degToRad(camera.fov / 2);
    const hHalf = Math.atan(Math.tan(vHalf) * camera.aspect);
    const right = new THREE.Vector3().crossVectors(upV, dir).normalize();
    const trueUp = new THREE.Vector3().crossVectors(dir, right);
    let halfW = fit.radius, halfH = fit.radius, halfD = fit.radius;
    let center = fit.center.clone();
    if (fit.points && fit.points.length) {
      // Étendue réelle des sommets dans le repère de la vue : cadrage serré même quand le scan
      // est tourné dans son fichier (une boîte alignée sur les axes serait trop large).
      const ext = [right, trueUp, dir].map((axis) => {
        let lo = Infinity, hi = -Infinity;
        fit.points.forEach((p) => { const d = p.dot(axis); if (d < lo) lo = d; if (d > hi) hi = d; });
        return { mid: (lo + hi) / 2, half: (hi - lo) / 2 };
      });
      [halfW, halfH, halfD] = ext.map((e) => e.half);
      center = new THREE.Vector3().addScaledVector(right, ext[0].mid)
        .addScaledVector(trueUp, ext[1].mid).addScaledVector(dir, ext[2].mid);
    }
    const dist = halfD + Math.max(halfW / Math.tan(hHalf), halfH / Math.tan(vHalf)) * 1.2;
    return { position: center.clone().addScaledVector(dir, dist), target: center, up: trueUp };
  }

  function setView(view, duration = 450) {
    const { dir, up } = viewAxes(view);
    animateTo(framingPose(dir, up), duration);
  }

  /** Nouveaux sommets de référence (ex. bouche ouverte) ; view : vue à prendre, sinon direction actuelle. */
  function refit(points, { view = null, duration = 450 } = {}) {
    if (points && points.length) fit.points = points;
    if (view) { setView(view, duration); return; }
    const dir = camera.position.clone().sub(controls.target).normalize();
    animateTo(framingPose(dir, camera.up.clone()), duration);
  }

  // --- Souris / tactile --------------------------------------------------------

  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  function pointerNdc(e) {
    const r = renderer.domElement.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    return ndc;
  }

  // Zoom molette VERS LE CURSEUR : le point visé reste sous la souris.
  function onWheel(e) {
    if (!e.target.closest('canvas')) return;
    e.preventDefault();
    e.stopPropagation();   // le zoom de TrackballControls (vers le centre) n'est pas utilisé
    const px = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * 400 : e.deltaY;
    let k = Math.exp(Math.max(-60, Math.min(60, px)) * 0.0022);
    const dist = camera.position.distanceTo(controls.target);
    k = Math.min(Math.max(k, controls.minDistance / dist), controls.maxDistance / dist);
    raycaster.setFromCamera(pointerNdc(e), camera);
    const viewDir = controls.target.clone().sub(camera.position).normalize();
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(viewDir, controls.target);
    const p = raycaster.ray.intersectPlane(plane, new THREE.Vector3()) || controls.target.clone();
    anim = null;
    camera.position.sub(p).multiplyScalar(k).add(p);
    controls.target.sub(p).multiplyScalar(k).add(p);
    requestRender();
  }

  // Double-clic sur le modèle : ce point devient le centre de rotation (et on s'en approche).
  function onDblClick(e) {
    raycaster.setFromCamera(pointerNdc(e), camera);
    const hit = raycaster.intersectObjects(group.children.filter((o) => o.visible), false)[0];
    if (!hit) { refit(null); return; }   // double-clic dans le vide : recadrer
    const offset = camera.position.clone().sub(controls.target).multiplyScalar(0.7);
    const minLen = controls.minDistance * 1.5;
    if (offset.length() < minLen) offset.setLength(minLen);
    animateTo({ position: hit.point.clone().add(offset), target: hit.point.clone(), up: camera.up.clone() }, 400);
  }

  // Maj/Ctrl + glisser = déplacer (en plus du clic droit) ; position du canevas rafraîchie à
  // chaque clic (la page a pu défiler ou la liste des modèles changer de hauteur).
  function onPointerDownCapture(e) {
    controls.handleResize();
    controls.mouseButtons.LEFT = (e.shiftKey || e.ctrlKey || e.metaKey) ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
    anim = null;
  }

  wrap.addEventListener('wheel', onWheel, { capture: true, passive: false });
  wrap.addEventListener('pointerdown', onPointerDownCapture, { capture: true });
  renderer.domElement.addEventListener('dblclick', onDblClick);

  /**
   * Remplace le contenu de la scène par ces objets et recadre la caméra.
   * fitPoints : sommets de référence du cadrage, sinon la boîte des objets.
   */
  function show(objects, { fitPoints = null, frame: mouthFrame = null, keepView = false } = {}) {
    frame = mouthFrame;
    while (group.children.length) {
      const old = group.children[0];
      group.remove(old);
      old.material.dispose();   // la géométrie est en cache, elle est réutilisée
    }
    objects.forEach((o) => group.add(o));
    const box = fitPoints && fitPoints.length
      ? new THREE.Box3().setFromPoints(fitPoints)
      : new THREE.Box3().setFromObject(group);
    if (!box.isEmpty()) {
      const sphere = box.getBoundingSphere(new THREE.Sphere());
      fit = { center: sphere.center, radius: sphere.radius || 1, points: fitPoints };
      camera.near = fit.radius / 200;
      camera.far = fit.radius * 200;
      camera.updateProjectionMatrix();
      controls.minDistance = fit.radius * 0.15;
      controls.maxDistance = fit.radius * 25;
    }
    // Mêmes modèles qu'avant (couleurs, filaire…) : on garde l'angle de vue du praticien.
    if (keepView) requestRender(); else setView(VIEWS[0], 0);
  }

  function snapshot() {
    renderer.render(scene, camera);
    return renderer.domElement.toDataURL('image/png');
  }

  return {
    show, setView, refit, resize, requestRender, snapshot,
    destroy() {
      ro.disconnect();
      wrap.removeEventListener('wheel', onWheel, { capture: true });
      wrap.removeEventListener('pointerdown', onPointerDownCapture, { capture: true });
      renderer.domElement.removeEventListener('dblclick', onDblClick);
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}

/** ~4000 sommets d'un objet, dans le repère de la scène (matrice de l'objet appliquée). */
function samplePositions(object, max = 4000) {
  const pos = object.geometry.getAttribute('position');
  const step = Math.max(1, Math.floor(pos.count / max));
  if (object.matrixAutoUpdate) object.updateMatrix();
  const out = [];
  for (let i = 0; i < pos.count; i += step) {
    out.push(new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(object.matrix));
  }
  return out;
}

/**
 * Objet three.js (maillage ou nuage de points) pour une géométrie PLY.
 * Couleurs : texture (image + UV) en priorité, sinon couleurs par sommet.
 */
function buildObject({ geometry, texture }, { useColors, wireframe }) {
  if (texture && useColors && geometry.getAttribute('uv') && !geometry.userData.pointCloud) {
    if (!geometry.getAttribute('normal')) geometry.computeVertexNormals();
    return new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      map: texture, color: 0xffffff, roughness: 0.6, metalness: 0, side: THREE.DoubleSide, wireframe,
    }));
  }
  const hasColors = !!geometry.getAttribute('color');
  const colored = hasColors && useColors;
  if (geometry.userData.pointCloud) {
    // Pas de faces : nuage de points.
    geometry.computeBoundingSphere();
    const size = Math.max(geometry.boundingSphere.radius / 150, 0.05);
    return new THREE.Points(geometry, new THREE.PointsMaterial({
      size, vertexColors: colored, color: colored ? 0xffffff : 0x6f6552,
    }));
  }
  if (!geometry.getAttribute('normal')) geometry.computeVertexNormals();
  return new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
    color: colored ? 0xffffff : BASE_COLOR, vertexColors: colored,
    roughness: 0.55, metalness: 0, side: THREE.DoubleSide, wireframe,
  }));
}

// ============================================================================
// Onglet
// ============================================================================

/**
 * @param {HTMLElement} root
 * @param {{patientId:number}} opts
 */
export function mountModel3D(root, opts) {
  const base = `/modele-3d/${opts.patientId}`;
  const state = {
    models: [],
    viewingDate: null,   // null = dernière date
    hidden: new Set(),   // id des modèles masqués
    useColors: true,
    wireframe: false,
    loadToken: 0,
    frameKey: null,      // arcades ayant servi au calcul du repère
    mouthFrame: null,    // repère de la bouche (anatomy.js), null si arcades non reconnues
    shownKey: null,
    objects: [],         // objets affichés (userData.role : upper | lower | bite | null)
    hinge: null,         // charnière d'ouverture (anatomy.js), null si arcades non reconnues
    mouthAngle: 0,       // ouverture actuelle de chaque arcade, en degrés
    mouthAnim: 0,
    defaulted: new Set(),   // modèles dont la visibilité par défaut a déjà été appliquée
  };
  const geometries = new Map();   // id -> Promise<BufferGeometry>
  const textures = new Map();     // texture_url -> Promise<Texture|null>
  const loader = new PLYLoader();
  const fileLoader = new THREE.FileLoader().setResponseType('arraybuffer');
  const textureLoader = new THREE.TextureLoader();

  root.classList.add('m3d-root');
  root.innerHTML = `
    <div class="odonto-panel m3d-toolbar">
      <div class="m3d-heading">
        <h3>Modèle 3D</h3>
        <span class="odonto-muted odonto-small" data-role="summary">Chargement…</span>
      </div>
      <button type="button" class="odo-btn odo-btn-primary" data-act="upload">${ICON.upload}Importer des fichiers</button>
    </div>
    <div class="odonto-panel" data-role="timeline" hidden></div>
    <div class="odonto-panel m3d-empty" data-role="empty" hidden>
      <div class="m3d-empty-icon">${ICON.cube}</div>
      <p class="odonto-strong">Aucun modèle 3D pour ce patient</p>
      <p class="odonto-muted odonto-small">Importez les fichiers exportés par votre scanner (.ply et images .png) : les couleurs sont associées automatiquement.</p>
      <button type="button" class="odo-btn odo-btn-soft" data-act="upload">${ICON.upload}Importer un modèle</button>
    </div>
    <div class="odonto-panel m3d-stage" data-role="stage" hidden>
      <div class="m3d-stage-head">
        <div>
          <div class="m3d-stage-title" data-role="stage-title"></div>
          <div class="m3d-chips" data-role="chips"></div>
        </div>
        <div class="m3d-display">
          <label class="m3d-check" data-role="colors-opt"><input type="checkbox" data-act="colors" checked> Couleurs du scan</label>
          <label class="m3d-check"><input type="checkbox" data-act="wireframe"> Filaire</label>
        </div>
      </div>
      <div class="m3d-canvas-wrap" data-role="canvas">
        <div class="m3d-views">
          ${VIEWS.map((v) => `<button type="button" class="m3d-view-btn" data-view="${v.key}">${v.label}</button>`).join('')}
          <span class="m3d-views-sep"></span>
          <button type="button" class="m3d-view-btn" data-act="snapshot" title="Enregistrer l'image affichée (PNG)">Capture</button>
        </div>
        <div class="m3d-overlay" data-role="overlay" hidden><div class="m3d-spinner"></div><span data-role="overlay-text"></span></div>
        <div class="m3d-note" data-role="all-hidden" hidden>Tous les modèles de cette date sont masqués : cliquez sur l'œil pour en afficher un.</div>
        <div class="m3d-mouth" data-role="mouth" hidden>
          <button type="button" class="m3d-mouth-btn" data-act="mouth" data-role="mouth-btn"></button>
          <input type="range" min="0" max="${MOUTH_OPEN_DEG}" step="1" value="0" data-act="mouth-range" data-role="mouth-range" aria-label="Ouverture de la bouche">
          <span class="m3d-mouth-value" data-role="mouth-value">0°</span>
        </div>
        <div class="m3d-hint">Glisser : tourner · Molette : zoomer vers le curseur · Clic droit ou Maj + glisser : déplacer · Double-clic : centrer</div>
      </div>
    </div>`;

  const q = (role) => root.querySelector(`[data-role="${role}"]`);
  const scene = createScene(q('canvas'));
  const timeline = createTimeline(q('timeline'), {
    dates: [], currentDate: null, showNow: false,
    title: 'Historique des modèles 3D',
    returnLabel: 'Revenir au dernier modèle',
    countLabel: (n) => (n > 1 ? 'modèles' : 'modèle'),
    onChange: (date) => { state.viewingDate = date; renderStage(); },
  });

  // --- Données -----------------------------------------------------------

  function dates() {
    const counts = new Map();
    state.models.forEach((m) => counts.set(m.scan_date, (counts.get(m.scan_date) || 0) + 1));
    return [...counts.keys()].sort().map((date) => ({ date, change_count: counts.get(date) }));
  }

  function activeDate() {
    const ds = dates();
    if (!ds.length) return null;
    if (state.viewingDate && ds.some((d) => d.date === state.viewingDate)) return state.viewingDate;
    return ds[ds.length - 1].date;
  }

  async function reload(focusDate) {
    try {
      const data = await request('GET', base);
      state.models = data.models || [];
    } catch (e) {
      toast(e.message || 'Impossible de charger les modèles 3D', { type: 'error' });
      return;
    }
    const ds = dates();
    if (focusDate !== undefined) {
      state.viewingDate = focusDate && ds.length && ds[ds.length - 1].date !== focusDate ? focusDate : null;
    }
    if (state.viewingDate && !ds.some((d) => d.date === state.viewingDate)) state.viewingDate = null;
    timeline.update({ dates: ds, currentDate: state.viewingDate });
    renderAll();
  }

  // --- Rendu -------------------------------------------------------------

  function renderAll() {
    const n = state.models.length;
    const ds = dates();
    q('summary').textContent = n
      ? `${n} modèle${n > 1 ? 's' : ''} · ${ds.length} date${ds.length > 1 ? 's' : ''} · dernier : ${formatDate(ds[ds.length - 1].date)}`
      : '';
    q('timeline').hidden = n === 0;
    q('empty').hidden = n !== 0;
    q('stage').hidden = n === 0;
    if (n) renderStage();
  }

  function modelsOfDate(date) {
    return state.models.filter((m) => m.scan_date === date);
  }

  function renderChips(models) {
    q('chips').innerHTML = models.map((m) => {
      const off = state.hidden.has(m.id);
      return `<div class="m3d-chip${off ? ' off' : ''}" data-id="${m.id}">
        <button type="button" class="m3d-chip-btn" data-act="toggle" title="${off ? 'Afficher' : 'Masquer'}">${off ? ICON.eyeOff : ICON.eye}</button>
        <span class="m3d-chip-name" title="${esc(m.original_name)}">${esc(m.original_name)}</span>
        ${jawRole(m.original_name) === 'bite' ? '<span class="m3d-chip-tag" title="Enregistrement d’occlusion : sert à aligner les arcades, masqué par défaut">occlusion</span>' : ''}
        <span class="m3d-chip-size">${formatSize(m.file_size)}</span>
        ${m.texture_url
          ? `<button type="button" class="m3d-chip-btn" data-act="texture" title="Couleurs : ${esc(m.texture_name || '')} — cliquer pour remplacer l'image">${ICON.palette}</button>`
          : m.texture_ref
            ? `<button type="button" class="m3d-chip-warn" data-act="texture" title="Le scanner a enregistré les couleurs dans « ${esc(m.texture_ref)} ». Importez cette image (bouton Importer) : elle sera appliquée automatiquement.">${ICON.palette}Image de couleurs manquante</button>`
            : ''}
        <a class="m3d-chip-btn" href="${esc(m.url)}?download=1" title="Télécharger le fichier .ply">${ICON.download}</a>
        <button type="button" class="m3d-chip-btn danger" data-act="delete" title="Supprimer ce modèle">${ICON.trash}</button>
      </div>`;
    }).join('');
  }

  function setOverlay(text) {
    q('overlay').hidden = !text;
    q('overlay-text').textContent = text || '';
  }

  function loadGeometry(model, onProgress) {
    if (!geometries.has(model.id)) {
      const p = new Promise((resolve, reject) => {
        fileLoader.load(model.url, (buffer) => {
          try {
            const geometry = loader.parse(buffer);
            // Sans « element face » dans l'en-tête : nuage de points (un maillage aux couleurs
            // par face est aussi non indexé, l'index ne suffit donc pas à trancher).
            const header = new TextDecoder().decode(buffer.slice(0, 4096));
            const faces = /element\s+face\s+(\d+)/.exec(header);
            geometry.userData.pointCloud = !faces || Number(faces[1]) === 0;
            if (!geometry.getAttribute('position') || geometry.getAttribute('position').count === 0) {
              throw new Error('Modèle vide');
            }
            resolve(geometry);
          } catch (err) { reject(err); }
        }, (e) => onProgress(model.id, e.loaded), reject);
      });
      p.catch(() => geometries.delete(model.id));   // nouvel essai au prochain affichage
      geometries.set(model.id, p);
    }
    return geometries.get(model.id);
  }

  /** Image de couleurs du modèle (null si absente ou illisible : le modèle s'affiche sans). */
  function loadTexture(model) {
    if (!model.texture_url) return Promise.resolve(null);
    if (!textures.has(model.texture_url)) {
      textures.set(model.texture_url, new Promise((resolve) => {
        textureLoader.load(model.texture_url, (tex) => {
          tex.colorSpace = THREE.SRGBColorSpace;
          tex.anisotropy = 4;
          resolve(tex);
        }, undefined, () => {
          toast(`Couleurs de « ${model.original_name} » illisibles`, { type: 'warning' });
          resolve(null);
        });
      }));
    }
    return textures.get(model.texture_url);
  }

  async function loadModel(model, onProgress) {
    const [geometry, texture] = await Promise.all([loadGeometry(model, onProgress), loadTexture(model)]);
    return { geometry, texture };
  }

  async function renderStage() {
    const date = activeDate();
    if (!date) return;
    const models = modelsOfDate(date);
    const n = models.length;
    q('stage-title').innerHTML = `Radio du <strong>${esc(longDate(date))}</strong>${n > 1 ? ` · ${n} modèles` : ''}`;
    // Enregistrements d'occlusion (TotalJaw…) : sans couleurs et posés sur les faces des dents,
    // ils recouvrent les couleurs des arcades → masqués par défaut (l'œil les réaffiche).
    const hasArch = models.some((m) => ['upper', 'lower'].includes(jawRole(m.original_name)));
    models.forEach((m) => {
      if (state.defaulted.has(m.id)) return;
      state.defaulted.add(m.id);
      if (hasArch && jawRole(m.original_name) === 'bite') state.hidden.add(m.id);
    });
    renderChips(models);

    const token = ++state.loadToken;
    const progress = new Map();
    const total = models.reduce((s, m) => s + (m.file_size || 0), 0) || 1;
    const onProgress = (id, loaded) => {
      if (token !== state.loadToken) return;
      progress.set(id, loaded);
      const pct = Math.min(99, Math.round(([...progress.values()].reduce((a, b) => a + b, 0) / total) * 100));
      setOverlay(`Chargement du modèle… ${pct} %`);
    };

    const visible = models.filter((m) => !state.hidden.has(m.id));
    q('all-hidden').hidden = visible.length > 0;
    const cached = visible.every((m) => geometries.has(m.id));
    if (!cached) setOverlay('Chargement du modèle…');
    const results = await Promise.allSettled(visible.map((m) => loadModel(m, onProgress)));
    if (token !== state.loadToken) return;   // l'utilisateur a changé de date entre-temps
    setOverlay(null);

    const failed = results.filter((r) => r.status === 'rejected');
    if (failed.length) toast(`${failed.length} modèle(s) illisible(s) : le fichier .ply est peut-être corrompu`, { type: 'error' });

    const entries = results
      .map((r, i) => (r.status === 'fulfilled' ? { model: visible[i], ...r.value } : null))
      .filter(Boolean);
    const hasColors = entries.some((o) => o.texture || !!o.geometry.getAttribute('color'));
    q('colors-opt').hidden = !hasColors;

    // Arcades reconnues par leur nom (UpperJaw / LowerJaw…) → repère de la bouche pour les vues.
    const roles = entries.map((e) => (e.geometry.userData.pointCloud ? null : jawRole(e.model.original_name)));
    const pick = (role) => entries.filter((e, i) => roles[i] === role);
    const frameKey = `${pick('upper').map((e) => e.model.id)}|${pick('lower').map((e) => e.model.id)}`;
    if (frameKey !== state.frameKey) {
      state.frameKey = frameKey;
      const uppers = pick('upper').map((e) => e.geometry), lowers = pick('lower').map((e) => e.geometry);
      state.mouthFrame = computeMouthFrame(uppers, lowers);
      state.hinge = computeHinge(state.mouthFrame, uppers, lowers);
      if (!state.hinge) state.mouthAngle = 0;
    }
    const objects = entries.map((e, i) => {
      const o = buildObject(e, state);
      o.userData.role = roles[i];
      return o;
    });
    state.objects = objects;
    applyMouth(state.mouthAngle);
    // Cadrage sur un échantillon de sommets (plus serré qu'une boîte alignée sur les axes du fichier).
    const fitPoints = objects.flatMap((o) => samplePositions(o));
    const shownKey = `${date}|${entries.map((e) => e.model.id)}`;
    scene.show(objects, { fitPoints, frame: state.mouthFrame, keepView: shownKey === state.shownKey });
    state.shownKey = shownKey;
    updateMouthUi();
    scene.resize();
  }

  // --- Ouverture de la bouche ---------------------------------------------

  /** Pose des arcades pour une ouverture de `deg`° chacune ; occlusion masquée bouche ouverte. */
  function applyMouth(deg) {
    const mats = state.hinge ? openMatrices(state.hinge, deg) : null;
    state.objects.forEach((o) => {
      const role = o.userData.role;
      if (mats && (role === 'upper' || role === 'lower')) {
        o.matrixAutoUpdate = false;
        o.matrix.copy(mats[role]);
        o.matrixWorldNeedsUpdate = true;
      } else if (role === 'bite') {
        o.visible = deg < 0.5;
      }
    });
  }

  /** Sommets de cadrage pour une ouverture donnée (sans changer l'affichage). */
  function pointsAt(deg) {
    applyMouth(deg);
    const pts = state.objects.filter((o) => o.visible).flatMap((o) => samplePositions(o));
    applyMouth(state.mouthAngle);
    return pts;
  }

  function updateMouthUi() {
    const box = q('mouth');
    box.hidden = !state.hinge;
    if (!state.hinge) return;
    const open = state.mouthAngle > 0.5;
    q('mouth-btn').innerHTML = `${ICON.mouth}${open ? 'Fermer la bouche' : 'Ouvrir la bouche'}`;
    q('mouth-btn').classList.toggle('active', open);
    q('mouth-range').value = String(Math.round(state.mouthAngle));
    q('mouth-value').textContent = `${Math.round(state.mouthAngle)}°`;
  }

  /** Ouverture / fermeture animée ; la caméra se recadre en même temps (vue de face). */
  function animateMouth(toDeg) {
    if (!state.hinge) return;
    const from = state.mouthAngle;
    const t0 = performance.now();
    const token = ++state.mouthAnim;
    scene.refit(pointsAt(toDeg), { view: VIEWS[0], duration: MOUTH_ANIM_MS });
    const step = (now) => {
      if (token !== state.mouthAnim) return;
      const k = Math.min(1, (now - t0) / MOUTH_ANIM_MS);
      const e = k < 0.5 ? 4 * k * k * k : 1 - ((-2 * k + 2) ** 3) / 2;
      state.mouthAngle = from + (toDeg - from) * e;
      applyMouth(state.mouthAngle);
      updateMouthUi();
      scene.requestRender();
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // --- Import ------------------------------------------------------------

  /** Modèle déjà importé (ce patient) qui nomme cette image dans son en-tête. */
  function existingModelFor(imageName) {
    const n = imageName.toLowerCase();
    return state.models.find((x) => (x.texture_ref || '').toLowerCase() === n) || null;
  }

  function openUpload() {
    const today = todayIso();
    const m = openModal({
      title: '<h3>Importer des modèles 3D</h3>',
      subtitle: 'Déposez les fichiers exportés par le scanner : les couleurs sont associées automatiquement.',
      className: 'odonto-modal-sm',
      body: `<form class="m3d-upload" data-role="form">
        <div class="odonto-field">
          <label for="m3d-date">Date de la radio</label>
          <input type="date" id="m3d-date" name="scan_date" class="m3d-input" value="${today}" max="${today}">
          <p class="odonto-subtle odonto-small" data-role="date-hint" style="margin:6px 0 0;" hidden></p>
        </div>
        <div class="odonto-field">
          <label for="m3d-file">Fichiers du scanner</label>
          <label class="m3d-drop" data-role="drop">
            <input type="file" id="m3d-file" name="file" accept=".ply,.png,.jpg,.jpeg" multiple>
            <span class="m3d-drop-icon">${ICON.upload}</span>
            <span data-role="drop-text">${DROP_HINT}</span>
          </label>
          <button type="button" class="odo-btn odo-btn-ghost odo-btn-xs m3d-folder-btn" data-act="folder">Choisir un dossier entier</button>
          <input type="file" data-role="folder-input" webkitdirectory multiple hidden>
          <ul class="m3d-pairs" data-role="pairs" hidden></ul>
        </div>
        <div class="m3d-progress" data-role="progress" hidden><div class="m3d-progress-bar" data-role="bar"></div></div>
        <p class="m3d-progress-text odonto-small odonto-muted" data-role="progress-text"></p>
      </form>`,
      footer: `<button type="button" class="odo-btn odo-btn-outline" data-act="close">Annuler</button>
        <button type="button" class="odo-btn odo-btn-primary" data-act="send">${ICON.upload}Importer</button>`,
    });
    const el = (role) => m.el.querySelector(`[data-role="${role}"]`);
    const fileInput = m.el.querySelector('#m3d-file');
    const folderInput = el('folder-input');
    const dateInput = m.el.querySelector('#m3d-date');
    const sendBtn = m.el.querySelector('[data-act="send"]');

    let selected = [];     // fichiers retenus (.ply / images)
    let ignored = 0;       // autres fichiers d'un dossier
    let pairing = { items: [], stray: [], bad: [] };
    let dateTouched = false;
    dateInput.addEventListener('input', () => { dateTouched = true; el('date-hint').hidden = true; });

    function setFiles(files) {
      selected = files.filter((f) => /\.ply$/i.test(f.name) || IMAGE_RE.test(f.name));
      ignored = files.length - selected.length;
      showFiles();
    }

    /** Date lue dans le nom des fichiers du scanner (« 2026-10-20_100_004-UpperJaw.ply »). */
    function dateFromNames() {
      const named = selected.filter((f) => /\.ply$/i.test(f.name));
      const ds = new Set((named.length ? named : selected)
        .map((f) => (/^(\d{4}-\d{2}-\d{2})/.exec(f.name) || [])[1]).filter(Boolean));
      if (ds.size !== 1) return null;
      const d = [...ds][0];
      return !Number.isNaN(new Date(d + 'T00:00:00').getTime()) && d <= today ? d : null;
    }

    async function showFiles() {
      const n = selected.length;
      el('drop').classList.toggle('filled', n > 0);
      el('drop-text').textContent = n ? `${n} fichier${n > 1 ? 's' : ''} sélectionné${n > 1 ? 's' : ''}` : DROP_HINT;
      if (!dateTouched) {
        const d = dateFromNames();
        if (d) dateInput.value = d;
        el('date-hint').hidden = !d;
        el('date-hint').textContent = d ? 'Date lue dans le nom des fichiers.' : '';
      }
      pairing = await pairFiles(selected);
      const lines = pairing.items.map(({ ply, ref, image, sharedWith }) => {
        const head = `<strong>${esc(ply.name)}</strong> <span class="odonto-subtle">${formatSize(ply.size)}</span>`;
        if (image) return `<li class="ok">${ICON.palette}<span>${head} — couleurs : ${esc(image.name)}</span></li>`;
        if (sharedWith) return `<li class="ok">${ICON.palette}<span>${head} — couleurs : ${esc(sharedWith.name)}</span></li>`;
        if (ref && existingModelFor(ref) && existingModelFor(ref).texture_url) {
          return `<li class="ok">${ICON.palette}<span>${head} — couleurs reprises du modèle déjà importé</span></li>`;
        }
        if (ref) return `<li class="warn">${ICON.palette}<span>${head} — couleurs dans « ${esc(ref)} », pas encore importée : elle sera appliquée automatiquement dès que vous l'importerez</span></li>`;
        return `<li><span>${head} — ce fichier ne contient pas de couleurs</span></li>`;
      });
      pairing.stray.forEach((f) => {
        const target = existingModelFor(f.name);
        lines.push(target
          ? `<li class="ok">${ICON.palette}<span>${esc(f.name)} — couleurs de « ${esc(target.original_name)} » (déjà importé)</span></li>`
          : `<li class="warn">${ICON.palette}<span>${esc(f.name)} — gardée : appliquée automatiquement au .ply qui l'utilise quand il sera importé</span></li>`);
      });
      if (ignored) lines.push(`<li><span>${ignored} autre${ignored > 1 ? 's' : ''} fichier${ignored > 1 ? 's' : ''} du dossier ignoré${ignored > 1 ? 's' : ''}</span></li>`);
      el('pairs').innerHTML = lines.join('');
      el('pairs').hidden = lines.length === 0;
    }

    fileInput.addEventListener('change', () => setFiles([...fileInput.files]));
    folderInput.addEventListener('change', () => setFiles([...folderInput.files]));
    m.el.querySelector('[data-act="folder"]').addEventListener('click', () => folderInput.click());
    const drop = el('drop');
    drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('over'));
    drop.addEventListener('drop', async (e) => {
      e.preventDefault();
      drop.classList.remove('over');
      setFiles(await droppedFiles(e.dataTransfer));
    });

    function lock(locked) {
      sendBtn.disabled = locked;
      dateInput.disabled = locked;
      fileInput.disabled = locked;
      el('progress').hidden = !locked;
    }

    sendBtn.addEventListener('click', async () => {
      pairing = await pairFiles(selected);
      const { items, stray } = pairing;
      const date = dateInput.value;
      if (!items.length && !stray.length) { toast('Choisissez les fichiers .ply (et leurs images) à importer', { type: 'warning' }); return; }
      if (items.length && !date) { toast('Indiquez la date de la radio', { type: 'warning' }); return; }
      if (items.length && date > today) { toast('La date de la radio ne peut pas être dans le futur', { type: 'warning' }); return; }

      lock(true);
      const steps = items.length + (stray.length ? 1 : 0);
      let done = 0;
      const progress = (label) => (frac) => {
        el('bar').style.width = `${Math.round(((done + frac) / steps) * 100)}%`;
        el('progress-text').textContent = frac < 1 ? `Envoi de ${label}… ${Math.round(frac * 100)} %` : `Enregistrement de ${label}…`;
      };
      let imagesResult = null;
      let duplicates = 0;
      try {
        for (const { ply, image } of items) {
          const fd = new FormData();
          fd.append('scan_date', date);
          fd.append('file', ply);
          if (image) fd.append('texture', image);
          const res = await uploadFile(base, fd, progress(`« ${ply.name} »`));
          if (res && res.duplicate) duplicates += 1;
          done += 1;
        }
        if (stray.length) {
          const fd = new FormData();
          stray.forEach((f) => fd.append('images', f));
          imagesResult = await uploadFile(`${base}/images`, fd, progress(stray.length > 1 ? `${stray.length} images` : `« ${stray[0].name} »`));
          done += 1;
        }
      } catch (err) {
        toast(err.message || "Échec de l'import", { type: 'error', duration: 5000 });
        lock(false);
        if (done) reload(items.length ? date : undefined);
        return;
      }
      m.close();
      const parts = [];
      const added = items.length - duplicates;
      if (added) parts.push(added > 1 ? `${added} modèles importés` : 'Modèle 3D importé');
      if (duplicates) parts.push(`${duplicates} fichier${duplicates > 1 ? 's' : ''} déjà importé${duplicates > 1 ? 's' : ''} : ignoré${duplicates > 1 ? 's' : ''}`);
      if (imagesResult) {
        const colored = imagesResult.attached.reduce((s, a) => s + a.models.length, 0);
        if (colored) parts.push(`couleurs ajoutées à ${colored} modèle${colored > 1 ? 's' : ''}`);
        if (imagesResult.pending.length) parts.push(`${imagesResult.pending.length} image(s) en attente de leur .ply`);
        if (imagesResult.errors.length) toast(imagesResult.errors.join(' · '), { type: 'error', duration: 6000 });
      }
      if (parts.length) toast(parts.join(' · '));
      reload(items.length ? date : undefined);
    });
  }

  // --- Événements --------------------------------------------------------

  function onClick(e) {
    if (e.target.closest('[data-act="upload"]')) { openUpload(); return; }
    if (e.target.closest('[data-act="mouth"]')) { animateMouth(state.mouthAngle > 0.5 ? 0 : MOUTH_OPEN_DEG); return; }
    const viewBtn = e.target.closest('[data-view]');
    if (viewBtn) { scene.setView(VIEWS.find((v) => v.key === viewBtn.dataset.view)); return; }
    if (e.target.closest('[data-act="snapshot"]')) {
      const a = document.createElement('a');
      a.href = scene.snapshot();
      a.download = `modele-3d-${activeDate()}.png`;
      a.click();
      return;
    }
    const chip = e.target.closest('.m3d-chip');
    if (!chip) return;
    const id = Number(chip.dataset.id);
    if (e.target.closest('[data-act="toggle"]')) {
      if (state.hidden.has(id)) state.hidden.delete(id); else state.hidden.add(id);
      renderStage();
    } else if (e.target.closest('[data-act="texture"]')) {
      pickTexture(state.models.find((x) => x.id === id));
    } else if (e.target.closest('[data-act="delete"]')) {
      const model = state.models.find((x) => x.id === id);
      confirmDialog({
        title: 'Supprimer ce modèle 3D ?',
        text: `« ${model ? model.original_name : ''} » sera définitivement supprimé du dossier du patient.`,
        confirmLabel: 'Supprimer', danger: true,
        onConfirm: async () => {
          try {
            await request('DELETE', `${base}/${id}`);
          } catch (err) {
            toast(err.message || 'Suppression impossible', { type: 'error' });
            return;
          }
          const g = geometries.get(id);
          geometries.delete(id);
          if (g) g.then((geo) => geo.dispose()).catch(() => {});
          disposeTexture(model && model.texture_url);
          toast('Modèle 3D supprimé');
          reload();
        },
      });
    }
  }

  function disposeTexture(url) {
    const t = url && textures.get(url);
    if (!t) return;
    textures.delete(url);
    t.then((tex) => tex && tex.dispose());
  }

  /** Ajout (ou remplacement) de l'image de couleurs d'un modèle déjà importé. */
  function pickTexture(model) {
    if (!model) return;
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.png,.jpg,.jpeg';
    input.addEventListener('change', async () => {
      const file = input.files[0];
      if (!file) return;
      if (model.texture_ref && file.name.toLowerCase() !== model.texture_ref.toLowerCase()) {
        toast(`Attention : le scanner attendait « ${model.texture_ref} »`, { type: 'warning', duration: 4500 });
      }
      const fd = new FormData();
      fd.append('texture', file);
      try {
        await uploadFile(`${base}/${model.id}/texture`, fd, () => {});
      } catch (err) {
        toast(err.message || "Échec de l'import de l'image", { type: 'error', duration: 5000 });
        return;
      }
      disposeTexture(model.texture_url);
      toast('Couleurs ajoutées au modèle');
      reload();
    });
    input.click();
  }

  function onInput(e) {
    if (!e.target.matches('[data-act="mouth-range"]')) return;
    state.mouthAnim += 1;   // stoppe une animation en cours
    state.mouthAngle = Number(e.target.value);
    applyMouth(state.mouthAngle);
    updateMouthUi();
    scene.requestRender();
  }

  function onChange(e) {
    if (e.target.matches('[data-act="mouth-range"]')) { scene.refit(pointsAt(state.mouthAngle)); return; }
    if (e.target.matches('[data-act="colors"]')) { state.useColors = e.target.checked; renderStage(); }
    if (e.target.matches('[data-act="wireframe"]')) { state.wireframe = e.target.checked; renderStage(); }
  }

  root.addEventListener('click', onClick);
  root.addEventListener('change', onChange);
  root.addEventListener('input', onInput);
  reload();

  return {
    /** À appeler quand l'onglet redevient visible (le canevas avait une taille nulle). */
    refresh() { scene.resize(); },
    destroy() {
      root.removeEventListener('click', onClick);
      root.removeEventListener('change', onChange);
      root.removeEventListener('input', onInput);
      timeline.destroy();
      scene.destroy();
      geometries.forEach((p) => p.then((g) => g.dispose()).catch(() => {}));
      textures.forEach((p) => p.then((t) => t && t.dispose()));
      root.innerHTML = '';
    },
  };
}
