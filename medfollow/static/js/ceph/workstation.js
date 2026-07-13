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

const LOUPE_FACTOR = 4;
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

const S = {
    analysisId: CFG.case.analysis_id || 'steiner',
    landmarks: CFG.case.landmarks || {},
    traces: CFG.case.traces || [],
    calibration: Object.assign({ mmPerPx: null, p1: null, p2: null, knownMm: 100 }, CFG.case.calibration || {}),
    adjust: Object.assign({ brightness: 100, contrast: 100, gamma: 1, invert: false, flipH: false }, CFG.case.adjust || {}),
    subject: { sex: CFG.patient.sex, age: CFG.patient.age },

    mode: 'landmark',           // landmark | calibrate | trace | measure
    activeLandmark: null,
    traceStructure: 'soft-profile',
    visiblePlanes: { ...DEFAULT_PLANES },
    showLandmarks: true,
    showLabels: true,
    showTraces: true,
    loupe: true,
    ruler: null,

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
        imgEl.setAttribute('href', CFG.case.image_url);
        imgEl.setAttribute('width', S.image.width);
        imgEl.setAttribute('height', S.image.height);
        loupeImgEl.setAttribute('href', CFG.case.image_url);
        loupeImgEl.setAttribute('width', S.image.width);
        loupeImgEl.setAttribute('height', S.image.height);
        fitToStage();
        renderAll();
    };
    probe.onerror = () => {
        hintEl.textContent = 'Impossible de charger la radiographie.';
    };
    probe.src = CFG.case.image_url;
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

function toImage(clientX, clientY) {
    const r = stage.getBoundingClientRect();
    const sx = clientX - r.left;
    const sy = clientY - r.top;
    let ix = (sx - S.view.x) / S.view.zoom;
    const iy = (sy - S.view.y) / S.view.zoom;
    if (S.adjust.flipH && S.image) ix = S.image.width - ix;
    return { x: ix, y: iy };
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
    touch();
}

