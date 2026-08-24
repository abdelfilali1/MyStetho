/**
 * Poste de travail céphalométrique de Doctivo.
 *
 * Les points sont TOUJOURS stockés en pixels de l'image naturelle. Le zoom, le
 * déplacement et le miroir horizontal ne sont que des transformations
 * d'affichage : la calibration et toutes les mesures restent valides quelle que
 * soit la façon dont le praticien regarde le cliché.
 */

import { ANALYSES, ANALYSIS_BY_ID, evaluate, fmt, fmtNorm, requiredLandmarks } from './analysis.js';
import { GROUP_COLOR, LANDMARK_BY_ID, LANDMARK_GROUPS, orderLandmarks } from './landmarks.js';
import { drawablePlanes, diagnosticSummary, PLANES, PLANE_GROUP_LABEL, TRACE_COLOR, TRACE_STRUCTURES } from './tracing.js';
import { detectLandmarks, modelAvailable } from './autodetect.js';
import { computeHistogram, computeClahe, windowLut } from './imaging.js';

const LOUPE_R = 78;
const SVG_NS = 'http://www.w3.org/2000/svg';

const CFG = JSON.parse(document.getElementById('ceph-data').textContent);

const DEFAULT_PLANES = {
    SN: true, FH: true, PP: true, MP: true, facial: true, NA: true, NB: true,
    APog: false, OP: true, U1: true, L1: true, Eline: true, Hline: false,
    softFacial: false, BaN: false, GoGn: false, Yaxis: false, ramus: false,
    PtGn: false, Nperp: false, PTV: false,
};

const SEVERITY_LABEL = {
    normal: 'Normal',
    mild: 'Écart léger',
    moderate: 'Écart modéré',
    severe: 'Écart sévère',
};

// ---------------------------------------------------------------------------
// État
// ---------------------------------------------------------------------------

/** Reglages d'image par defaut : fenetre pleine, aucun traitement. */
const NEUTRAL_ADJUST = {
    center: 128, width: 255, gamma: 1,
    invert: false, flipH: false, rotate: 0, sharpen: 0, clahe: false,
};

/**
 * Les anciens dossiers ont ete enregistres avec `brightness`/`contrast` en
 * pourcentage. On les convertit une fois pour toutes vers le couple
 * centre/largeur du fenetrage radiologique, qui exprime la meme droite :
 *   ancien : sortie = b·(c·(e − 0,5) + 0,5)
 *   nouveau : sortie = (e − C)/L + 0,5
 * L'egalite des pentes donne L = 1/(b·c), et celle des ordonnees le centre.
 */
function migrateAdjust(raw) {
    const a = Object.assign({}, NEUTRAL_ADJUST, raw || {});
    if (raw && raw.center === undefined && (raw.brightness !== undefined || raw.contrast !== undefined)) {
        const b = (raw.brightness ?? 100) / 100;
        const c = (raw.contrast ?? 100) / 100;
        if (b > 0.01 && c > 0.01) {
            const w = 1 / (b * c);
            const centre = (0.5 - 0.5 * b + 0.5 * b * c) / (b * c);
            a.width = Math.max(4, Math.min(510, Math.round(w * 255)));
            a.center = Math.max(0, Math.min(255, Math.round(centre * 255)));
        }
    }
    delete a.brightness;
    delete a.contrast;
    return a;
}

const S = {
    analysisId: CFG.case.analysis_id || 'steiner',
    landmarks: CFG.case.landmarks || {},
    aiSuggested: new Set(),     // points posés par l'IA, non encore validés par le praticien
    traces: CFG.case.traces || [],
    measures: CFG.case.measures || [],
    calibration: Object.assign({ mmPerPx: null, p1: null, p2: null, knownMm: 100 }, CFG.case.calibration || {}),
    adjust: migrateAdjust(CFG.case.adjust),
    subject: { sex: CFG.patient.sex, age: CFG.patient.age },

    mode: 'landmark',           // landmark | calibrate | trace | measure
    activeLandmark: null,
    traceStructure: 'soft-profile',
    measureType: 'dist',        // dist | angle
    measureDraft: null,         // points en cours de pose
    visiblePlanes: { ...DEFAULT_PLANES },
    showLandmarks: true,
    showLabels: true,
    showTraces: true,
    showScaleBar: true,
    showGrid: false,
    loupeFactor: 4,             // 0 = loupe désactivée
    handTool: false,            // outil Main : déplacement au bouton gauche
    windowing: null,            // fenêtrage en cours (clic droit glissé)

    histo: null,                // { hist, count, peak, percentile }
    claheUrl: null,             // URL blob de l'image égalisée (calculée à la demande)
    claheBusy: false,

    view: { zoom: 1, x: 0, y: 0 },
    image: null,                // { el, width, height }
    cursor: null,
    dragging: null,
    panning: null,
    stroke: null,
    spaceDown: false,
    dirty: false,
    saving: false,
};

// ---------------------------------------------------------------------------
// Éléments du DOM
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);
const stage = $('ceph-stage');
const svg = $('ceph-svg');
const gImage = $('ceph-g-image');
const gOverlay = $('ceph-g-overlay');
const gScreen = $('ceph-g-screen');
const gLoupe = $('ceph-g-loupe');
const imgEl = $('ceph-img');
const loupeImgEl = $('ceph-loupe-img');
const hudEl = $('ceph-hud');
const hintEl = $('ceph-hint');

// ---------------------------------------------------------------------------
// Chargement de la radiographie
// ---------------------------------------------------------------------------

function loadImage() {
    const probe = new Image();
    probe.onload = () => {
        S.image = { width: probe.naturalWidth, height: probe.naturalHeight };
        setImageSource(CFG.case.image_url);
        fitToStage();
        // L'histogramme est calcule une seule fois, hors ecran : il alimente le
        // bandeau radiologique ET les presets, qui se calent sur les centiles
        // reels du cliche plutot que sur des seuils fixes.
        try {
            S.histo = computeHistogram(probe);
        } catch (err) {
            console.warn('Histogramme indisponible :', err);
        }
        renderAll();
        renderHistogram();
    };
    probe.onerror = () => {
        hintEl.textContent = 'Impossible de charger la radiographie.';
    };
    probe.src = CFG.case.image_url;
}

/** Bascule les deux <image> (vue principale et loupe) sur une meme source. */
function setImageSource(url) {
    for (const node of [imgEl, loupeImgEl]) {
        node.setAttribute('href', url);
        node.setAttribute('width', S.image.width);
        node.setAttribute('height', S.image.height);
    }
}

/**
 * Egalisation locale (CLAHE). Le calcul pixel est fait UNE fois puis mis en
 * cache sous forme de blob : basculer d'un mode a l'autre ensuite ne coute
 * qu'un changement d'attribut `href`.
 */
async function setClahe(on) {
    S.adjust.clahe = on;
    $('ceph-clahe-btn').classList.toggle('is-active', on);
    if (!on) {
        setImageSource(CFG.case.image_url);
        renderViewer();
        return;
    }
    if (S.claheUrl) {
        setImageSource(S.claheUrl);
        renderViewer();
        return;
    }
    if (S.claheBusy) return;
    S.claheBusy = true;
    const btn = $('ceph-clahe-btn');
    const label = btn.textContent;
    btn.textContent = 'Calcul…';
    btn.disabled = true;
    try {
        // Laisse le navigateur peindre le libelle avant le calcul bloquant.
        await new Promise((r) => setTimeout(r, 30));
        S.claheUrl = await computeClahe(bitmap.complete && bitmap.naturalWidth ? bitmap : imgEl);
        claheBitmap = new Image();
        claheBitmap.src = S.claheUrl;
        setImageSource(S.claheUrl);
        renderViewer();
    } catch (err) {
        console.error(err);
        S.adjust.clahe = false;
        btn.classList.remove('is-active');
        window.showToast && window.showToast('Égalisation locale impossible sur ce cliché.', 'error');
    } finally {
        S.claheBusy = false;
        btn.textContent = label;
        btn.disabled = false;
    }
}

function fitToStage() {
    if (!S.image) return;
    const w = stage.clientWidth;
    const h = stage.clientHeight;
    const zoom = Math.min(w / S.image.width, h / S.image.height) * 0.94;
    S.view = {
        zoom,
        x: (w - S.image.width * zoom) / 2,
        y: (h - S.image.height * zoom) / 2,
    };
}

// ---------------------------------------------------------------------------
// Transformations de coordonnées
// ---------------------------------------------------------------------------

/**
 * Chaine de transformation de la vue, partagee par l'image et le calque
 * geometrique : deplacement, zoom, rotation autour du centre de l'image, puis
 * miroir. Ecrite une seule fois pour que tout reste coherent.
 */
function viewTransform(zoom, tx, ty) {
    const w = S.image ? S.image.width : 0;
    const h = S.image ? S.image.height : 0;
    const rot = S.adjust.rotate ? ` rotate(${S.adjust.rotate} ${w / 2} ${h / 2})` : '';
    const flip = S.adjust.flipH ? ` translate(${w} 0) scale(-1 1)` : '';
    return `translate(${tx} ${ty}) scale(${zoom})${rot}${flip}`;
}

/**
 * Ecran -> pixels de l'image. On inverse la matrice reelle du calque plutot que
 * de refaire le calcul a la main : rotation et miroir sont pris en compte sans
 * code supplementaire, et il n'y a qu'une seule source de verite.
 */
function toImage(clientX, clientY) {
    const m = gOverlay.getScreenCTM();
    if (!m) return { x: 0, y: 0 };
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const q = pt.matrixTransform(m.inverse());
    return { x: q.x, y: q.y };
}

/** Pixels de l'image -> coordonnees du SVG (= pixels de la zone d'affichage). */
function toScreen(p) {
    const m = gOverlay.getCTM();
    if (!m) return { x: 0, y: 0 };
    const pt = svg.createSVGPoint();
    pt.x = p.x;
    pt.y = p.y;
    return pt.matrixTransform(m);
}

