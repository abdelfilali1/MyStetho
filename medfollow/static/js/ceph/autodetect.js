/**
 * Détection automatique des points céphalométriques — brouillon assisté par IA.
 *
 * Le modèle (HRNet-W32, 19 points ISBI, licence MIT) tourne ENTIÈREMENT dans le
 * navigateur via onnxruntime-web (WebAssembly). La radiographie ne quitte jamais
 * le poste du praticien. Le résultat est un BROUILLON : chaque point posé par
 * l'IA est marqué « suggéré » et doit être validé/corrigé par le praticien.
 *
 * Attention : la précision est modeste (~1,5–1,8 mm en conditions réelles) et
 * certains points (Porion, Orbitale, Gonion, Articulare, ENA, ENP) sont
 * notoirement peu fiables — ils sont signalés pour vérification prioritaire.
 */

const MODEL_URL = '/static/js/ceph/model/ceph-hrnet-int8.onnx';
const ORT_DIR = '/static/js/ceph/ort/';
const ORT_SCRIPT = ORT_DIR + 'ort.min.js';

// Taille d'entrée du réseau et de ses cartes de chaleur (heatmaps).
const IN = 768;
const HM = 192;              // 768 / 4
const MEAN = [0.485, 0.456, 0.406];
const STD = [0.229, 0.224, 0.225];

/**
 * Ordre EXACT des 19 canaux de sortie (jeu ISBI standard, confirmé par la fiche
 * du modèle) → identifiants de points Doctivo. Les points absents du réseau
 * (apex incisifs, D, Xi, tissus mous fins…) restent à poser à la main.
 */
export const ISBI_TO_DOCTIVO = [
    'S',    // 0  Sella
    'N',    // 1  Nasion
    'Or',   // 2  Orbitale        (peu fiable)
    'Po',   // 3  Porion          (peu fiable)
    'A',    // 4  Sous-épineux (point A)
    'B',    // 5  Supra-mentonnier (point B)
    'Pog',  // 6  Pogonion
    'Me',   // 7  Menton
    'Gn',   // 8  Gnathion
    'Go',   // 9  Gonion           (peu fiable)
    'L1T',  // 10 Bord incisive inférieure
    'U1T',  // 11 Bord incisive supérieure
    'Ls',   // 12 Labrale superius
    'Li',   // 13 Labrale inferius
    'Sn',   // 14 Sous-nasal
    'Pog_', // 15 Pogonion cutané
    'PNS',  // 16 Épine nasale postérieure (peu fiable)
    'ANS',  // 17 Épine nasale antérieure  (peu fiable)
    'Ar',   // 18 Articulare        (peu fiable)
];

/** Points que la littérature signale comme peu fiables → à revérifier en priorité. */
export const UNRELIABLE = new Set(['Or', 'Po', 'Go', 'Ar', 'ANS', 'PNS']);

let ortReady = null;   // promesse de chargement d'onnxruntime-web
let session = null;    // session ORT (chargée une fois)

/** Charge onnxruntime-web (une seule fois) via une balise <script> same-origin. */
function loadOrt() {
    if (ortReady) return ortReady;
    ortReady = new Promise((resolve, reject) => {
        if (window.ort) return resolve(window.ort);
        const s = document.createElement('script');
        s.src = ORT_SCRIPT;
        s.onload = () => resolve(window.ort);
        s.onerror = () => reject(new Error('Chargement du moteur IA (onnxruntime-web) impossible.'));
        document.head.appendChild(s);
    }).then((ort) => {
        // WASM mono-thread : pas besoin d'isolation cross-origin (SharedArrayBuffer).
        ort.env.wasm.wasmPaths = ORT_DIR;
        ort.env.wasm.numThreads = 1;
        ort.env.wasm.simd = true;
        return ort;
    });
    return ortReady;
}

/** Récupère (et met en cache) la session ONNX du modèle. */
async function getSession(onProgress) {
    if (session) return session;
    const ort = await loadOrt();
    if (onProgress) onProgress('Téléchargement du modèle…');
    const buf = await fetchModel(onProgress);
    if (onProgress) onProgress('Initialisation du moteur…');
    session = await ort.InferenceSession.create(buf, {
        executionProviders: ['wasm'],
        graphOptimizationLevel: 'all',
    });
    return session;
}

/** Télécharge le modèle en signalant la progression (fichier volumineux). */
async function fetchModel(onProgress) {
    const res = await fetch(MODEL_URL);
    if (!res.ok) throw new Error('Modèle IA introuvable sur le serveur.');
    const total = Number(res.headers.get('content-length')) || 0;
    if (!res.body || !total) return res.arrayBuffer();
    const reader = res.body.getReader();
    const chunks = [];
    let received = 0;
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        received += value.length;
        if (onProgress) onProgress(`Téléchargement du modèle… ${Math.round((received / total) * 100)} %`);
    }
    const out = new Uint8Array(received);
    let off = 0;
    for (const c of chunks) { out.set(c, off); off += c.length; }
    return out.buffer;
}

