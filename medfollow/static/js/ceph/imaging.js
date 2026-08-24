/**
 * Traitement d'image de la visionneuse céphalométrique.
 *
 * Tout ce qui a besoin d'accéder aux pixels vit ici, et s'exécute UNE SEULE
 * FOIS, hors écran, au chargement du cliché :
 *   - l'histogramme des niveaux de gris et ses centiles (base des presets) ;
 *   - l'image égalisée localement (CLAHE), produite en blob et mise en cache.
 *
 * La visionneuse elle-même reste en SVG : le fenêtrage, le gamma et
 * l'accentuation sont des filtres SVG, donc gratuits pendant la manipulation.
 * Aucun pixel n'est recalculé quand le praticien déplace la souris.
 *
 * La radiographie est servie par l'application (même origine) : la lecture des
 * pixels par canvas est donc autorisée, rien ne sort du poste.
 */

const HIST_MAX_PIXELS = 2_000_000;   // sous-échantillonnage pour l'histogramme

/** Dessine une image dans un canvas hors écran et renvoie son ImageData. */
function toImageData(img, maxPixels) {
    let w = img.naturalWidth || img.width;
    let h = img.naturalHeight || img.height;
    if (maxPixels && w * h > maxPixels) {
        const k = Math.sqrt(maxPixels / (w * h));
        w = Math.max(1, Math.round(w * k));
        h = Math.max(1, Math.round(h * k));
    }
    const cv = document.createElement('canvas');
    cv.width = w;
    cv.height = h;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0, w, h);
    return ctx.getImageData(0, 0, w, h);
}

/** Luminance perçue, ramenée à un octet. */
function luma(r, g, b) {
    return (r * 0.299 + g * 0.587 + b * 0.114) | 0;
}

/**
 * Histogramme 256 classes + centiles.
 * Les centiles servent de base aux presets : ils s'adaptent à chaque cliché,
 * là où des seuils fixes ne marcheraient que sur un appareil donné.
 */
export function computeHistogram(img) {
    const data = toImageData(img, HIST_MAX_PIXELS).data;
    const hist = new Float64Array(256);
    let n = 0;
    for (let i = 0; i < data.length; i += 4) {
        if (data[i + 3] === 0) continue;          // pixel transparent : ignoré
        hist[luma(data[i], data[i + 1], data[i + 2])]++;
        n++;
    }

    // Table des centiles : percentile(p) en une lecture cumulée.
    const cum = new Float64Array(256);
    let acc = 0;
    for (let v = 0; v < 256; v++) {
        acc += hist[v];
        cum[v] = acc;
    }
    const percentile = (p) => {
        if (!n) return p * 2.55;
        const target = (p / 100) * n;
        let lo = 0;
        let hi = 255;
        while (lo < hi) {
            const mid = (lo + hi) >> 1;
            if (cum[mid] < target) lo = mid + 1; else hi = mid;
        }
        return lo;
    };

    let peak = 0;
    for (let v = 0; v < 256; v++) if (hist[v] > peak) peak = hist[v];

    return { hist, count: n, peak, percentile };
}

/**
 * CLAHE — égalisation d'histogramme à contraste limité.
 *
 * L'intérêt clinique sur une téléradiographie de profil : une courbe de tons
 * GLOBALE ne peut pas révéler en même temps les corticales (denses) et le
 * profil cutané (très peu dense). CLAHE égalise par tuiles, avec une limite
 * d'écrêtage qui empêche d'amplifier le bruit, puis interpole entre tuiles
 * pour ne laisser aucune couture visible.
 *
 * @param {HTMLImageElement} img
 * @param {{tiles?: number, clip?: number}} opts
 * @returns {Promise<string>} URL blob de l'image traitée
 */