function zoomBy(factor, center) {
    const zoom = Math.min(12, Math.max(0.1, S.view.zoom * factor));
    if (!center) {
        S.view.zoom = zoom;
    } else {
        // Garde le point sous le curseur fixe pendant le zoom.
        const k = zoom / S.view.zoom;
        S.view = {
            zoom,
            x: center.x - (center.x - S.view.x) * k,
            y: center.y - (center.y - S.view.y) * k,
        };
    }
    renderViewer();
}

// ---------------------------------------------------------------------------
// Actions sur l'état
// ---------------------------------------------------------------------------

function touch() {
    S.dirty = true;
    scheduleSave();
}

function placeLandmark(id, p) {
    S.landmarks[id] = p;
    S.aiSuggested.delete(id);   // posé/déplacé à la main = validé par le praticien
    touch();
}

function removeLandmark(id) {
    delete S.landmarks[id];
    S.aiSuggested.delete(id);
    touch();
    renderAll();
}

/** Passe au point suivant, dans l'ordre de digitalisation, qui n'est pas encore posé. */
function advanceLandmark() {
    const order = orderLandmarks(requiredLandmarks(S.analysisId));
    const start = S.activeLandmark ? order.indexOf(S.activeLandmark) + 1 : 0;
    for (let i = 0; i < order.length; i++) {
        const id = order[(start + i + order.length) % order.length];
        if (!S.landmarks[id]) {
            S.activeLandmark = id;
            return;
        }
    }
    S.activeLandmark = null;
}

function applyCalibration() {
    const { p1, p2, knownMm } = S.calibration;
    if (!p1 || !p2 || !(knownMm > 0)) {
        window.showToast && window.showToast('Posez les deux extrémités de la distance connue.', 'error');
        return;
    }
    const px = Math.hypot(p2.x - p1.x, p2.y - p1.y);
    if (px < 1) return;
    S.calibration.mmPerPx = knownMm / px;
    touch();
    renderAll();
    window.showToast && window.showToast('Image calibrée : les mesures en millimètres sont maintenant disponibles.', 'success');
}

function clearCalibration() {
    S.calibration = { mmPerPx: null, p1: null, p2: null, knownMm: S.calibration.knownMm || 100 };
    touch();
    renderAll();
}

function setMode(mode) {
    S.mode = mode;
    if (mode === 'landmark' && !S.activeLandmark) advanceLandmark();
    renderAll();
}

// ---------------------------------------------------------------------------
// Rendu — visionneuse (SVG)
// ---------------------------------------------------------------------------

function el(name, attrs, parent) {
    const n = document.createElementNS(SVG_NS, name);
    for (const k in attrs) {
        if (attrs[k] === null || attrs[k] === undefined) continue;
        n.setAttribute(k, attrs[k]);
    }
    if (parent) parent.appendChild(n);
    return n;
}

/**
 * Une seule table de 256 valeurs porte le fenetrage, le gamma et le negatif.
 * C'est ce qui distingue un vrai reglage radiologique d'un simple contraste :
 * la courbe de tons est arbitraire, et le materiel n'a pas a la recalculer.
 */
function updateFilter() {
    const lut = windowLut({
        center: S.adjust.center,
        width: S.adjust.width,
        gamma: S.adjust.gamma,
        invert: S.adjust.invert,
    });
    for (const node of document.querySelectorAll('.ceph-lut')) {
        node.setAttribute('tableValues', lut);
    }
    // Accentuation : melange lineaire entre l'image tonalisee et sa version
    // convoluee. A 0 %, on repointe l'image sur le filtre sans convolution pour
    // ne pas payer le cout du noyau a chaque redessin.
    const a = Math.max(0, Math.min(1, (S.adjust.sharpen || 0) / 100));
    const mix = $('ceph-sharp-mix');
    mix.setAttribute('k2', a.toFixed(3));
    mix.setAttribute('k3', (1 - a).toFixed(3));
    imgEl.setAttribute('filter', a > 0 ? 'url(#ceph-adj-sharp)' : 'url(#ceph-adj)');
}

function renderViewer() {
    if (!S.image) return;
    const { zoom, x, y } = S.view;
    const t = viewTransform(zoom, x, y);
    gImage.setAttribute('transform', t);
    gOverlay.setAttribute('transform', t);
    imgEl.style.imageRendering = zoom > 2 ? 'pixelated' : 'auto';
    updateFilter();
    renderOverlay();
    renderScreen();
    renderLoupe();
    renderHud();
}

function renderOverlay() {
    gOverlay.innerHTML = '';
    const zoom = S.view.zoom;
    const lw = 1 / zoom;
    const r = 4 / zoom;

    // Grille anatomique : dans le repère de l'image, donc elle suit la rotation
    // et donne un repère d'horizontalité une fois le cliché redressé.
    if (S.showGrid) {
        // Pas choisi pour rester lisible : on monte dans les pas ronds jusqu'a
        // ce que deux lignes soient separees d'au moins 14 px a l'ecran. Une
        // grille figee a 10 mm disparaitrait sur un cliche peu resolu et
        // deviendrait un aplat sur un cliche tres defini.
        const NICE_MM = [1, 2, 5, 10, 20, 50, 100];
        let step;
        if (S.calibration.mmPerPx) {
            const mm = NICE_MM.find((v) => (v / S.calibration.mmPerPx) * zoom >= 14) || 100;
            step = mm / S.calibration.mmPerPx;
        } else {
            step = Math.max(20, Math.pow(10, Math.ceil(Math.log10(14 / zoom))));
        }
        if (step * zoom >= 6) {
            for (let x = 0; x <= S.image.width; x += step) {
                el('line', {
                    x1: x, y1: 0, x2: x, y2: S.image.height,
                    stroke: '#38bdf8', 'stroke-width': lw * 0.6, opacity: 0.28,
                }, gOverlay);
            }
            for (let y = 0; y <= S.image.height; y += step) {
                el('line', {
                    x1: 0, y1: y, x2: S.image.width, y2: y,
                    stroke: '#38bdf8', 'stroke-width': lw * 0.6, opacity: 0.28,
                }, gOverlay);
            }
        }
    }

    // Plans de référence
    const planes = drawablePlanes(S.landmarks).filter((p) => S.visiblePlanes[p.id]);
    for (const p of planes) {
        el('line', {
            x1: p.a.x, y1: p.a.y, x2: p.b.x, y2: p.b.y,
            stroke: p.color, 'stroke-width': lw * 1.3,
            'stroke-dasharray': p.dash ? `${lw * 5} ${lw * 4}` : null,
            opacity: 0.85,
        }, gOverlay);
    }

    // Tracés anatomiques à main levée
    if (S.showTraces) {
        for (const t of S.traces) {
            el('polyline', {
                points: t.points.map((p) => `${p.x},${p.y}`).join(' '),
                fill: 'none',
                stroke: TRACE_COLOR[t.structure] || '#fff',
                'stroke-width': lw * 1.8,
                'stroke-linecap': 'round',
                'stroke-linejoin': 'round',
            }, gOverlay);
        }
    }
    if (S.stroke) {
        el('polyline', {
            points: S.stroke.map((p) => `${p.x},${p.y}`).join(' '),
            fill: 'none',
            stroke: TRACE_COLOR[S.traceStructure] || '#fff',
            'stroke-width': lw * 1.8,
            'stroke-linecap': 'round',
        }, gOverlay);
    }

    // Règle de calibration
    const c = S.calibration;
    if (c.p1) {
        if (c.p2) {
            el('line', {
                x1: c.p1.x, y1: c.p1.y, x2: c.p2.x, y2: c.p2.y,
                stroke: '#0891b2', 'stroke-width': lw * 1.6,
            }, gOverlay);
            el('circle', { cx: c.p2.x, cy: c.p2.y, r: r * 0.8, fill: '#0891b2' }, gOverlay);
        }
        el('circle', { cx: c.p1.x, cy: c.p1.y, r: r * 0.8, fill: '#0891b2' }, gOverlay);
    }

    // Mesures libres (persistantes) et mesure en cours de pose
    const drawMeasure = (m, live) => {
        const col = live ? '#fbbf24' : '#ca8a04';
        for (let i = 1; i < m.pts.length; i++) {
            el('line', {
                x1: m.pts[i - 1].x, y1: m.pts[i - 1].y, x2: m.pts[i].x, y2: m.pts[i].y,
                stroke: col, 'stroke-width': lw * 1.5,
                'stroke-dasharray': live ? `${lw * 4} ${lw * 3}` : null,
            }, gOverlay);
        }
        for (const p of m.pts) {
            el('circle', { cx: p.x, cy: p.y, r: r * 0.7, fill: col, stroke: '#fff', 'stroke-width': lw * 0.7 }, gOverlay);
        }
    };
    for (const m of S.measures) drawMeasure(m, false);
    if (S.measureDraft && S.measureDraft.pts.length) drawMeasure(S.measureDraft, true);

    // Points céphalométriques
    if (S.showLandmarks) {
        for (const id in S.landmarks) {
            const def = LANDMARK_BY_ID[id];
            if (!def) continue;
            const p = S.landmarks[id];
            const color = GROUP_COLOR[def.group];
            const suggested = S.aiSuggested.has(id);
            if (id === S.activeLandmark) {
                el('circle', { cx: p.x, cy: p.y, r: r * 2.6, fill: color, opacity: 0.18 }, gOverlay);
            }
            // Point suggéré par l'IA (non validé) : halo pointillé ambre autour du marqueur.
            if (suggested) {
                el('circle', {
                    cx: p.x, cy: p.y, r: r * 2, fill: 'none', stroke: '#f59e0b',
                    'stroke-width': lw * 1.1, 'stroke-dasharray': `${lw * 2.4} ${lw * 2}`, opacity: 0.95,
                }, gOverlay);
            }
            el('circle', {
                cx: p.x, cy: p.y, r, fill: suggested ? '#fff' : color,
                stroke: suggested ? '#f59e0b' : '#fff',
                'stroke-width': lw * (suggested ? 1.2 : 0.8), opacity: 0.98,
            }, gOverlay);
            el('circle', { cx: p.x, cy: p.y, r: r * 0.28, fill: suggested ? '#f59e0b' : '#fff', opacity: 0.9 }, gOverlay);
        }
    }
}