function removeLandmark(id) {
    delete S.landmarks[id];
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

function updateFilter() {
    const b = S.adjust.brightness / 100;
    const c = S.adjust.contrast / 100;
    const g = 1 / S.adjust.gamma;
    for (const ch of ['R', 'G', 'B']) {
        const gam = $(`ceph-gamma${ch}`);
        gam.setAttribute('exponent', g);
        const lin = $(`ceph-lin${ch}`);
        // Le contraste pivote autour du gris moyen, puis la luminosité multiplie.
        lin.setAttribute('slope', c * b);
        lin.setAttribute('intercept', (0.5 - 0.5 * c) * b);
    }
    $('ceph-invert').style.display = S.adjust.invert ? '' : 'none';
    // feComponentTransfer ne se désactive pas par display : on neutralise la table.
    for (const ch of ['R', 'G', 'B']) {
        $(`ceph-inv${ch}`).setAttribute('tableValues', S.adjust.invert ? '1 0' : '0 1');
    }
}

function renderViewer() {
    if (!S.image) return;
    const { zoom, x, y } = S.view;
    const flipT = S.adjust.flipH ? `translate(${S.image.width} 0) scale(-1 1)` : '';
    gImage.setAttribute('transform', `translate(${x} ${y}) scale(${zoom}) ${flipT}`);
    gOverlay.setAttribute('transform', `translate(${x} ${y}) scale(${zoom}) ${flipT}`);
    imgEl.style.imageRendering = zoom > 2 ? 'pixelated' : 'auto';
    updateFilter();
    renderOverlay();
    renderLoupe();
    renderHud();
}

function renderOverlay() {
    gOverlay.innerHTML = '';
    const zoom = S.view.zoom;
    const lw = 1 / zoom;
    const fs = 11 / zoom;
    const r = 4 / zoom;

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

    // Règle de mesure ponctuelle
    if (S.ruler) {
        el('line', {
            x1: S.ruler.a.x, y1: S.ruler.a.y, x2: S.ruler.b.x, y2: S.ruler.b.y,
            stroke: '#ca8a04', 'stroke-width': lw * 1.4,
        }, gOverlay);
        el('circle', { cx: S.ruler.a.x, cy: S.ruler.a.y, r: r * 0.7, fill: '#ca8a04' }, gOverlay);
        el('circle', { cx: S.ruler.b.x, cy: S.ruler.b.y, r: r * 0.7, fill: '#ca8a04' }, gOverlay);
    }

    // Points céphalométriques
    if (S.showLandmarks) {
        for (const id in S.landmarks) {
            const def = LANDMARK_BY_ID[id];
            if (!def) continue;
            const p = S.landmarks[id];
            const color = GROUP_COLOR[def.group];
            if (id === S.activeLandmark) {
                el('circle', { cx: p.x, cy: p.y, r: r * 2.6, fill: color, opacity: 0.18 }, gOverlay);
            }
            el('circle', {
                cx: p.x, cy: p.y, r, fill: color, stroke: '#fff',
                'stroke-width': lw * 0.8, opacity: 0.98,
            }, gOverlay);
            el('circle', { cx: p.x, cy: p.y, r: r * 0.28, fill: '#fff', opacity: 0.9 }, gOverlay);
            if (S.showLabels) {
                // Un halo blanc garde l'étiquette lisible aussi bien sur l'émail
                // clair que sur l'air sombre du cliché.
                const t = el('text', {
                    x: p.x + r * 1.8, y: p.y - r * 1.1,
                    'font-size': fs, fill: color, stroke: '#fff',
                    'stroke-width': fs * 0.3, 'paint-order': 'stroke',
                    'font-weight': 600, 'pointer-events': 'none',
                    transform: S.adjust.flipH ? `translate(${2 * p.x} 0) scale(-1 1)` : null,
                }, gOverlay);
                t.textContent = def.abbr;
            }
        }
    }
}

/**
 * La loupe redessine la radio à LOUPE_FACTOR × le zoom courant, découpée en
 * disque, décalée du curseur. Placer un point au pixel près sur un cliché flou
 * est impossible sans elle.
 */
function renderLoupe() {
    if (!S.loupe || !S.cursor || S.panning || !S.image) {
        gLoupe.style.display = 'none';
        return;
    }
    gLoupe.style.display = '';
    const Z = S.view.zoom * LOUPE_FACTOR;
    const cx = S.cursor.s.x + LOUPE_R + 26;
    const cy = S.cursor.s.y - LOUPE_R - 26;
    const ix = S.adjust.flipH ? S.image.width - S.cursor.i.x : S.cursor.i.x;
    const iy = S.cursor.i.y;
    const flipT = S.adjust.flipH ? `translate(${S.image.width} 0) scale(-1 1)` : '';

    $('ceph-loupe-clipped').setAttribute('transform', `translate(${cx} ${cy})`);
    $('ceph-loupe-scale').setAttribute('transform', `scale(${Z}) translate(${-ix} ${-iy})`);
    $('ceph-loupe-flip').setAttribute('transform', flipT);
    $('ceph-loupe-ring').setAttribute('cx', cx);
    $('ceph-loupe-ring').setAttribute('cy', cy);

    const pts = $('ceph-loupe-points');
    pts.innerHTML = '';
    for (const id in S.landmarks) {
        const p = S.landmarks[id];
        el('circle', {
            cx: S.adjust.flipH ? S.image.width - p.x : p.x,
            cy: p.y, r: 3 / Z, fill: '#0284c7', stroke: '#fff',
            'stroke-width': 1 / Z, opacity: 0.95,
        }, pts);
    }
}

function renderHud() {
    const bits = [];
    if (S.ruler) {
        const px = Math.hypot(S.ruler.b.x - S.ruler.a.x, S.ruler.b.y - S.ruler.a.y);
        bits.push(`<b class="ceph-hud-ruler">${S.calibration.mmPerPx
            ? (px * S.calibration.mmPerPx).toFixed(2).replace('.', ',') + ' mm'
            : px.toFixed(1).replace('.', ',') + ' px'}</b>`);
    }
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
        hintEl.innerHTML = `<span class="ceph-hint-name">Règle</span>
            <span class="ceph-hint-def">Glissez pour mesurer une distance libre sur le cliché.</span>`;
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
            const row = document.createElement('button');
            row.type = 'button';
            row.className = 'ceph-lm' + (done ? ' is-done' : '') + (id === S.activeLandmark ? ' is-active' : '');
            row.title = def.definition;
            row.innerHTML = `
                <span class="ceph-lm-abbr" style="color:${g.color}">${def.abbr}</span>
                <span class="ceph-lm-name">${def.name}</span>
                <span class="ceph-lm-state">${done ? '✓' : '○'}</span>`;
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
    $('ceph-calib-mm').value = S.calibration.knownMm;
    $('ceph-calib-state').textContent = S.calibration.mmPerPx
        ? `Calibré : ${S.calibration.mmPerPx.toFixed(4).replace('.', ',')} mm/px`
        : 'Non calibré — les mesures en mm sont retenues.';
    $('ceph-calib-state').className = S.calibration.mmPerPx ? 'ceph-calib-state ceph-ok' : 'ceph-calib-state ceph-warn';
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

stage.addEventListener('pointerdown', (e) => {
    if (!S.image || onPanel(e)) return;
    stage.setPointerCapture(e.pointerId);

    // Bouton du milieu ou barre d'espace : déplacement, quel que soit l'outil.
    if (e.button === 1 || S.spaceDown) {
        S.panning = { x: e.clientX - S.view.x, y: e.clientY - S.view.y };
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
        S.ruler = { a: p, b: p };
        S.dragging = '__ruler';
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
    if (S.dragging === '__ruler' && S.ruler) {
        S.ruler.b = p;
        renderViewer();
        return;
    }
    if (S.dragging) {
        S.landmarks[S.dragging] = p;
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
    if (S.dragging && S.dragging !== '__ruler' && S.mode === 'landmark') {
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
            const flip = S.adjust.flipH ? -1 : 1;
            const p = S.landmarks[sel];
            S.landmarks[sel] = { x: p.x + d[0] * flip, y: p.y + d[1] };
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
const ADJ = [
    ['ceph-brightness', 'brightness', (v) => parseFloat(v)],
    ['ceph-contrast', 'contrast', (v) => parseFloat(v)],
    ['ceph-gamma', 'gamma', (v) => parseFloat(v)],
];
for (const [id, key, parse] of ADJ) {
    const input = $(id);
    input.value = S.adjust[key];
    input.addEventListener('input', (e) => {
        S.adjust[key] = parse(e.target.value);
        touch();
        renderViewer();
    });
}
$('ceph-invert-btn').addEventListener('click', () => {
    S.adjust.invert = !S.adjust.invert;
    $('ceph-invert-btn').classList.toggle('is-active', S.adjust.invert);
    touch();
    renderViewer();
});
$('ceph-flip-btn').addEventListener('click', () => {
    S.adjust.flipH = !S.adjust.flipH;
    $('ceph-flip-btn').classList.toggle('is-active', S.adjust.flipH);
    touch();
    renderViewer();
});
$('ceph-reset-adjust').addEventListener('click', () => {
    S.adjust = { brightness: 100, contrast: 100, gamma: 1, invert: false, flipH: false };
    $('ceph-brightness').value = 100;
    $('ceph-contrast').value = 100;
    $('ceph-gamma').value = 1;
    $('ceph-invert-btn').classList.remove('is-active');
    $('ceph-flip-btn').classList.remove('is-active');
    touch();
    renderViewer();
});

// Affichage
$('ceph-toggle-landmarks').addEventListener('change', (e) => { S.showLandmarks = e.target.checked; renderViewer(); });
$('ceph-toggle-labels').addEventListener('change', (e) => { S.showLabels = e.target.checked; renderViewer(); });
$('ceph-toggle-traces').addEventListener('change', (e) => { S.showTraces = e.target.checked; renderViewer(); });
$('ceph-toggle-loupe').addEventListener('change', (e) => { S.loupe = e.target.checked; renderViewer(); });

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

    const a = S.adjust;
    const filters = [`brightness(${a.brightness}%)`, `contrast(${a.contrast}%)`];
    if (a.invert) filters.push('invert(1)');
    ctx.filter = filters.join(' ');
    if (bitmap.complete && bitmap.naturalWidth) ctx.drawImage(bitmap, 0, 0, cw, ch);
    ctx.filter = 'none';

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
    ctx.restore();

    return canvas.toDataURL('image/png');
}

// Bitmap HTML utilisée par le canvas (le <image> SVG n'est pas dessinable directement).
const bitmap = new Image();
bitmap.crossOrigin = 'anonymous';
bitmap.src = CFG.case.image_url;

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
// Démarrage
// ---------------------------------------------------------------------------

advanceLandmark();
loadImage();
renderAll();
setSaveState('saved');
