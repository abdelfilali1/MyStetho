/* Radio IA — moteur de détection DANS LE NAVIGATEUR (onnxruntime-web / WASM).
 *
 * Calqué sur static/js/ceph/autodetect.js : le modèle YOLOv8 DentalXrayAI (DENTEX)
 * tourne côté client, la VM ne sert que des fichiers statiques (elle n'a pas assez
 * de RAM pour PyTorch). Le runtime ORT est RÉUTILISÉ depuis le module Céphalométrie
 * (static/js/ceph/ort/) pour ne pas dupliquer ~11 Mo de WASM.
 *
 * Différences YOLOv8 vs le modèle HRNet de la céphalo :
 *   - normalisation /255 seule (pas de moyenne/écart-type ImageNet) ;
 *   - letterbox avec un remplissage gris 114 (et non noir) ;
 *   - décodage de la sortie [1, 4+nc, 8400] : xywh + scores de classe, seuil de
 *     confiance puis suppression des non-maxima (NMS), enfin transformée inverse.
 */

const MODEL_URL = "/static/js/radio/model/dentalxray.onnx";
// Runtime ORT partagé avec la Céphalométrie (déjà déployé sur la VM).
const ORT_DIR = "/static/js/ceph/ort/";
const ORT_SCRIPT = ORT_DIR + "ort.min.js";

const IN = 640;             // taille d'entrée du réseau
const PAD = 114;            // gris de remplissage du letterbox (convention Ultralytics)
const CONF_MIN = 0.25;      // seuil de confiance
const IOU_NMS = 0.45;       // seuil IoU pour la NMS

// Ordre des classes = model.names de DentalXrayAI (vérifié à l'export).
const CLASS_NAMES = ["Caries", "Deep Caries", "Impacted", "Periapical Lesion"];
// Libellés FR + couleurs (miroir de services/radio_ai.py).
const CLASS_META = {
    "Caries": { label: "Carie", color: "#f59e0b" },
    "Deep Caries": { label: "Carie profonde", color: "#ef4444" },
    "Impacted": { label: "Dent incluse", color: "#6366f1" },
    "Periapical Lesion": { label: "Lésion périapicale", color: "#10b981" }
};

let ortReady = null;   // promesse de chargement d'onnxruntime-web
let session = null;    // session ORT (chargée une fois)

function loadOrt() {
    if (ortReady) return ortReady;
    ortReady = new Promise((resolve, reject) => {
        if (window.ort) return resolve(window.ort);
        const s = document.createElement("script");
        s.src = ORT_SCRIPT;
        s.onload = () => resolve(window.ort);
        s.onerror = () => reject(new Error("Chargement du moteur IA (onnxruntime-web) impossible."));
        document.head.appendChild(s);
    }).then((ort) => {
        // Mono-thread : pas besoin d'isolation cross-origin (COOP/COEP).
        ort.env.wasm.wasmPaths = ORT_DIR;
        ort.env.wasm.numThreads = 1;
        ort.env.wasm.simd = true;
        return ort;
    });
    return ortReady;
}

async function fetchModel(onProgress) {
    const res = await fetch(MODEL_URL);
    if (!res.ok) throw new Error("Modèle IA introuvable (HTTP " + res.status + ").");
    const total = Number(res.headers.get("content-length") || 0);
    if (!res.body || !total) return await res.arrayBuffer();
    const reader = res.body.getReader();
    const chunks = [];
    let received = 0;
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        received += value.length;
        if (onProgress) onProgress("Téléchargement du modèle… " + Math.round(received / total * 100) + " %");
    }
    const buf = new Uint8Array(received);
    let pos = 0;
    for (const c of chunks) { buf.set(c, pos); pos += c.length; }
    return buf.buffer;
}

async function getSession(onProgress) {
    if (session) return session;
    const ort = await loadOrt();
    if (onProgress) onProgress("Téléchargement du modèle…");
    const buf = await fetchModel(onProgress);
    if (onProgress) onProgress("Initialisation du moteur…");
    session = await ort.InferenceSession.create(buf, {
        executionProviders: ["wasm"],
        graphOptimizationLevel: "all"
    });
    return session;
}

// Letterbox 640×640 (gris 114) + tenseur CHW planaire normalisé /255.
function preprocess(bitmap, w, h) {
    const scale = Math.min(IN / w, IN / h);
    const dw = Math.round(w * scale);
    const dh = Math.round(h * scale);
    const padX = Math.floor((IN - dw) / 2);
    const padY = Math.floor((IN - dh) / 2);

    const canvas = document.createElement("canvas");
    canvas.width = IN; canvas.height = IN;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "rgb(114,114,114)";
    ctx.fillRect(0, 0, IN, IN);
    ctx.drawImage(bitmap, 0, 0, w, h, padX, padY, dw, dh);
    const { data } = ctx.getImageData(0, 0, IN, IN);

    const chw = new Float32Array(3 * IN * IN);
    const plane = IN * IN;
    for (let i = 0, p = 0; i < plane; i++, p += 4) {
        chw[i] = data[p] / 255;                 // R
        chw[plane + i] = data[p + 1] / 255;     // G
        chw[2 * plane + i] = data[p + 2] / 255; // B
    }
    // Transformée inverse : coord réseau (640) → pixel image naturelle.
    const toImage = (nx, ny) => ({ x: (nx - padX) / scale, y: (ny - padY) / scale });
    return { chw, toImage };
}