/**
 * Calque d'annotations, en coordonnees ecran et SANS transformation : les
 * etiquettes et la barre d'echelle restent droites et de taille constante,
 * meme cliche redresse, en miroir ou tres zoome. C'est le comportement d'une
 * console de radiologie — le texte n'est pas une partie de l'image.
 */
function renderScreen() {
    gScreen.innerHTML = '';
    if (!S.image) return;

    const stageW = stage.clientWidth;
    const stageH = stage.clientHeight;

    // Encombrement du cliche a l'ecran : on projette ses quatre coins, ce qui
    // reste valable quelles que soient la rotation et le miroir.
    const corners = [
        { x: 0, y: 0 }, { x: S.image.width, y: 0 },
        { x: S.image.width, y: S.image.height }, { x: 0, y: S.image.height },
    ].map(toScreen);
    const imgRight = Math.max(...corners.map((c) => c.x));

    // Marge libre a droite du cliche. En dessous d'une centaine de pixels il n'y
    // a plus la place d'une colonne : on revient a l'etiquette collee au point.
    const gutter = stageW - imgRight;
    const useGutter = gutter >= 100;
    const colX = Math.max(imgRight + 14, stageW - gutter + 14);

    // Etiquettes des points
    if (S.showLandmarks && S.showLabels) {
        const items = [];
        for (const id in S.landmarks) {
            const def = LANDMARK_BY_ID[id];
            if (!def) continue;
            items.push({ def, p: toScreen(S.landmarks[id]) });
        }

        if (useGutter && items.length) {
            // Le bandeau d'aide occupe le haut de la colonne : on demarre dessous.
            const hintH = hintEl.style.display === 'none' ? 0 : hintEl.offsetHeight + 12;
            const top = 10 + hintH;
            const GAP = 15;
            items.sort((a, b) => a.p.y - b.p.y);

            // Chaque etiquette part de la hauteur de son point puis est repoussee
            // vers le bas juste ce qu'il faut pour ne pas chevaucher la precedente.
            let y = top;
            for (const it of items) {
                y = Math.max(y, it.p.y);
                it.y = y;
                y += GAP;
            }
            // Si la pile deborde en bas, on la remonte d'un bloc.
            const bottom = stageH - 8;
            if (items[items.length - 1].y > bottom) {
                let yy = bottom;
                for (let i = items.length - 1; i >= 0; i--) {
                    yy = Math.min(yy, items[i].y);
                    items[i].y = yy;
                    yy -= GAP;
                }
            }

            // Le nom complet n'est ajoute que si la colonne est assez large pour
            // l'accueillir sans etre tronque.
            const withName = gutter >= 200;
            for (const it of items) {
                const color = GROUP_COLOR[it.def.group];
                el('line', {
                    x1: it.p.x + 7, y1: it.p.y, x2: colX - 5, y2: it.y - 4,
                    stroke: color, 'stroke-width': 1, opacity: 0.45,
                    'stroke-dasharray': '3 3', 'pointer-events': 'none',
                }, gScreen);
                el('circle', { cx: colX - 8, cy: it.y - 4, r: 2, fill: color, opacity: 0.8 }, gScreen);
                const t = el('text', {
                    x: colX, y: it.y,
                    'font-size': 11.5, fill: color, stroke: '#0b1220',
                    'stroke-width': 3, 'paint-order': 'stroke',
                    'font-weight': 700, 'pointer-events': 'none',
                }, gScreen);
                t.textContent = it.def.abbr;
                if (withName) {
                    const n = el('tspan', {
                        'font-size': 10.5, fill: '#94a3b8', 'font-weight': 500, dx: 6,
                    }, t);
                    n.textContent = it.def.name.replace(/\s*\(.*\)\s*$/, '');
                }
            }
        } else {
            // Pas de marge (cliche zoome) : on revient a l'etiquette au point.
            for (const it of items) {
                const t = el('text', {
                    x: it.p.x + 9, y: it.p.y - 7,
                    'font-size': 11.5, fill: GROUP_COLOR[it.def.group], stroke: '#0b1220',
                    'stroke-width': 3, 'paint-order': 'stroke',
                    'font-weight': 700, 'pointer-events': 'none',
                }, gScreen);
                t.textContent = it.def.abbr;
            }
        }
    }

    // Valeur de chaque mesure, posee au milieu du segment
    const labelMeasure = (m, live) => {
        const v = measureValue(m);
        if (!v) return;
        const anchor = m.type === 'angle' ? m.pts[1] : {
            x: (m.pts[0].x + m.pts[m.pts.length - 1].x) / 2,
            y: (m.pts[0].y + m.pts[m.pts.length - 1].y) / 2,
        };
        const s = toScreen(anchor);
        const t = el('text', {
            x: s.x + 10, y: s.y - 8, 'font-size': 12,
            fill: live ? '#fbbf24' : '#facc15', stroke: '#0b1220',
            'stroke-width': 3.4, 'paint-order': 'stroke',
            'font-weight': 700, 'pointer-events': 'none',
        }, gScreen);
        t.textContent = v;
    };
    for (const m of S.measures) labelMeasure(m, false);
    if (S.measureDraft && S.measureDraft.pts.length >= 2) labelMeasure(S.measureDraft, true);

    // Barre d'echelle : seulement quand le cliche est calibre, sinon elle
    // donnerait une fausse impression de mesure absolue.
    if (S.showScaleBar && S.calibration.mmPerPx) {
        const pxPerMm = S.view.zoom / S.calibration.mmPerPx;
        const target = 140;                              // longueur visee, en pixels ecran
        const NICE = [1, 2, 5, 10, 20, 50, 100, 200];
        let mm = NICE[NICE.length - 1];
        for (const n of NICE) { if (n * pxPerMm >= target * 0.6) { mm = n; break; } }
        const len = mm * pxPerMm;
        const x0 = 16;
        const y0 = stage.clientHeight - 22;
        el('rect', {
            x: x0 - 8, y: y0 - 20, width: len + 60, height: 30,
            rx: 6, fill: '#0b1220', opacity: 0.55,
        }, gScreen);
        el('line', { x1: x0, y1: y0, x2: x0 + len, y2: y0, stroke: '#e2e8f0', 'stroke-width': 2 }, gScreen);
        for (const x of [x0, x0 + len]) {
            el('line', { x1: x, y1: y0 - 5, x2: x, y2: y0 + 5, stroke: '#e2e8f0', 'stroke-width': 2 }, gScreen);
        }
        const t = el('text', {
            x: x0 + len + 8, y: y0 + 4, 'font-size': 12, fill: '#e2e8f0', 'font-weight': 700,
        }, gScreen);
        t.textContent = `${mm} mm`;
    }
}

/** Valeur formatee d'une mesure : millimetres si calibre, pixels sinon. */
function measureValue(m) {
    if (m.type === 'angle') {
        if (m.pts.length < 3) return null;
        const [a, b, c] = m.pts;
        const a1 = Math.atan2(a.y - b.y, a.x - b.x);
        const a2 = Math.atan2(c.y - b.y, c.x - b.x);
        let d = Math.abs((a1 - a2) * 180 / Math.PI);
        if (d > 180) d = 360 - d;
        return `${d.toFixed(1).replace('.', ',')}°`;
    }
    if (m.pts.length < 2) return null;
    const px = Math.hypot(m.pts[1].x - m.pts[0].x, m.pts[1].y - m.pts[0].y);
    return S.calibration.mmPerPx
        ? `${(px * S.calibration.mmPerPx).toFixed(2).replace('.', ',')} mm`
        : `${px.toFixed(1).replace('.', ',')} px`;
}

/**
 * La loupe redessine la radio à N × le zoom courant (×2, ×4 ou ×8), découpée en
 * disque, décalée du curseur. Placer un point au pixel près sur un cliché flou
 * est impossible sans elle.
 */
function renderLoupe() {
    if (!S.loupeFactor || !S.cursor || S.panning || S.windowing || !S.image) {
        gLoupe.style.display = 'none';
        return;
    }
    gLoupe.style.display = '';
    const Z = S.view.zoom * S.loupeFactor;

    // La loupe se place en haut a droite du curseur, et bascule des qu'elle
    // sortirait du cadre : elle ne doit jamais masquer ce qu'on vise.
    let cx = S.cursor.s.x + LOUPE_R + 26;
    let cy = S.cursor.s.y - LOUPE_R - 26;
    if (cx + LOUPE_R + 6 > stage.clientWidth) cx = S.cursor.s.x - LOUPE_R - 26;
    if (cy - LOUPE_R - 6 < 0) cy = S.cursor.s.y + LOUPE_R + 26;

    // Meme chaine de transformation que la vue principale, a ceci pres qu'on
    // choisit la translation pour amener le point vise au centre du disque.
    const q = imagePointAtZoom(S.cursor.i, Z);
    $('ceph-loupe-clipped').setAttribute('transform', '');
    $('ceph-loupe-clip-c').setAttribute('cx', cx);
    $('ceph-loupe-clip-c').setAttribute('cy', cy);
    $('ceph-loupe-scale').setAttribute('transform', viewTransform(Z, cx - q.x, cy - q.y));
    $('ceph-loupe-ring').setAttribute('cx', cx);
    $('ceph-loupe-ring').setAttribute('cy', cy);
    $('ceph-loupe-cross').setAttribute('transform', `translate(${cx} ${cy})`);
    const fac = $('ceph-loupe-badge');
    fac.setAttribute('x', cx);
    fac.setAttribute('y', cy + LOUPE_R + 14);
    fac.textContent = `×${S.loupeFactor}`;

    const pts = $('ceph-loupe-points');
    pts.innerHTML = '';
    for (const id in S.landmarks) {
        const p = S.landmarks[id];
        el('circle', {
            cx: p.x, cy: p.y, r: 3 / Z, fill: '#0284c7', stroke: '#fff',
            'stroke-width': 1 / Z, opacity: 0.95,
        }, pts);
    }
}