/**
 * Compose la radiographie sur un carré INxIN, en préservant les proportions
 * (letterbox). Renvoie le tenseur CHW normalisé + la transformation inverse pour
 * repasser des coordonnées réseau aux pixels de l'image naturelle.
 */
function preprocess(bitmap, w, h) {
    const scale = Math.min(IN / w, IN / h);
    const dw = Math.round(w * scale);
    const dh = Math.round(h * scale);
    const padX = Math.floor((IN - dw) / 2);
    const padY = Math.floor((IN - dh) / 2);

    const canvas = document.createElement('canvas');
    canvas.width = IN;
    canvas.height = IN;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, IN, IN);
    ctx.drawImage(bitmap, 0, 0, w, h, padX, padY, dw, dh);
    const { data } = ctx.getImageData(0, 0, IN, IN);

    // RGBA entrelacé -> CHW normalisé (ImageNet).
    const chw = new Float32Array(3 * IN * IN);
    const plane = IN * IN;
    for (let i = 0, p = 0; i < plane; i++, p += 4) {
        chw[i] = (data[p] / 255 - MEAN[0]) / STD[0];
        chw[plane + i] = (data[p + 1] / 255 - MEAN[1]) / STD[1];
        chw[2 * plane + i] = (data[p + 2] / 255 - MEAN[2]) / STD[2];
    }
    // Inverse : coord réseau (768) -> pixel image naturelle.
    const toImage = (nx, ny) => ({ x: (nx - padX) / scale, y: (ny - padY) / scale });
    return { chw, toImage };
}

/**
 * Décode une carte de chaleur 192×192 : argmax + raffinement sous-pixel (décalage
 * de 0,25 px vers le voisin le plus fort, post-traitement HRNet standard).
 * Renvoie la position en coordonnées réseau (768) et la confiance (max).
 */
function decodeHeatmap(hm, base) {
    let best = -Infinity, bx = 0, by = 0;
    for (let y = 0; y < HM; y++) {
        for (let x = 0; x < HM; x++) {
            const v = hm[base + y * HM + x];
            if (v > best) { best = v; bx = x; by = y; }
        }
    }
    let fx = bx, fy = by;
    if (bx > 0 && bx < HM - 1 && by > 0 && by < HM - 1) {
        const dx = hm[base + by * HM + bx + 1] - hm[base + by * HM + bx - 1];
        const dy = hm[base + (by + 1) * HM + bx] - hm[base + (by - 1) * HM + bx];
        fx += Math.sign(dx) * 0.25;
        fy += Math.sign(dy) * 0.25;
    }
    // heatmap (192) -> entrée réseau (768) : facteur 4, centre de pixel.
    return { nx: (fx + 0.5) * 4, ny: (fy + 0.5) * 4, conf: best };
}

/**
 * Détecte les 19 points sur la radiographie.
 * @returns {Promise<{landmarks: Object, unreliable: string[], lowConf: string[]}>}
 *          landmarks : { id: {x, y} } en pixels de l'image naturelle.
 */
export async function detectLandmarks(bitmap, w, h, onProgress) {
    const sess = await getSession(onProgress);
    const ort = await loadOrt();
    if (onProgress) onProgress('Analyse de la radiographie…');

    const { chw, toImage } = preprocess(bitmap, w, h);
    const tensor = new ort.Tensor('float32', chw, [1, 3, IN, IN]);
    const feeds = {};
    feeds[sess.inputNames[0]] = tensor;
    const out = await sess.run(feeds);
    const hm = out[sess.outputNames[0]].data;   // Float32Array [1,19,192,192]

    const landmarks = {};
    const lowConf = [];
    // Seuil de confiance relatif : sous ce niveau, on marque le point comme douteux.
    const CONF_MIN = 0.15;
    for (let k = 0; k < ISBI_TO_DOCTIVO.length; k++) {
        const id = ISBI_TO_DOCTIVO[k];
        const { nx, ny, conf } = decodeHeatmap(hm, k * HM * HM);
        const p = toImage(nx, ny);
        // Garde-fou : rester dans les bornes de l'image.
        landmarks[id] = {
            x: Math.max(0, Math.min(w, p.x)),
            y: Math.max(0, Math.min(h, p.y)),
        };
        if (conf < CONF_MIN) lowConf.push(id);
    }
    return { landmarks, unreliable: [...UNRELIABLE], lowConf };
}

/** Vrai si l'asset modèle est présent (sinon le bouton reste masqué). */
export async function modelAvailable() {
    try {
        const r = await fetch(MODEL_URL, { method: 'HEAD' });
        return r.ok;
    } catch (e) {
        return false;
    }
}