function iou(a, b) {
    const x1 = Math.max(a.x1, b.x1), y1 = Math.max(a.y1, b.y1);
    const x2 = Math.min(a.x2, b.x2), y2 = Math.min(a.y2, b.y2);
    const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
    const areaA = (a.x2 - a.x1) * (a.y2 - a.y1);
    const areaB = (b.x2 - b.x1) * (b.y2 - b.y1);
    const denom = areaA + areaB - inter;
    return denom > 0 ? inter / denom : 0;
}

// NMS par classe (IoU > seuil → on garde la boîte de plus forte confiance).
function nms(boxes) {
    const kept = [];
    const byClass = {};
    boxes.forEach((b) => { (byClass[b.clsId] = byClass[b.clsId] || []).push(b); });
    Object.keys(byClass).forEach((k) => {
        const arr = byClass[k].sort((a, b) => b.conf - a.conf);
        const survivors = [];
        arr.forEach((cand) => {
            if (survivors.every((s) => iou(cand, s) <= IOU_NMS)) survivors.push(cand);
        });
        kept.push(...survivors);
    });
    return kept;
}

// n° de dent FDI estimé géométriquement (miroir de radio_ai.estimate_fdi).
function estimateFdi(cxNorm, cyNorm) {
    const upper = cyNorm < 0.5;
    let pos, quadrant;
    if (cxNorm < 0.5) { quadrant = upper ? 1 : 4; pos = (0.5 - cxNorm) / 0.5; }
    else { quadrant = upper ? 2 : 3; pos = (cxNorm - 0.5) / 0.5; }
    const t = Math.max(1, Math.min(8, Math.round(pos * 7) + 1));
    return quadrant * 10 + t;
}

function decode(out, dims, toImage, w, h) {
    // dims = [1, 4+nc, 8400] ; data en channels-first : data[c*n + i].
    const nc = CLASS_NAMES.length;
    const ch = dims[1];         // 4 + nc
    const n = dims[2];          // 8400
    const data = out;
    const raw = [];
    for (let i = 0; i < n; i++) {
        let best = 0, bestId = 0;
        for (let k = 0; k < nc; k++) {
            const s = data[(4 + k) * n + i];
            if (s > best) { best = s; bestId = k; }
        }
        if (best < CONF_MIN) continue;
        const cx = data[i], cy = data[n + i], bw = data[2 * n + i], bh = data[3 * n + i];
        // xywh (espace 640) → coins → image naturelle.
        const p1 = toImage(cx - bw / 2, cy - bh / 2);
        const p2 = toImage(cx + bw / 2, cy + bh / 2);
        const x1 = Math.max(0, Math.min(w, p1.x)), y1 = Math.max(0, Math.min(h, p1.y));
        const x2 = Math.max(0, Math.min(w, p2.x)), y2 = Math.max(0, Math.min(h, p2.y));
        if (x2 - x1 < 1 || y2 - y1 < 1) continue;
        raw.push({ clsId: bestId, conf: best, x1: x1, y1: y1, x2: x2, y2: y2 });
    }
    const kept = nms(raw).sort((a, b) => b.conf - a.conf);
    return kept.map((b, idx) => {
        const name = CLASS_NAMES[b.clsId] || String(b.clsId);
        const meta = CLASS_META[name] || { label: name, color: "#0ea5e9" };
        const cxN = (b.x1 + b.x2) / 2 / w, cyN = (b.y1 + b.y2) / 2 / h;
        return {
            id: idx,
            cls: name,
            label: meta.label,
            color: meta.color,
            conf: Math.round(b.conf * 10000) / 10000,
            box: [Math.round(b.x1 * 10) / 10, Math.round(b.y1 * 10) / 10,
                  Math.round(b.x2 * 10) / 10, Math.round(b.y2 * 10) / 10],
            nbox: [b.x1 / w, b.y1 / h, b.x2 / w, b.y2 / h].map((v) => Math.round(v * 1e5) / 1e5),
            tooth: estimateFdi(cxN, cyN),
            tooth_estimated: true,
            dismissed: false,
            source: "ai"
        };
    });
}

/**
 * Détecte les pathologies sur un ImageBitmap. Renvoie un objet compatible avec
 * le format serveur historique : { model, image_w, image_h, detections: [...] }.
 */
export async function detectPathologies(bitmap, w, h, onProgress) {
    const sess = await getSession(onProgress);
    const ort = await loadOrt();
    if (onProgress) onProgress("Analyse…");
    const { chw, toImage } = preprocess(bitmap, w, h);
    const tensor = new ort.Tensor("float32", chw, [1, 3, IN, IN]);
    const feeds = {};
    feeds[sess.inputNames[0]] = tensor;
    const out = await sess.run(feeds);
    const o = out[sess.outputNames[0]];
    const detections = decode(o.data, o.dims, toImage, w, h);
    return { model: "dentalxray.onnx", image_w: w, image_h: h, detections: detections };
}

/** Vrai si le fichier modèle est déployé (sinon on masque le bouton). */
export async function modelAvailable() {
    try {
        const r = await fetch(MODEL_URL, { method: "HEAD" });
        return r.ok;
    } catch (e) {
        return false;
    }
}