/**
 * Position d'un point image apres rotation, miroir et zoom, translation mise a
 * zero. Sert a caler la loupe sans dupliquer la matrice de la vue.
 */
function imagePointAtZoom(p, zoom) {
    const w = S.image.width;
    const h = S.image.height;
    let x = S.adjust.flipH ? w - p.x : p.x;
    let y = p.y;
    if (S.adjust.rotate) {
        const a = S.adjust.rotate * Math.PI / 180;
        const dx = x - w / 2;
        const dy = y - h / 2;
        x = dx * Math.cos(a) - dy * Math.sin(a) + w / 2;
        y = dx * Math.sin(a) + dy * Math.cos(a) + h / 2;
    }
    return { x: x * zoom, y: y * zoom };
}

function renderHud() {
    const bits = [];
    if (S.windowing) {
        bits.push('<b class="ceph-hud-ruler">Fenêtrage</b>');
    }
    // Lecture radiologique permanente : centre et largeur de fenetre, comme sur
    // une console. C'est ce qui permet de reproduire un reglage d'un cliche a
    // l'autre au lieu de le retrouver a tatons.
    bits.push(`F ${Math.round(S.adjust.center)} / ${Math.round(S.adjust.width)}`);
    if (S.adjust.rotate) bits.push(`${S.adjust.rotate.toFixed(1).replace('.', ',')}°`);
    if (S.cursor) bits.push(`${S.cursor.i.x.toFixed(0)}, ${S.cursor.i.y.toFixed(0)}`);
    bits.push(`${(S.view.zoom * 100).toFixed(0)} %`);
    bits.push(S.calibration.mmPerPx
        ? `<span class="ceph-ok">${S.calibration.mmPerPx.toFixed(4).replace('.', ',')} mm/px</span>`
        : '<span class="ceph-warn">non calibré</span>');
    hudEl.innerHTML = bits.join('<span class="ceph-hud-sep">·</span>');

    const def = S.activeLandmark ? LANDMARK_BY_ID[S.activeLandmark] : null;
    if (def && S.mode === 'landmark') {
        hintEl.innerHTML = `<span class="ceph-hint-name" style="color:${GROUP_COLOR[def.group]}">${def.name}</span>
            <span class="ceph-hint-abbr">${def.abbr}</span>
            <span class="ceph-hint-def">${def.definition}</span>`;
        hintEl.style.display = '';
    } else if (S.mode === 'calibrate') {
        hintEl.innerHTML = `<span class="ceph-hint-name">Calibration</span>
            <span class="ceph-hint-def">Cliquez les deux extrémités d’une distance connue (réglette radio-opaque, bille de calibrage), saisissez sa longueur réelle en mm, puis validez.</span>`;
        hintEl.style.display = '';
    } else if (S.mode === 'trace') {
        hintEl.innerHTML = `<span class="ceph-hint-name">Tracé anatomique</span>
            <span class="ceph-hint-def">Dessinez à main levée le contour sélectionné par-dessus la radiographie.</span>`;
        hintEl.style.display = '';
    } else if (S.mode === 'measure') {
        hintEl.innerHTML = `<span class="ceph-hint-name">Mesures</span>
            <span class="ceph-hint-def">${S.measureType === 'angle'
                ? 'Cliquez trois points : la valeur de l’angle est prise au deuxième (le sommet).'
                : 'Cliquez les deux extrémités de la distance à mesurer.'}
                Les mesures sont enregistrées avec le dossier.</span>`;
        hintEl.style.display = '';
    } else {
        hintEl.style.display = 'none';
    }
}

// ---------------------------------------------------------------------------
// Rendu — panneaux
// ---------------------------------------------------------------------------

function renderAnalysisSelect() {
    const sel = $('ceph-analysis');
    if (sel.options.length === 0) {
        for (const a of ANALYSES) {
            const o = document.createElement('option');
            o.value = a.id;
            o.textContent = a.name;
            sel.appendChild(o);
        }
    }
    sel.value = S.analysisId;
    const a = ANALYSIS_BY_ID[S.analysisId];
    $('ceph-analysis-sub').textContent = a.subtitle + (a.citation ? ' · ' + a.citation : '');
}

function renderLandmarkPanel() {
    const needed = orderLandmarks(requiredLandmarks(S.analysisId));
    const placed = needed.filter((id) => S.landmarks[id]).length;
    $('ceph-progress-count').textContent = `${placed} / ${needed.length}`;
    $('ceph-progress-bar').style.width = needed.length ? `${(placed / needed.length) * 100}%` : '0%';

    const box = $('ceph-landmark-list');
    box.innerHTML = '';
    for (const g of LANDMARK_GROUPS) {
        const ids = needed.filter((id) => LANDMARK_BY_ID[id].group === g.id);
        if (!ids.length) continue;
        const h = document.createElement('div');
        h.className = 'ceph-lm-group';
        h.innerHTML = `<span class="ceph-dot" style="background:${g.color}"></span>${g.label}`;
        box.appendChild(h);

        for (const id of ids) {
            const def = LANDMARK_BY_ID[id];
            const done = !!S.landmarks[id];
            const suggested = S.aiSuggested.has(id);
            const row = document.createElement('button');
            row.type = 'button';
            row.className = 'ceph-lm' + (done ? ' is-done' : '') + (suggested ? ' is-ai' : '')
                + (id === S.activeLandmark ? ' is-active' : '');
            row.title = suggested ? 'Suggéré par l’IA — à vérifier' : def.definition;
            const state = suggested ? '<span class="ceph-lm-ai">IA</span>' : (done ? '✓' : '○');
            row.innerHTML = `
                <span class="ceph-lm-abbr" style="color:${g.color}">${def.abbr}</span>
                <span class="ceph-lm-name">${def.name}</span>
                <span class="ceph-lm-state">${state}</span>`;
            row.addEventListener('click', () => {
                S.activeLandmark = id;
                S.mode = 'landmark';
                renderAll();
            });
            box.appendChild(row);
        }
    }
}

function severityClass(sev) {
    return 'ceph-sev-' + sev;
}

/** Résultats de l'analyse courante, ligne à ligne, tels qu'affichés ET exportés. */
function currentResults() {
    const a = ANALYSIS_BY_ID[S.analysisId];
    return evaluate(S.landmarks, S.calibration.mmPerPx, S.subject, a.measurements, a.id);
}

function renderResults() {
    const rows = currentResults();
    const box = $('ceph-results');
    box.innerHTML = '';

    for (const r of rows) {
        const tr = document.createElement('div');
        tr.className = 'ceph-res';

        let valueHtml;
        if (r.value !== null) {
            valueHtml = `<span class="ceph-res-value ${severityClass(r.severity)}">${fmt(r.value, r.def.unit)}</span>`;
        } else if (r.needsCalibration) {
            valueHtml = '<span class="ceph-res-missing">calibration requise</span>';
        } else {
            const miss = r.missing.map((m) => (LANDMARK_BY_ID[m] ? LANDMARK_BY_ID[m].abbr : m)).join(', ');
            valueHtml = `<span class="ceph-res-missing">manque : ${miss}</span>`;
        }

        const zHtml = r.z !== null && isFinite(r.z)
            ? `<span class="ceph-res-z ${severityClass(r.severity)}">${(r.z > 0 ? '+' : '') + r.z.toFixed(1).replace('.', ',')} ET</span>`
            : '';

        tr.innerHTML = `
            <div class="ceph-res-head">
                <span class="ceph-res-name" title="${r.def.description.replace(/"/g, '&quot;')}">${r.def.name}</span>
                ${valueHtml}
            </div>
            <div class="ceph-res-sub">
                <span class="ceph-res-norm">Norme ${fmtNorm(r.norm, r.def.unit)}</span>
                ${zHtml}
            </div>
            ${r.note ? `<div class="ceph-res-note ${severityClass(r.severity)}">${r.note}</div>` : ''}
            ${r.def.caveat && r.value !== null ? `<div class="ceph-res-caveat">⚠ ${r.def.caveat}</div>` : ''}`;
        box.appendChild(tr);
    }

    renderSummary();
}

function renderSummary() {
    const lines = diagnosticSummary(S.landmarks, S.calibration.mmPerPx, S.subject);
    const box = $('ceph-summary');
    if (!lines.length) {
        box.innerHTML = '<p class="ceph-empty">Posez les points squelettiques (S, N, A, B…) pour obtenir la synthèse diagnostique.</p>';
        return;
    }
    box.innerHTML = lines.map((l) => `
        <div class="ceph-sum ${severityClass(l.severity)}">
            <div class="ceph-sum-label">${l.label}</div>
            <div class="ceph-sum-finding">${l.finding}</div>
            <div class="ceph-sum-detail">${l.detail}</div>
        </div>`).join('');
}

function renderPlanesPanel() {
    const box = $('ceph-planes');
    if (box.dataset.built) {
        box.querySelectorAll('input[data-plane]').forEach((i) => {
            i.checked = !!S.visiblePlanes[i.dataset.plane];
        });
        return;
    }
    box.dataset.built = '1';
    const groups = ['skeletal', 'dental', 'soft', 'constructed'];
    for (const g of groups) {
        const h = document.createElement('div');
        h.className = 'ceph-lm-group';
        h.textContent = PLANE_GROUP_LABEL[g];
        box.appendChild(h);
        for (const p of PLANES.filter((x) => x.group === g)) {
            const lab = document.createElement('label');
            lab.className = 'ceph-check';
            lab.innerHTML = `<input type="checkbox" data-plane="${p.id}" ${S.visiblePlanes[p.id] ? 'checked' : ''}>
                <span class="ceph-plane-swatch" style="background:${p.color}"></span>${p.label}`;
            lab.querySelector('input').addEventListener('change', (e) => {
                S.visiblePlanes[p.id] = e.target.checked;
                renderViewer();
            });
            box.appendChild(lab);
        }
    }
}