export function computeClahe(img, opts = {}) {
    const TILES = opts.tiles || 8;
    const CLIP = opts.clip || 2.5;      // × la hauteur moyenne de l'histogramme

    const w = img.naturalWidth || img.width;
    const h = img.naturalHeight || img.height;
    const cv = document.createElement('canvas');
    cv.width = w;
    cv.height = h;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const imageData = ctx.getImageData(0, 0, w, h);
    const px = imageData.data;

    // Plan de luminance (l'image est grise, mais on ne le suppose pas).
    const gray = new Uint8Array(w * h);
    for (let i = 0, p = 0; i < px.length; i += 4, p++) {
        gray[p] = luma(px[i], px[i + 1], px[i + 2]);
    }

    const tw = Math.ceil(w / TILES);
    const th = Math.ceil(h / TILES);
    // Une LUT de 256 entrées par tuile.
    const luts = new Uint8Array(TILES * TILES * 256);

    const hist = new Uint32Array(256);
    for (let ty = 0; ty < TILES; ty++) {
        for (let tx = 0; tx < TILES; tx++) {
            hist.fill(0);
            const x0 = tx * tw;
            const y0 = ty * th;
            const x1 = Math.min(w, x0 + tw);
            const y1 = Math.min(h, y0 + th);
            let n = 0;
            for (let y = y0; y < y1; y++) {
                const row = y * w;
                for (let x = x0; x < x1; x++) {
                    hist[gray[row + x]]++;
                    n++;
                }
            }
            if (!n) continue;

            // Écrêtage : on rabote les classes trop hautes et on redistribue
            // uniformément l'excédent (sinon le bruit de fond explose).
            const limit = Math.max(1, Math.floor((CLIP * n) / 256));
            let excess = 0;
            for (let v = 0; v < 256; v++) {
                if (hist[v] > limit) {
                    excess += hist[v] - limit;
                    hist[v] = limit;
                }
            }
            const share = Math.floor(excess / 256);
            let rest = excess - share * 256;
            for (let v = 0; v < 256; v++) {
                hist[v] += share;
                if (rest > 0) { hist[v]++; rest--; }
            }

            // Fonction de répartition -> LUT.
            const base = (ty * TILES + tx) * 256;
            let acc = 0;
            const scale = 255 / n;
            for (let v = 0; v < 256; v++) {
                acc += hist[v];
                luts[base + v] = Math.min(255, Math.round(acc * scale));
            }
        }
    }

    // Interpolation bilinéaire entre les LUT des 4 tuiles voisines.
    const lutAt = (tx, ty, v) => luts[((ty * TILES + tx) * 256) + v];
    for (let y = 0; y < h; y++) {
        const fy = (y + 0.5) / th - 0.5;
        let ty0 = Math.floor(fy);
        const wy = fy - ty0;
        ty0 = Math.max(0, Math.min(TILES - 1, ty0));
        const ty1 = Math.max(0, Math.min(TILES - 1, ty0 + 1));
        const row = y * w;
        for (let x = 0; x < w; x++) {
            const fx = (x + 0.5) / tw - 0.5;
            let tx0 = Math.floor(fx);
            const wx = fx - tx0;
            tx0 = Math.max(0, Math.min(TILES - 1, tx0));
            const tx1 = Math.max(0, Math.min(TILES - 1, tx0 + 1));
            const v = gray[row + x];
            const a = lutAt(tx0, ty0, v);
            const b = lutAt(tx1, ty0, v);
            const c = lutAt(tx0, ty1, v);
            const d = lutAt(tx1, ty1, v);
            const top = a + (b - a) * wx;
            const bot = c + (d - c) * wx;
            const out = (top + (bot - top) * wy) | 0;
            const i = (row + x) * 4;
            px[i] = px[i + 1] = px[i + 2] = out;
        }
    }

    ctx.putImageData(imageData, 0, 0);
    return new Promise((resolve, reject) => {
        cv.toBlob((blob) => {
            if (blob) resolve(URL.createObjectURL(blob));
            else reject(new Error('CLAHE : échec de la conversion'));
        }, 'image/png');
    });
}

/**
 * Table de correspondance 256 valeurs pour un filtre SVG `feFunc type="table"`.
 * Combine, dans cet ordre : fenêtrage (centre/largeur), gamma, négatif.
 * La chaîne renvoyée se pose telle quelle dans `tableValues`.
 */
export function windowLut({ center, width, gamma = 1, invert = false }) {
    const w = Math.max(1, width);
    const lo = center - w / 2;
    const out = new Array(256);
    for (let v = 0; v < 256; v++) {
        let t = (v - lo) / w;
        t = t < 0 ? 0 : t > 1 ? 1 : t;
        if (gamma !== 1) t = Math.pow(t, 1 / gamma);
        if (invert) t = 1 - t;
        out[v] = t.toFixed(4);
    }
    return out.join(' ');
}