function renderTraceSelect() {
    const sel = $('ceph-trace-structure');
    if (sel.options.length === 0) {
        for (const t of TRACE_STRUCTURES) {
            const o = document.createElement('option');
            o.value = t.id;
            o.textContent = t.label;
            sel.appendChild(o);
        }
    }
    sel.value = S.traceStructure;
}

function renderTools() {
    document.querySelectorAll('[data-mode]').forEach((b) => {
        b.classList.toggle('is-active', b.dataset.mode === S.mode);
    });
    $('ceph-calib-panel').style.display = S.mode === 'calibrate' ? '' : 'none';
    $('ceph-trace-panel').style.display = S.mode === 'trace' ? '' : 'none';
    $('ceph-measure-panel').style.display = S.mode === 'measure' ? '' : 'none';
    document.querySelectorAll('[data-measure]').forEach((b) => {
        b.classList.toggle('is-active', b.dataset.measure === S.measureType);
    });
    $('ceph-measure-hint').textContent = S.measureType === 'angle'
        ? 'Trois clics : première branche, sommet, seconde branche.'
        : 'Deux clics : les extrémités de la distance.';
    renderMeasureList();
    $('ceph-calib-mm').value = S.calibration.knownMm;
    $('ceph-calib-state').textContent = S.calibration.mmPerPx
        ? `Calibré : ${S.calibration.mmPerPx.toFixed(4).replace('.', ',')} mm/px`
        : 'Non calibré — les mesures en mm sont retenues.';
    $('ceph-calib-state').className = S.calibration.mmPerPx ? 'ceph-calib-state ceph-ok' : 'ceph-calib-state ceph-warn';
}

function renderMeasureList() {
    const box = $('ceph-measure-list');
    if (!S.measures.length) {
        box.innerHTML = '<div class="ceph-measure-empty">Aucune mesure.</div>';
        return;
    }
    box.innerHTML = S.measures.map((m, i) => `
        <div class="ceph-measure-row">
            <span class="ceph-measure-kind">${m.type === 'angle' ? '∠' : '↔'}</span>
            <span class="ceph-measure-val">${measureValue(m) || '—'}</span>
            <button type="button" class="ceph-measure-del" data-i="${i}" title="Supprimer">×</button>
        </div>`).join('');
    box.querySelectorAll('.ceph-measure-del').forEach((b) => {
        b.onclick = () => {
            S.measures.splice(parseInt(b.dataset.i, 10), 1);
            touch();
            renderAll();
        };
    });
}

function renderAll() {
    renderAnalysisSelect();
    renderLandmarkPanel();
    renderResults();
    renderPlanesPanel();
    renderTraceSelect();
    renderTools();
    renderViewer();
}

// ---------------------------------------------------------------------------
// Interactions pointeur
// ---------------------------------------------------------------------------

function hitTest(p) {
    const tol = 9 / S.view.zoom;
    let best = null;
    for (const id in S.landmarks) {
        const lp = S.landmarks[id];
        const d = Math.hypot(lp.x - p.x, lp.y - p.y);
        if (d <= tol && (!best || d < best.d)) best = { id, d };
    }
    return best ? best.id : null;
}

stage.addEventListener('wheel', (e) => {
    e.preventDefault();
    const r = stage.getBoundingClientRect();
    zoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12, { x: e.clientX - r.left, y: e.clientY - r.top });
}, { passive: false });

/** Les panneaux flottants sont DANS la visionneuse : un clic sur « Valider la
 *  calibration » ne doit pas poser un point sur le cliché en même temps. */
const onPanel = (e) => !!(e.target.closest && e.target.closest('.ceph-float'));

// Le clic droit sert au fenetrage : on neutralise le menu contextuel sur le
// cliche, comme sur toute console d'imagerie.
stage.addEventListener('contextmenu', (e) => {
    if (!onPanel(e)) e.preventDefault();
});

stage.addEventListener('pointerdown', (e) => {
    if (!S.image || onPanel(e)) return;
    stage.setPointerCapture(e.pointerId);

    // Bouton du milieu, barre d'espace ou outil Main : déplacement, quel que
    // soit l'outil de travail sélectionné.
    if (e.button === 1 || S.spaceDown || (S.handTool && e.button === 0)) {
        S.panning = { x: e.clientX - S.view.x, y: e.clientY - S.view.y };
        return;
    }

    // Bouton droit : FENETRAGE. Horizontal = largeur de fenetre (contraste),
    // vertical = centre (luminosite). C'est le geste universel des PACS, et il
    // se fait sur l'image elle-meme plutot que dans un panneau lateral.
    if (e.button === 2) {
        S.windowing = {
            x: e.clientX, y: e.clientY,
            center: S.adjust.center, width: S.adjust.width,
        };
        return;
    }
    if (e.button !== 0) return;

    const p = toImage(e.clientX, e.clientY);

    if (S.mode === 'landmark') {
        const hit = hitTest(p);
        if (hit) {
            S.activeLandmark = hit;
            S.dragging = hit;
            renderAll();
            return;
        }
        if (S.activeLandmark) {
            placeLandmark(S.activeLandmark, p);
            S.dragging = S.activeLandmark;
            renderAll();
        }
        return;
    }

    if (S.mode === 'calibrate') {
        const c = S.calibration;
        if (!c.p1 || (c.p1 && c.p2)) {
            c.p1 = p;
            c.p2 = null;
        } else {
            c.p2 = p;
        }
        touch();
        renderViewer();
        return;
    }

    if (S.mode === 'trace') {
        S.stroke = [p];
        return;
    }

    if (S.mode === 'measure') {
        const need = S.measureType === 'angle' ? 3 : 2;
        if (!S.measureDraft) S.measureDraft = { type: S.measureType, pts: [] };
        S.measureDraft.pts.push(p);
        if (S.measureDraft.pts.length >= need) {
            S.measures.push({
                id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
                type: S.measureDraft.type,
                pts: S.measureDraft.pts,
            });
            S.measureDraft = null;
            touch();
            renderAll();
        } else {
            renderViewer();
        }
    }
});

stage.addEventListener('pointermove', (e) => {
    if (!S.image) return;
    if (onPanel(e) && !S.dragging && !S.panning && !S.stroke) {
        S.cursor = null;   // pas de loupe ni de curseur pendant qu'on règle un panneau
        renderViewer();
        return;
    }
    const r = stage.getBoundingClientRect();
    const p = toImage(e.clientX, e.clientY);
    S.cursor = { s: { x: e.clientX - r.left, y: e.clientY - r.top }, i: p };

    if (S.panning) {
        S.view.x = e.clientX - S.panning.x;
        S.view.y = e.clientY - S.panning.y;
        renderViewer();
        return;
    }
    if (S.windowing) {
        // Sensibilite proportionnelle a la largeur courante : le reglage reste
        // fin quand la fenetre est etroite, rapide quand elle est large.
        const k = Math.max(0.35, S.windowing.width / 255);
        S.adjust.width = Math.max(4, Math.min(510,
            Math.round(S.windowing.width + (e.clientX - S.windowing.x) * k)));
        S.adjust.center = Math.max(0, Math.min(255,
            Math.round(S.windowing.center + (e.clientY - S.windowing.y) * k)));
        syncWindowInputs();
        renderViewer();
        renderHistogram();
        return;
    }
    // Le brouillon de mesure suit le curseur tant que le dernier point n'est pas posé.
    if (S.mode === 'measure' && S.measureDraft && S.measureDraft.pts.length) {
        const need = S.measureType === 'angle' ? 3 : 2;
        const pts = S.measureDraft.pts.slice(0, need - 1);
        S.measureDraft = { type: S.measureDraft.type, pts: [...pts, p] };
        renderViewer();
        return;
    }
    if (S.dragging) {
        S.landmarks[S.dragging] = p;
        S.aiSuggested.delete(S.dragging);   // déplacé à la main = validé
        touch();
        renderViewer();
        return;
    }
    if (S.stroke) {
        // Allège le tracé : un sommet n'est enregistré qu'après un vrai déplacement.
        const last = S.stroke[S.stroke.length - 1];
        if (Math.hypot(p.x - last.x, p.y - last.y) * S.view.zoom > 2) S.stroke.push(p);
        renderViewer();
        return;
    }
    renderViewer();
});

function endPointer() {
    if (S.stroke && S.stroke.length > 1) {
        S.traces.push({
            id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
            structure: S.traceStructure,
            points: S.stroke,
        });
        touch();
    }
    S.stroke = null;
    S.panning = null;
    if (S.windowing) {
        S.windowing = null;
        touch();
        renderViewer();
    }
    if (S.dragging && S.mode === 'landmark') {
        // Poser un point fait avancer la séquence guidée au suivant non posé.
        if (S.activeLandmark === S.dragging) advanceLandmark();
    }
    const wasDragging = S.dragging;
    S.dragging = null;
    if (wasDragging) renderAll();
}

stage.addEventListener('pointerup', endPointer);
stage.addEventListener('pointercancel', endPointer);
stage.addEventListener('pointerleave', () => {
    S.cursor = null;
    renderViewer();
});

// ---------------------------------------------------------------------------
// Clavier
// ---------------------------------------------------------------------------

window.addEventListener('keydown', (e) => {
    const tag = e.target && e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    if (e.code === 'Space') {
        e.preventDefault();
        S.spaceDown = true;
        stage.classList.add('is-panning');
        return;
    }
    const sel = S.activeLandmark;
    if (sel && S.landmarks[sel]) {
        // Les flèches déplacent d'un pixel image, ou de 0,2 px avec Maj pour un
        // réglage sub-pixel à fort grossissement.
        const step = e.shiftKey ? 0.2 : 1;
        const map = {
            ArrowLeft: [-step, 0], ArrowRight: [step, 0],
            ArrowUp: [0, -step], ArrowDown: [0, step],
        };
        const d = map[e.key];
        if (d) {
            e.preventDefault();
            // Les fleches doivent decaler le point tel qu'on le VOIT : on annule
            // donc le miroir et la rotation d'affichage avant de l'appliquer.
            const flip = S.adjust.flipH ? -1 : 1;
            const a = -(S.adjust.rotate || 0) * Math.PI / 180;
            const dx = d[0] * flip;
            const dy = d[1];
            const rx = dx * Math.cos(a) - dy * Math.sin(a);
            const ry = dx * Math.sin(a) + dy * Math.cos(a);
            const p = S.landmarks[sel];
            S.landmarks[sel] = { x: p.x + rx, y: p.y + ry };
            S.aiSuggested.delete(sel);   // ajusté au clavier = validé
            touch();
            renderAll();
            return;
        }
        if (e.key === 'Delete' || e.key === 'Backspace') {
            e.preventDefault();
            removeLandmark(sel);
            return;
        }
    }
    if (e.key === '+' || e.key === '=') zoomBy(1.2);
    if (e.key === '-' || e.key === '_') zoomBy(1 / 1.2);
    if (e.key === '0') { fitToStage(); renderViewer(); }

    // Raccourcis de la visionneuse. Volontairement des touches simples : le
    // praticien a une main sur la souris et l'autre sur le clavier.
    const MODES = { 1: 'landmark', 2: 'calibrate', 3: 'trace', 4: 'measure' };
    if (MODES[e.key]) { setMode(MODES[e.key]); return; }
    const k = e.key.toLowerCase();
    if (k === 'n') { $('ceph-invert-btn').click(); return; }
    if (k === 'm') { $('ceph-flip-btn').click(); return; }
    if (k === 'r') { $('ceph-rotate-btn').click(); return; }
    if (k === 'c') { setClahe(!S.adjust.clahe); return; }
    if (k === 'f') { toggleFullscreen(); return; }
    if (k === 'h') { $('ceph-hand').click(); return; }
    if (k === 'l') {
        // ×2 → ×4 → ×8 → arrêt, en boucle.
        const cycle = [2, 4, 8, 0];
        S.loupeFactor = cycle[(cycle.indexOf(S.loupeFactor) + 1) % cycle.length];
        $('ceph-loupe-factor').value = String(S.loupeFactor);
        renderViewer();
        return;
    }
    if (e.key === '?') { $('ceph-help-btn').click(); return; }
    if (e.key === 'Escape') {
        $('ceph-help').style.display = 'none';
        if (S.measureDraft) { S.measureDraft = null; renderViewer(); }
    }
});

window.addEventListener('keyup', (e) => {
    if (e.code === 'Space') {
        S.spaceDown = false;
        stage.classList.remove('is-panning');
    }
});

window.addEventListener('resize', () => renderViewer());

// ---------------------------------------------------------------------------
// Barre d'outils
// ---------------------------------------------------------------------------

document.querySelectorAll('[data-mode]').forEach((b) => {
    b.addEventListener('click', () => setMode(b.dataset.mode));
});

$('ceph-analysis').addEventListener('change', (e) => {
    S.analysisId = e.target.value;
    S.activeLandmark = null;
    advanceLandmark();
    touch();
    renderAll();
});

$('ceph-trace-structure').addEventListener('change', (e) => {
    S.traceStructure = e.target.value;
});

$('ceph-trace-clear').addEventListener('click', () => {
    S.traces = S.traces.filter((t) => t.structure !== S.traceStructure);
    touch();
    renderViewer();
});

$('ceph-trace-clear-all').addEventListener('click', () => {
    if (!S.traces.length) return;
    if (!confirm('Effacer tous les tracés anatomiques ?')) return;
    S.traces = [];
    touch();
    renderViewer();
});

$('ceph-calib-mm').addEventListener('input', (e) => {
    S.calibration.knownMm = parseFloat(e.target.value) || 0;
});
$('ceph-calib-apply').addEventListener('click', applyCalibration);
$('ceph-calib-clear').addEventListener('click', clearCalibration);

// Réglages image
// ---------------------------------------------------------------------------
// Bandeau radiologique : fenetrage, histogramme, presets
// ---------------------------------------------------------------------------

/** Recopie l'etat du fenetrage dans les curseurs et les lectures chiffrees. */
function syncWindowInputs() {
    $('ceph-wcenter').value = S.adjust.center;
    $('ceph-wwidth').value = S.adjust.width;
    $('ceph-gamma').value = S.adjust.gamma;
    $('ceph-sharpen').value = S.adjust.sharpen;
    $('ceph-wc-val').textContent = Math.round(S.adjust.center);
    $('ceph-ww-val').textContent = Math.round(S.adjust.width);
    $('ceph-gamma-val').textContent = S.adjust.gamma.toFixed(2).replace('.', ',');
    $('ceph-sharp-val').textContent = `${Math.round(S.adjust.sharpen)} %`;
    $('ceph-rotate-range').value = S.adjust.rotate;
    $('ceph-rotate-val').textContent = `${S.adjust.rotate.toFixed(1).replace('.', ',')}°`;
    $('ceph-winread').textContent = `Fenêtre ${Math.round(S.adjust.center - S.adjust.width / 2)}`
        + ` – ${Math.round(S.adjust.center + S.adjust.width / 2)}`;
}

/**
 * Histogramme des niveaux de gris, en echelle racine pour que les classes
 * peu peuplees (les tissus mous, justement) restent visibles a cote du pic
 * du fond. Les deux poignees materialisent les bornes de la fenetre.
 */
function renderHistogram() {
    const cv = $('ceph-histo');
    const ctx = cv.getContext('2d');
    const W = cv.width;
    const H = cv.height;
    ctx.clearRect(0, 0, W, H);
    if (!S.histo) return;

    const { hist, peak } = S.histo;
    const scale = peak > 0 ? H / Math.sqrt(peak) : 0;
    ctx.fillStyle = '#334155';
    for (let v = 0; v < 256; v++) {
        const h = Math.sqrt(hist[v]) * scale;
        ctx.fillRect((v / 256) * W, H - h, W / 256 + 0.5, h);
    }

    // Courbe de tons appliquee, superposee : le praticien voit exactement ce
    // que la fenetre fait des niveaux d'origine.
    const lo = S.adjust.center - S.adjust.width / 2;
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    for (let v = 0; v < 256; v++) {
        let t = (v - lo) / Math.max(1, S.adjust.width);
        t = t < 0 ? 0 : t > 1 ? 1 : t;
        if (S.adjust.gamma !== 1) t = Math.pow(t, 1 / S.adjust.gamma);
        if (S.adjust.invert) t = 1 - t;
        const x = (v / 256) * W;
        const y = H - t * H;
        if (v === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Zone hors fenetre, grisee.
    ctx.fillStyle = 'rgba(11,18,32,.55)';
    const xLo = Math.max(0, (lo / 256) * W);
    const xHi = Math.min(W, ((lo + S.adjust.width) / 256) * W);
    ctx.fillRect(0, 0, xLo, H);
    ctx.fillRect(xHi, 0, W - xHi, H);

    const wrap = $('ceph-histo-wrap');
    const px = wrap.clientWidth || W;
    $('ceph-histo-lo').style.left = `${(lo / 256) * px}px`;
    $('ceph-histo-hi').style.left = `${((lo + S.adjust.width) / 256) * px}px`;
}

/** Applique un couple (borne basse, borne haute) exprime en niveaux 0–255. */
function setWindowBounds(lo, hi) {
    if (hi - lo < 4) hi = lo + 4;
    S.adjust.center = Math.max(0, Math.min(255, Math.round((lo + hi) / 2)));
    S.adjust.width = Math.max(4, Math.min(510, Math.round(hi - lo)));
    syncWindowInputs();
    renderViewer();
    renderHistogram();
}

// Poignees de l'histogramme
for (const [id, which] of [['ceph-histo-lo', 'lo'], ['ceph-histo-hi', 'hi']]) {
    $(id).addEventListener('pointerdown', (e) => {
        e.preventDefault();
        const wrap = $('ceph-histo-wrap');
        const move = (ev) => {
            const r = wrap.getBoundingClientRect();
            const v = Math.max(0, Math.min(255, ((ev.clientX - r.left) / r.width) * 256));
            let lo = S.adjust.center - S.adjust.width / 2;
            let hi = S.adjust.center + S.adjust.width / 2;
            if (which === 'lo') lo = v; else hi = v;
            if (lo > hi) { const t = lo; lo = hi; hi = t; }
            setWindowBounds(lo, hi);
        };
        const up = () => {
            window.removeEventListener('pointermove', move);
            window.removeEventListener('pointerup', up);
            touch();
        };
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
    });
}

/**
 * Presets d'affichage. Ils sont calcules sur les CENTILES du cliche courant :
 * un seuil fixe ne vaudrait que pour un appareil donne, alors que les centiles
 * s'adaptent a n'importe quelle teleradiographie.
 */
function applyPreset(name) {
    const pc = S.histo ? S.histo.percentile : (p) => p * 2.55;
    let lo = 0;
    let hi = 255;
    let gamma = 1;
    let sharpen = 0;
    if (name === 'original') {
        lo = 0; hi = 255; gamma = 1; sharpen = 0;
    } else if (name === 'bone') {
        // Structures denses : on ouvre la fenetre sur la moitie haute et on
        // accentue les bords pour lire les corticales.
        lo = pc(55); hi = pc(99.5); gamma = 1; sharpen = 45;
    } else if (name === 'soft') {
        // Profil cutane : tres peu dense, il vit dans le bas de l'histogramme.
        lo = pc(2); hi = pc(62); gamma = 1.35; sharpen = 15;
    } else if (name === 'teeth') {
        lo = pc(80); hi = pc(99.9); gamma = 0.9; sharpen = 60;
    }
    S.adjust.gamma = gamma;
    S.adjust.sharpen = sharpen;
    document.querySelectorAll('.ceph-preset[data-preset]').forEach((b) => {
        b.classList.toggle('is-active', b.dataset.preset === name);
    });
    setWindowBounds(lo, hi);
    touch();
}

document.querySelectorAll('.ceph-preset[data-preset]').forEach((b) => {
    b.addEventListener('click', () => applyPreset(b.dataset.preset));
});
$('ceph-clahe-btn').addEventListener('click', () => setClahe(!S.adjust.clahe));

// Curseurs de la colonne de droite
$('ceph-wcenter').addEventListener('input', (e) => {
    S.adjust.center = parseFloat(e.target.value);
    syncWindowInputs(); renderViewer(); renderHistogram(); touch();
});
$('ceph-wwidth').addEventListener('input', (e) => {
    S.adjust.width = parseFloat(e.target.value);
    syncWindowInputs(); renderViewer(); renderHistogram(); touch();
});
$('ceph-gamma').addEventListener('input', (e) => {
    S.adjust.gamma = parseFloat(e.target.value);
    syncWindowInputs(); renderViewer(); renderHistogram(); touch();
});
$('ceph-sharpen').addEventListener('input', (e) => {
    S.adjust.sharpen = parseFloat(e.target.value);
    syncWindowInputs(); renderViewer(); touch();
});

$('ceph-invert-btn').addEventListener('click', () => {
    S.adjust.invert = !S.adjust.invert;
    $('ceph-invert-btn').classList.toggle('is-active', S.adjust.invert);
    touch();
    renderViewer();
    renderHistogram();
});
$('ceph-flip-btn').addEventListener('click', () => {
    S.adjust.flipH = !S.adjust.flipH;
    $('ceph-flip-btn').classList.toggle('is-active', S.adjust.flipH);
    touch();
    renderViewer();
});
$('ceph-reset-adjust').addEventListener('click', () => {
    const wasClahe = S.adjust.clahe;
    S.adjust = Object.assign({}, NEUTRAL_ADJUST);
    document.querySelectorAll('.ceph-preset[data-preset]').forEach((b) => b.classList.remove('is-active'));
    $('ceph-invert-btn').classList.remove('is-active');
    $('ceph-flip-btn').classList.remove('is-active');
    if (wasClahe) setClahe(false);
    syncWindowInputs();
    touch();
    renderViewer();
    renderHistogram();
});

// ---------------------------------------------------------------------------
// Redressement du cliche
// ---------------------------------------------------------------------------

$('ceph-rotate-btn').addEventListener('click', () => {
    const p = $('ceph-rotate-panel');
    const open = p.style.display === 'none';
    p.style.display = open ? '' : 'none';
    $('ceph-rotate-btn').classList.toggle('is-active', open);
});
$('ceph-rotate-range').addEventListener('input', (e) => {
    S.adjust.rotate = parseFloat(e.target.value) || 0;
    syncWindowInputs();
    touch();
    renderViewer();
});
$('ceph-rotate-reset').addEventListener('click', () => {
    S.adjust.rotate = 0;
    syncWindowInputs();
    touch();
    renderViewer();
});
$('ceph-rotate-fh').addEventListener('click', () => {
    // Le plan de Francfort (Porion–Orbitale) est la reference horizontale de la
    // teleradiographie de profil : l'amener a l'horizontale rend la lecture des
    // rapports verticaux immediate.
    const po = S.landmarks.Po;
    const or = S.landmarks.Or;
    const state = $('ceph-rotate-state');
    if (!po || !or) {
        state.textContent = 'Posez d’abord Porion (Po) et Orbitale (Or).';
        state.className = 'ceph-calib-state ceph-warn';
        return;
    }
    const deg = Math.atan2(or.y - po.y, or.x - po.x) * 180 / Math.PI;
    // On borne au domaine du curseur : au-dela, c'est le cliche qui est en cause.
    S.adjust.rotate = Math.max(-30, Math.min(30, -deg));
    state.textContent = `Francfort ramené à l’horizontale (${S.adjust.rotate.toFixed(1).replace('.', ',')}°).`;
    state.className = 'ceph-calib-state ceph-ok';
    syncWindowInputs();
    touch();
    renderViewer();
});

// ---------------------------------------------------------------------------
// Plein ecran et aide
// ---------------------------------------------------------------------------

function toggleFullscreen() {
    const box = $('ceph-viewer');
    if (document.fullscreenElement) document.exitFullscreen();
    else if (box.requestFullscreen) box.requestFullscreen().catch(() => {});
}
$('ceph-fullscreen').addEventListener('click', toggleFullscreen);
document.addEventListener('fullscreenchange', () => {
    $('ceph-viewer').classList.toggle('is-fullscreen', !!document.fullscreenElement);
    // La zone d'affichage change de taille : on recadre et on repositionne la
    // barre d'echelle, qui est ancree en bas de la scene.
    setTimeout(() => { fitToStage(); renderViewer(); renderHistogram(); }, 60);
});

const helpBox = $('ceph-help');
$('ceph-help-btn').addEventListener('click', () => {
    helpBox.style.display = helpBox.style.display === 'none' ? '' : 'none';
});
$('ceph-help-close').addEventListener('click', () => { helpBox.style.display = 'none'; });

// Affichage
$('ceph-toggle-landmarks').addEventListener('change', (e) => { S.showLandmarks = e.target.checked; renderViewer(); });
$('ceph-toggle-labels').addEventListener('change', (e) => { S.showLabels = e.target.checked; renderViewer(); });
$('ceph-toggle-traces').addEventListener('change', (e) => { S.showTraces = e.target.checked; renderViewer(); });
$('ceph-toggle-scalebar').addEventListener('change', (e) => { S.showScaleBar = e.target.checked; renderViewer(); });
$('ceph-toggle-grid').addEventListener('change', (e) => { S.showGrid = e.target.checked; renderViewer(); });
$('ceph-loupe-factor').addEventListener('change', (e) => {
    S.loupeFactor = parseInt(e.target.value, 10) || 0;
    renderViewer();
});

// Mesures
document.querySelectorAll('[data-measure]').forEach((b) => {
    b.addEventListener('click', () => {
        S.measureType = b.dataset.measure;
        S.measureDraft = null;
        renderAll();
    });
});
$('ceph-measure-clear').addEventListener('click', () => {
    if (!S.measures.length) return;
    if (!confirm('Effacer toutes les mesures ?')) return;
    S.measures = [];
    S.measureDraft = null;
    touch();
    renderAll();
});

$('ceph-hand').addEventListener('click', () => {
    S.handTool = !S.handTool;
    $('ceph-hand').classList.toggle('is-active', S.handTool);
    stage.classList.toggle('is-hand', S.handTool);
});

$('ceph-fit').addEventListener('click', () => { fitToStage(); renderViewer(); });
$('ceph-zoom-in').addEventListener('click', () => zoomBy(1.2));
$('ceph-zoom-out').addEventListener('click', () => zoomBy(1 / 1.2));

// ---------------------------------------------------------------------------
// Enregistrement
// ---------------------------------------------------------------------------

let saveTimer = null;

function scheduleSave() {
    setSaveState('pending');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 1200);
}

function setSaveState(state) {
    const el = $('ceph-save-state');
    if (state === 'pending') { el.textContent = 'Modifications non enregistrées'; el.className = 'ceph-save-state is-pending'; }
    else if (state === 'saving') { el.textContent = 'Enregistrement…'; el.className = 'ceph-save-state is-saving'; }
    else if (state === 'saved') { el.textContent = 'Enregistré'; el.className = 'ceph-save-state is-saved'; }
    else if (state === 'error') { el.textContent = 'Échec de l’enregistrement'; el.className = 'ceph-save-state is-error'; }
}

async function save() {
    if (S.saving) { scheduleSave(); return; }
    S.saving = true;
    setSaveState('saving');
    try {
        const res = await fetch(`/cephalometrie/${CFG.case.id}/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                analysis_id: S.analysisId,
                landmarks: S.landmarks,
                traces: S.traces,
                measures: S.measures,
                calibration: S.calibration,
                adjust: S.adjust,
                notes: $('ceph-notes').value,
            }),
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        S.dirty = false;
        setSaveState('saved');
    } catch (err) {
        console.error(err);
        setSaveState('error');
    } finally {
        S.saving = false;
    }
}

$('ceph-save').addEventListener('click', () => { clearTimeout(saveTimer); save(); });
$('ceph-notes').addEventListener('input', scheduleSave);

window.addEventListener('beforeunload', (e) => {
    if (S.dirty) { e.preventDefault(); e.returnValue = ''; }
});

// ---------------------------------------------------------------------------
// Rapport PDF
// ---------------------------------------------------------------------------

/**
 * Compose le tracé (radio + plans + points + tracés) sur un canvas, en pixels de
 * l'image naturelle, pour l'intégrer au rapport PDF. Le canvas applique les
 * mêmes réglages d'image que la visionneuse.
 */
function renderTracingPng() {
    if (!S.image) return null;
    const maxW = 1600;
    const scale = Math.min(1, maxW / S.image.width);
    const cw = Math.round(S.image.width * scale);
    const ch = Math.round(S.image.height * scale);

    const canvas = document.createElement('canvas');
    canvas.width = cw;
    canvas.height = ch;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, cw, ch);

    // Le rapport doit montrer EXACTEMENT ce que le praticien a lu a l'ecran :
    // on applique la meme table de correspondance, pixel par pixel, plutot
    // qu'une approximation par filtres CSS (qui ne savent pas faire un
    // fenetrage arbitraire ni un gamma).
    const source = (S.adjust.clahe && claheBitmap && claheBitmap.complete && claheBitmap.naturalWidth)
        ? claheBitmap
        : bitmap;
    if (source.complete && source.naturalWidth) {
        ctx.drawImage(source, 0, 0, cw, ch);
        try {
            const lut = windowLut({
                center: S.adjust.center, width: S.adjust.width,
                gamma: S.adjust.gamma, invert: S.adjust.invert,
            }).split(' ').map((v) => Math.round(parseFloat(v) * 255));
            const img = ctx.getImageData(0, 0, cw, ch);
            const d = img.data;
            for (let i = 0; i < d.length; i += 4) {
                d[i] = lut[d[i]];
                d[i + 1] = lut[d[i + 1]];
                d[i + 2] = lut[d[i + 2]];
            }
            ctx.putImageData(img, 0, 0);
        } catch (err) {
            console.warn('Application des réglages au rapport impossible :', err);
        }
    }

    ctx.save();
    ctx.scale(scale, scale);
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';

    // Plans de référence
    for (const p of drawablePlanes(S.landmarks).filter((x) => S.visiblePlanes[x.id])) {
        ctx.beginPath();
        ctx.strokeStyle = p.color;
        ctx.lineWidth = 2 / scale;
        ctx.setLineDash(p.dash ? [8 / scale, 6 / scale] : []);
        ctx.moveTo(p.a.x, p.a.y);
        ctx.lineTo(p.b.x, p.b.y);
        ctx.stroke();
    }
    ctx.setLineDash([]);

    // Tracés anatomiques
    if (S.showTraces) {
        for (const t of S.traces) {
            if (t.points.length < 2) continue;
            ctx.beginPath();
            ctx.strokeStyle = TRACE_COLOR[t.structure] || '#fff';
            ctx.lineWidth = 2.6 / scale;
            ctx.moveTo(t.points[0].x, t.points[0].y);
            for (const pt of t.points.slice(1)) ctx.lineTo(pt.x, pt.y);
            ctx.stroke();
        }
    }

    // Points + étiquettes
    const r = 5 / scale;
    ctx.font = `${Math.round(15 / scale)}px Manrope, sans-serif`;
    ctx.lineWidth = 1.4 / scale;
    for (const id in S.landmarks) {
        const def = LANDMARK_BY_ID[id];
        if (!def) continue;
        const p = S.landmarks[id];
        ctx.beginPath();
        ctx.fillStyle = GROUP_COLOR[def.group];
        ctx.strokeStyle = '#fff';
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 3 / scale;
        ctx.strokeText(def.abbr, p.x + r * 1.6, p.y - r);
        ctx.fillText(def.abbr, p.x + r * 1.6, p.y - r);
        ctx.lineWidth = 1.4 / scale;
    }
    // Mesures libres
    if (S.measures.length) {
        ctx.font = `${Math.round(15 / scale)}px Manrope, sans-serif`;
        for (const m of S.measures) {
            ctx.beginPath();
            ctx.strokeStyle = '#facc15';
            ctx.lineWidth = 2.2 / scale;
            ctx.moveTo(m.pts[0].x, m.pts[0].y);
            for (const pt of m.pts.slice(1)) ctx.lineTo(pt.x, pt.y);
            ctx.stroke();
            const v = measureValue(m);
            if (!v) continue;
            const anchor = m.type === 'angle' ? m.pts[1] : {
                x: (m.pts[0].x + m.pts[m.pts.length - 1].x) / 2,
                y: (m.pts[0].y + m.pts[m.pts.length - 1].y) / 2,
            };
            ctx.strokeStyle = '#000';
            ctx.lineWidth = 3.5 / scale;
            ctx.fillStyle = '#facc15';
            ctx.strokeText(v, anchor.x + 8 / scale, anchor.y - 8 / scale);
            ctx.fillText(v, anchor.x + 8 / scale, anchor.y - 8 / scale);
        }
    }

    ctx.restore();

    return canvas.toDataURL('image/png');
}

// Bitmap HTML utilisée par le canvas (le <image> SVG n'est pas dessinable directement).
const bitmap = new Image();
bitmap.crossOrigin = 'anonymous';
bitmap.src = CFG.case.image_url;

// Version egalisee localement, tenue a jour pour que le rapport PDF reflete le
// mode d'affichage reellement utilise.
let claheBitmap = null;

async function buildReport(download) {
    const btn = download ? $('ceph-pdf-dl') : $('ceph-pdf-print');
    btn.disabled = true;
    try {
        if (S.dirty) { clearTimeout(saveTimer); await save(); }

        const rows = currentResults().map((r) => ({
            name: r.def.name,
            unit: r.def.unit,
            value: r.value !== null ? fmt(r.value, r.def.unit) : null,
            norm: fmtNorm(r.norm, r.def.unit),
            z: r.z !== null && isFinite(r.z) ? (r.z > 0 ? '+' : '') + r.z.toFixed(1).replace('.', ',') : '',
            severity: r.severity,
            severity_label: r.value !== null ? SEVERITY_LABEL[r.severity] : '',
            note: r.note || '',
            missing: r.value === null
                ? (r.needsCalibration
                    ? 'Calibration requise'
                    : 'Points manquants : ' + r.missing.map((m) => (LANDMARK_BY_ID[m] ? LANDMARK_BY_ID[m].abbr : m)).join(', '))
                : '',
        }));

        const a = ANALYSIS_BY_ID[S.analysisId];
        const res = await fetch(`/cephalometrie/${CFG.case.id}/rapport.pdf`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                analysis_name: a.name,
                analysis_subtitle: a.subtitle,
                citation: a.citation || '',
                calibrated: !!S.calibration.mmPerPx,
                rows,
                summary: diagnosticSummary(S.landmarks, S.calibration.mmPerPx, S.subject),
                notes: $('ceph-notes').value,
                tracing_png: renderTracingPng(),
            }),
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);

        if (download) {
            const link = document.createElement('a');
            link.href = url;
            link.download = `cephalometrie_${CFG.patient.slug}_${CFG.case.id}.pdf`;
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 60000);
        } else {
            printBlobUrl(url);
        }
    } catch (err) {
        console.error(err);
        window.showToast && window.showToast('Génération du rapport impossible.', 'error');
    } finally {
        btn.disabled = false;
    }
}

/** Même mécanique d'impression directe que window.printPdf, mais sur un blob déjà en main. */
function printBlobUrl(blobUrl) {
    const old = document.getElementById('__cephPrintFrame');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    const frame = document.createElement('iframe');
    frame.id = '__cephPrintFrame';
    frame.setAttribute('aria-hidden', 'true');
    frame.style.cssText = 'position:fixed;left:-10000px;top:0;width:210mm;height:297mm;border:0;';
    let done = false;
    const go = () => {
        if (done) return;
        done = true;
        try { frame.contentWindow.focus(); frame.contentWindow.print(); }
        catch (e) { window.open(blobUrl, '_blank'); }
        setTimeout(() => { try { URL.revokeObjectURL(blobUrl); } catch (e) { /* déjà libéré */ } }, 120000);
    };
    frame.onload = () => setTimeout(go, 300);
    frame.src = blobUrl;
    document.body.appendChild(frame);
    setTimeout(go, 2500);
}

$('ceph-pdf-print').addEventListener('click', () => buildReport(false));
$('ceph-pdf-dl').addEventListener('click', () => buildReport(true));

// ---------------------------------------------------------------------------
// Détection automatique (brouillon IA)
// ---------------------------------------------------------------------------

const aiBtn = $('ceph-ai-btn');
const aiLabel = $('ceph-ai-label');
let aiBusy = false;

async function runAutodetect() {
    if (aiBusy || !S.image) return;
    // Ne pas écraser un travail déjà entamé sans prévenir.
    const already = Object.keys(S.landmarks).length;
    if (already && !confirm(
        `La détection automatique va pré-positionner 19 points (brouillon à valider).\n`
        + `${already} point(s) sont déjà posés et pourraient être remplacés. Continuer ?`)) {
        return;
    }

    aiBusy = true;
    aiBtn.classList.add('is-active');
    aiBtn.disabled = true;
    const setLbl = (t) => { aiLabel.textContent = t; };

    try {
        const { landmarks, unreliable, lowConf } = await detectLandmarks(
            bitmap, S.image.width, S.image.height, setLbl);

        for (const id in landmarks) {
            S.landmarks[id] = landmarks[id];
            S.aiSuggested.add(id);
        }
        S.mode = 'landmark';
        S.activeLandmark = null;
        touch();
        renderAll();

        const flag = [...new Set([...unreliable, ...lowConf])]
            .filter((id) => LANDMARK_BY_ID[id])
            .map((id) => LANDMARK_BY_ID[id].abbr);
        const msg = '19 points pré-positionnés (brouillon). Vérifiez chaque point'
            + (flag.length ? `, notamment : ${flag.join(', ')}.` : '.');
        window.showToast && window.showToast(msg, 'info');
    } catch (err) {
        console.error(err);
        window.showToast && window.showToast(
            'Détection automatique impossible : ' + (err.message || 'erreur inconnue'), 'error');
    } finally {
        aiBusy = false;
        aiBtn.classList.remove('is-active');
        aiBtn.disabled = false;
        setLbl('Détection auto');
    }
}

// Le bouton n'apparaît que si l'asset modèle est présent sur le serveur — sinon
// le module reste 100 % manuel, sans rien casser.
modelAvailable().then((ok) => {
    if (ok) aiBtn.style.display = '';
});
aiBtn.addEventListener('click', runAutodetect);

// ---------------------------------------------------------------------------
// Démarrage
// ---------------------------------------------------------------------------

advanceLandmark();
syncWindowInputs();
$('ceph-invert-btn').classList.toggle('is-active', S.adjust.invert);
$('ceph-flip-btn').classList.toggle('is-active', S.adjust.flipH);
$('ceph-clahe-btn').classList.toggle('is-active', S.adjust.clahe);
$('ceph-loupe-factor').value = String(S.loupeFactor);
loadImage();
renderAll();
setSaveState('saved');
// L'egalisation locale enregistree avec le dossier est recalculee au chargement
// (le blob de la session precedente n'existe plus).
if (S.adjust.clahe) {
    bitmap.addEventListener('load', () => setClahe(true), { once: true });
}
