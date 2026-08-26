/**
 * Parodontogramme SEPA (port de dentalpin `PeriodontogramView/Chart`,
 * `PerioArchBlock`, `PerioToothLateral`, `PerioProfileStrip`, `PerioSiteMarker`,
 * `PerioIndicesBanner`, `usePerioHeatmap`, `usePeriodontogramSession`).
 *
 * mountPeriodontogram(root, { patientId }) → { refresh, destroy }
 */

import { perioApi, toast } from './api.js';
import { esc } from './constants.js';
import { GUM_LINE_Y_BY_POSITION, VIEWBOX_W_BY_POSITION, getLateralPath, getToothPosition, getToothTransform, implantSvg } from './paths.js';
import { confirmDialog } from './popups.js';
import { createTimeline } from './timeline.js';

const P = {
  empty: {
    title: 'Aucun examen parodontal pour le moment',
    description: 'Ouvrez une nouvelle session pour enregistrer les profondeurs de sondage, les saignements, la plaque et les autres métriques SEPA.',
    cta: "Commencer l'examen",
  },
  session: {
    draftBadge: 'Brouillon en cours',
    closedBadge: 'Session clôturée',
    recordedAt: (d) => `Enregistré le ${d}`,
    openDraft: 'Ouvrir une nouvelle session',
    closeTitle: 'Clôturer la session parodontale',
    closeDescription: "Une fois clôturée, la session est immutable et apparaît dans l'historique. Pour apporter des corrections, vous devrez ouvrir une nouvelle session.",
    closeButton: 'Clôturer la session',
    discardTitle: 'Abandonner le brouillon',
    discardDescription: 'Toutes les données saisies dans cette session seront supprimées. Cette action est irréversible.',
    discardButton: 'Abandonner',
    cancel: 'Annuler',
    closeSession: 'Clôturer la session',
    discardDraft: 'Abandonner le brouillon',
    closedCount: (n) => `${n} session${n > 1 ? 's' : ''} clôturée${n > 1 ? 's' : ''}`,
  },
  indices: { bop: 'Saignement', pi: 'Plaque', calMean: 'CAL moyen', deepPockets: 'Poches ≥5mm' },
  saveState: { saving: 'Enregistrement…', dirty: 'Modifications non enregistrées', saved: 'Modifications enregistrées' },
  history: { viewingSession: (d) => `Visualisation de la session du ${d} (lecture seule).`, returnToCurrent: 'Retour à la session actuelle' },
  arch: {
    upper: 'Supérieure', lower: 'Inférieure', palatal: 'Palatin', lingual: 'Lingual', vestibular: 'Vestibulaire',
    probing: 'Sondage', margin: 'Marge', bleeding: 'Saignement', plaque: 'Plaque',
    probingTitle: (c) => `${c} sondage (0–15 mm)`,
    marginTitle: (c) => `${c} marge gingivale (-5 à 10 mm)`,
    plaqueTitle: (c) => `${c} plaque (cliquer pour basculer)`,
    bleedingTitle: (c) => `${c} saignement (cliquer pour basculer)`,
    implant: 'Implant', implantToggleOn: 'Implant (cliquer pour retirer)', implantToggleOff: 'Cliquer pour marquer comme implant',
    mobility: 'Mobilité', mobilityTitle: 'Cliquer pour modifier la mobilité (0–3)',
    prognosis: 'Pronostic', prognosisTitle: 'Bon / Moyen / Douteux / Sans espoir',
    furcaV: 'Furca V', furcaVTitle: 'Furca vestibulaire (0/I/II/III)',
    furcaLP: 'Furca L/P', furcaLPTitle: 'Furca linguale/palatine (0/I/II/III)',
    gingivalWidth: 'Largeur gingivale',
    siteMarkerAria: (c, d) => `Site ${c}, sondage ${d}`,
  },
  chart: { ariaLabel: 'Parodontogramme — arcades supérieure et inférieure' },
  loading: 'Chargement du parodontogramme…',
  errors: {
    loadFailed: 'Impossible de charger le parodontogramme.',
    saveFailed: "Impossible d'enregistrer la modification.",
    checkConnection: 'Vérifiez votre connexion et réessayez.',
  },
  noValue: '—',
};

const VESTIBULAR_SITES = ['MV', 'V', 'DV'];
const PALATAL_SITES = ['ML', 'L', 'DL'];
const SITES_PER_TOOTH = 6;
const DEEP_POCKET_THRESHOLD_MM = 5;
const DEBOUNCE_MS = 600;
const TOOTH_COL_PX = 60;
const MM_PX = 4;
const MAX_MM = 15;
const STRIP_H = MAX_MM * MM_PX;

const MOBILITY_CYCLE = [null, 0, 1, 2, 3];
const PROGNOSIS_CYCLE = [null, 'good', 'fair', 'poor', 'hopeless'];
const FURCA_CYCLE = [null, '0', 'I', 'II', 'III'];

function nextInCycle(cycle, current) {
  const idx = cycle.findIndex((v) => v === current);
  return cycle[(idx + 1) % cycle.length];
}

function prognosisGlyph(v) {
  return { good: 'B', fair: 'M', poor: 'D', hopeless: '✕' }[v] || '·';
}

function mobilityGlyph(v) { return v === null || v === undefined ? '·' : String(v); }
function furcaGlyph(v) { return v || '·'; }

function probingTone(pd) {
  if (pd === null || pd === undefined) return 'neutral';
  if (pd <= 3) return 'success';
  if (pd === 4) return 'warning-low';
  if (pd <= 6) return 'warning-high';
  return 'error';
}

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' });
}

function fmtDateLong(iso) {
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' });
}

function computeIndices(teeth) {
  const present = teeth.filter((t) => t.is_present);
  const total = present.length * SITES_PER_TOOTH;
  if (total === 0) return { bop_pct: 0, pi_pct: 0, cal_mean_mm: 0, deep_pockets_count: 0 };
  let bop = 0, plaque = 0, cal = 0, deep = 0;
  for (const t of present) {
    let hasDeep = false;
    for (const s of t.sites) {
      if (s.bleeding_on_probing) bop++;
      if (s.plaque) plaque++;
      if (s.probing_depth_mm != null && s.gingival_margin_mm != null) cal += s.probing_depth_mm + s.gingival_margin_mm;
      if (s.probing_depth_mm != null && s.probing_depth_mm >= DEEP_POCKET_THRESHOLD_MM) hasDeep = true;
    }
    if (hasDeep) deep++;
  }
  return { bop_pct: (100 * bop) / total, pi_pct: (100 * plaque) / total, cal_mean_mm: cal / total, deep_pockets_count: deep };
}

// ============================================================================
// Rendus élémentaires
// ============================================================================

function siteOf(tooth, code) {
  return tooth.sites.find((s) => s.site_code === code) || null;
}

function siteMarker(site, code) {
  const pd = site ? site.probing_depth_mm : null;
  return `<span class="perio-site-marker perio-tone-${probingTone(pd)}" aria-label="${esc(P.arch.siteMarkerAria(code, pd == null ? P.noValue : pd))}">${pd == null ? '·' : pd}</span>`;
}

/** Une dent latérale + 3 marqueurs (PerioToothLateral.vue). */
function renderToothLateral(tooth, face, markersPosition) {
  const n = tooth.tooth_number;
  const paths = getLateralPath(n);
  const pos = getToothPosition(n);
  const vbW = VIEWBOX_W_BY_POSITION[pos] || 46;
  const gly = GUM_LINE_Y_BY_POSITION[pos] || 95;
  const VIEW_W = 70, VIEW_H = 150, TARGET_GUM = 97.5;
  const xV = vbW / 2 - VIEW_W / 2;
  const yV = gly - TARGET_GUM;
  const base = getToothTransform(n);
  const transform = face === 'vestibular' ? base : `${base} scaleY(-1)`.trim();
  const sites = face === 'vestibular' ? VESTIBULAR_SITES : PALATAL_SITES;
  const markers = `<div class="perio-markers">${sites.map((c) => siteMarker(siteOf(tooth, c), c)).join('')}</div>`;
  let roots = '';
  if (!tooth.is_implant) {
    roots = '<g class="perio-roots">';
    if (paths.root) roots += `<path d="${paths.root}"/>`;
    else if (paths.roots) roots += paths.roots.map((d) => `<path d="${d}"/>`).join('');
    roots += '</g>';
  }
  const implant = tooth.is_implant && tooth.is_present ? implantSvg(paths.viewBox, '#10B981', 1) : '';
  return `<div class="perio-tooth-lateral">
    ${markersPosition === 'above' ? markers : ''}
    <div class="perio-tooth-svg-wrap" style="opacity:${tooth.is_present ? 1 : 0.35}">
      <svg viewBox="${xV} ${yV} ${VIEW_W} ${VIEW_H}" class="perio-tooth-svg" style="transform:${transform}" preserveAspectRatio="xMidYMid meet">
        ${roots}${implant}
        <g class="perio-crown"><path d="${paths.crown}"/></g>
      </svg>
      ${tooth.is_present ? '' : '<span class="perio-absent">—</span>'}
    </div>
    ${markersPosition !== 'above' ? markers : ''}
  </div>`;
}

/** Profil SEPA : lignes marge gingivale / fond de poche (PerioProfileStrip.vue). */
function renderStrip(teeth, face, direction) {
  const sites = face === 'vestibular' ? VESTIBULAR_SITES : PALATAL_SITES;
  const width = teeth.length * TOOTH_COL_PX;
  const depthToY = (mm) => {
    const c = Math.max(-3, Math.min(MAX_MM, mm));
    return direction === 'depth-up' ? STRIP_H - c * MM_PX : c * MM_PX;
  };
  const siteX = (ti, si) => ti * TOOTH_COL_PX + TOOTH_COL_PX * [0.2, 0.5, 0.8][si];
  const pts = (get) => {
    const out = [];
    teeth.forEach((t, ti) => sites.forEach((code, si) => {
      const mm = get(siteOf(t, code));
      if (mm == null) return;
      out.push({ x: siteX(ti, si), y: depthToY(mm) });
    }));
    return out;
  };
  const toPath = (arr) => arr.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x},${p.y}`).join(' ');
  const gm = pts((s) => (s ? s.gingival_margin_mm : null));
  const pd = pts((s) => (s && s.probing_depth_mm != null ? (s.gingival_margin_mm || 0) + s.probing_depth_mm : null));
  const bandGm = [], bandPd = [];
  teeth.forEach((t, ti) => sites.forEach((code, si) => {
    const s = siteOf(t, code);
    if (!s || s.probing_depth_mm == null) return;
    const g = s.gingival_margin_mm || 0;
    bandGm.push({ x: siteX(ti, si), y: depthToY(g) });
    bandPd.push({ x: siteX(ti, si), y: depthToY(g + s.probing_depth_mm) });
  }));
  let band = '';
  if (bandGm.length >= 2) {
    band = `${toPath(bandGm)} ${bandPd.slice().reverse().map((p) => `L ${p.x},${p.y}`).join(' ')} Z`;
  }
  let grid = '';
  for (let m = 0; m <= MAX_MM; m++) {
    grid += `<line x1="0" x2="${width}" y1="${depthToY(m)}" y2="${depthToY(m)}" class="perio-strip-grid${m % 5 === 0 ? ' bold' : ''}"/>`;
  }
  return `<svg viewBox="0 0 ${width} ${STRIP_H}" width="${width}" height="${STRIP_H}" class="perio-profile-strip" preserveAspectRatio="none" aria-hidden="true">
    <g>${grid}</g>
    ${band ? `<path d="${band}" class="perio-strip-band"/>` : ''}
    ${gm.length ? `<path d="${toPath(gm)}" class="perio-strip-gm"/>` : ''}
    ${pd.length ? `<path d="${toPath(pd)}" class="perio-strip-pd"/>` : ''}
  </svg>`;
}

// ============================================================================
// Bloc d'arcade (PerioArchBlock.vue)
// ============================================================================

function orderedTeeth(teeth, arch) {
  const quadrants = arch === 'upper' ? [1, 2] : [4, 3];
  const out = [];
  for (const q of quadrants) {
    const qt = teeth.filter((t) => Math.floor(t.tooth_number / 10) === q);
    qt.sort((a, b) => {
      const pa = a.tooth_number % 10, pb = b.tooth_number % 10;
      return q === 1 || q === 4 ? pb - pa : pa - pb;
    });
    out.push(...qt);
  }
  return out;
}

function renderArchBlock(teeth, arch, readonly) {
  const ordered = orderedTeeth(teeth, arch);
  const innerFace = arch === 'upper' ? 'palatal' : 'lingual';
  const innerLabel = arch === 'upper' ? P.arch.palatal : P.arch.lingual;
  const overlayWidth = `${ordered.length * TOOTH_COL_PX}px`;
  const dis = (t) => (readonly || !t.is_present ? ' disabled' : '');

  const fdiRow = (tag) => `<${tag}><tr><th class="perio-label"></th>${ordered.map((t) => `<th class="perio-fdi">${t.tooth_number}</th>`).join('')}</tr></${tag}>`;

  const implantRow = () => `<tr><th scope="row" class="perio-label">${P.arch.implant}</th>${ordered.map((t) => `<td><button type="button" class="perio-cell-cycle${t.is_implant ? ' is-implant' : ''}" data-act="implant" data-tooth="${t.tooth_number}"${readonly ? ' disabled' : ''} title="${t.is_implant ? P.arch.implantToggleOn : P.arch.implantToggleOff}">${t.is_implant ? '●' : '·'}</button></td>`).join('')}</tr>`;

  const cycleRow = (label, field, title, glyph) => `<tr><th scope="row" class="perio-label">${label}</th>${ordered.map((t) => `<td><button type="button" class="perio-cell-cycle" data-act="cycle" data-field="${field}" data-tooth="${t.tooth_number}"${dis(t)} title="${esc(title)}">${glyph(t[field])}</button></td>`).join('')}</tr>`;

  const kgRow = () => `<tr><th scope="row" class="perio-label">${P.arch.gingivalWidth}</th>${ordered.map((t) => `<td><input type="number" min="0" max="20" value="${t.keratinized_gingiva_mm ?? ''}" class="perio-cell-input" data-act="tooth-num" data-field="keratinized_gingiva_mm" data-tooth="${t.tooth_number}"${dis(t)}></td>`).join('')}</tr>`;

  const siteRow = (kind, label, face, sites, cls, tag) => {
    const cell = (t, code) => {
      const s = siteOf(t, code);
      if (kind === 'site-pd') return `<input type="number" min="0" max="15" value="${s && s.probing_depth_mm != null ? s.probing_depth_mm : ''}" class="perio-cell-input perio-cell-input--site" data-act="site-num" data-field="probing_depth_mm" data-tooth="${t.tooth_number}" data-site="${code}"${dis(t)} title="${esc(P.arch.probingTitle(code))}">`;
      if (kind === 'site-gm') return `<input type="number" min="-5" max="10" value="${s && s.gingival_margin_mm != null ? s.gingival_margin_mm : ''}" class="perio-cell-input perio-cell-input--site" data-act="site-num" data-field="gingival_margin_mm" data-tooth="${t.tooth_number}" data-site="${code}"${dis(t)} title="${esc(P.arch.marginTitle(code))}">`;
      if (kind === 'site-plaque') return `<button type="button" class="perio-cell-toggle perio-cell-toggle--plaque${s && s.plaque ? ' is-on' : ''}" data-act="site-toggle" data-field="plaque" data-tooth="${t.tooth_number}" data-site="${code}"${dis(t)} title="${esc(P.arch.plaqueTitle(code))}"></button>`;
      return `<button type="button" class="perio-cell-toggle perio-cell-toggle--bop${s && s.bleeding_on_probing ? ' is-on' : ''}" data-act="site-toggle" data-field="bleeding_on_probing" data-tooth="${t.tooth_number}" data-site="${code}"${dis(t)} title="${esc(P.arch.bleedingTitle(code))}"></button>`;
    };
    return `<tr class="${cls}"><th scope="row" class="perio-label">${label} <span class="perio-face-tag">${tag}</span></th>${ordered.map((t) => `<td><div class="perio-site-cells">${sites.map((c) => cell(t, c)).join('')}</div></td>`).join('')}</tr>`;
  };

  const toothRow = (face, label, cls, anchorCls, direction, markersPosition) => `<tr class="tooth-row">
    <th scope="row" class="perio-label perio-row-anchor ${cls}">${label}<div class="perio-profile-anchor ${anchorCls}" style="width:${overlayWidth}" data-strip="${face}">${renderStrip(ordered, face, direction)}</div></th>
    ${ordered.map((t) => `<td class="perio-tooth-cell" data-lateral="${t.tooth_number}-${face}" data-markers="${markersPosition}">${renderToothLateral(t, face, markersPosition)}</td>`).join('')}
  </tr>`;

  const V = [
    ['site-pd', P.arch.probing], ['site-gm', P.arch.margin], ['site-plaque', P.arch.plaque], ['site-bop', P.arch.bleeding],
  ];
  const VR = V.slice().reverse();

  let body;
  if (arch === 'upper') {
    body = [
      implantRow(),
      cycleRow(P.arch.mobility, 'mobility', P.arch.mobilityTitle, mobilityGlyph),
      cycleRow(P.arch.prognosis, 'prognosis', P.arch.prognosisTitle, prognosisGlyph),
      cycleRow(P.arch.furcaV, 'furcation_buccal', P.arch.furcaVTitle, furcaGlyph),
      cycleRow(P.arch.furcaLP, 'furcation_lingual', P.arch.furcaLPTitle, furcaGlyph),
      kgRow(),
      ...V.map(([k, l]) => siteRow(k, l, 'vestibular', VESTIBULAR_SITES, 'perio-row-vestibular', 'V')),
      toothRow('vestibular', P.arch.vestibular, 'perio-face-v', 'perio-profile-anchor--top', 'depth-up', 'below'),
      toothRow(innerFace, innerLabel, 'perio-face-p', 'perio-profile-anchor--bottom', 'depth-down', 'above'),
      ...VR.map(([k, l]) => siteRow(k, l, innerFace, PALATAL_SITES, 'perio-row-palatal', innerLabel.charAt(0))),
    ].join('');
  } else {
    body = [
      ...V.map(([k, l]) => siteRow(k, l, innerFace, PALATAL_SITES, 'perio-row-palatal', 'L')),
      toothRow(innerFace, innerLabel, 'perio-face-p', 'perio-profile-anchor--top', 'depth-up', 'below'),
      toothRow('vestibular', P.arch.vestibular, 'perio-face-v', 'perio-profile-anchor--bottom', 'depth-down', 'above'),
      ...VR.map(([k, l]) => siteRow(k, l, 'vestibular', VESTIBULAR_SITES, 'perio-row-vestibular', 'V')),
      kgRow(),
      cycleRow(P.arch.furcaLP, 'furcation_lingual', P.arch.furcaLPTitle, furcaGlyph),
      cycleRow(P.arch.furcaV, 'furcation_buccal', P.arch.furcaVTitle, furcaGlyph),
      cycleRow(P.arch.prognosis, 'prognosis', P.arch.prognosisTitle, prognosisGlyph),
      cycleRow(P.arch.mobility, 'mobility', P.arch.mobilityTitle, mobilityGlyph),
      implantRow(),
    ].join('');
  }

  return `<section class="perio-arch-block" data-arch="${arch}">
    <header class="perio-arch-header"><h4>${arch === 'upper' ? P.arch.upper : P.arch.lower}</h4><span>${P.arch.vestibular} (MV V DV) ↔ ${innerLabel} (ML L DL)</span></header>
    <table class="perio-arch-table">
      <colgroup><col style="width:96px">${ordered.map(() => '<col style="width:60px">').join('')}</colgroup>
      ${arch === 'upper' ? fdiRow('thead') : ''}
      <tbody>${body}</tbody>
      ${arch === 'lower' ? fdiRow('tfoot') : ''}
    </table>
  </section>`;
}

// ============================================================================
// Montage
// ============================================================================

export function mountPeriodontogram(root, opts) {
  const api = perioApi(opts.patientId);
  const state = {
    timeline: null,
    snapshot: null,
    viewingDate: null,
    loading: true,
    starting: false,
    error: null,
    saving: 0,
    dirty: false,
  };
  const pending = new Map(); // key -> { timer, payload }
  let timeline = null;

  root.classList.add('periodontogram-root');

  const hasDraft = () => !!(state.timeline && state.timeline.draft);
  const closedCount = () => (state.timeline ? state.timeline.dates.length : 0);
  const isEmpty = () => !hasDraft() && closedCount() === 0;
  const isViewingHistory = () => state.viewingDate !== null;
  const isReadOnly = () => isViewingHistory() || !state.snapshot || state.snapshot.status === 'closed';
  const q = (sel) => root.querySelector(sel);

  // ------------------------------------------------------------ rendering
  function bannerHtml() {
    const s = state.snapshot;
    const isDraft = s.status === 'draft';
    const indices = isReadOnly() ? s.indices : computeIndices(s.teeth);
    const saveState = state.saving > 0 ? 'saving' : state.dirty ? 'dirty' : 'saved';
    const saveIcon = saveState === 'saving' ? '<span class="odo-spinner odo-spinner-xs"></span>' : saveState === 'dirty' ? '☁' : '✓';
    return `<div class="perio-banner">
      <div class="perio-banner-row">
        <div class="perio-banner-left">
          ${isDraft ? `<span class="odo-badge odo-badge-warning">✎ ${P.session.draftBadge}</span>` : `<span class="odo-badge odo-badge-success">🔒 ${P.session.closedBadge}</span>`}
          <span class="odonto-muted odonto-small">${esc(P.session.recordedAt(fmtDate(s.closed_at || s.recorded_at)))}</span>
          ${isDraft ? `<span class="perio-save-pill state-${saveState}" role="status" aria-live="polite">${saveIcon} ${P.saveState[saveState]}</span>` : ''}
        </div>
        ${isDraft && !isViewingHistory() ? `<div class="odonto-actions">
          <button type="button" class="odo-btn odo-btn-ghost odo-btn-danger-text odo-btn-sm" data-act="discard">🗑 ${P.session.discardDraft}</button>
          <button type="button" class="odo-btn odo-btn-primary odo-btn-sm" data-act="close-session">✓ ${P.session.closeSession}</button>
        </div>` : ''}
      </div>
      ${indices ? `<div class="perio-indices">
        <div><div class="perio-index-label">${P.indices.bop}</div><div class="perio-index-value">${indices.bop_pct.toFixed(1)}%</div></div>
        <div><div class="perio-index-label">${P.indices.pi}</div><div class="perio-index-value">${indices.pi_pct.toFixed(1)}%</div></div>
        <div><div class="perio-index-label">${P.indices.calMean}</div><div class="perio-index-value">${indices.cal_mean_mm.toFixed(1)}mm</div></div>
        <div><div class="perio-index-label">${P.indices.deepPockets}</div><div class="perio-index-value">${indices.deep_pockets_count}</div></div>
      </div>` : ''}
    </div>`;
  }

  function render() {
    if (timeline) { timeline.destroy(); timeline = null; }
    let html;
    if (state.loading && !state.snapshot) {
      html = `<div class="odo-loading"><span class="odo-spinner"></span> <span class="odonto-muted">${P.loading}</span></div>`;
    } else if (state.error) {
      html = `<div class="odo-alert odo-alert-error">⚠ ${esc(P.errors.loadFailed)} <button type="button" class="odo-btn odo-btn-outline odo-btn-xs" data-act="retry">Réessayer</button></div>`;
    } else if (isEmpty()) {
      html = `<div class="perio-empty"><div class="perio-empty-icon">📈</div><h3>${P.empty.title}</h3><p>${P.empty.description}</p>
        <button type="button" class="odo-btn odo-btn-primary" data-act="start"${state.starting ? ' disabled' : ''}>+ ${P.empty.cta}</button></div>`;
    } else if (state.snapshot) {
      const s = state.snapshot;
      const readonly = isReadOnly();
      const upper = s.teeth.filter((t) => Math.floor(t.tooth_number / 10) <= 2);
      const lower = s.teeth.filter((t) => Math.floor(t.tooth_number / 10) >= 3);
      html = `${isViewingHistory() ? `<div class="perio-history-banner"><span>🕘 ${esc(P.history.viewingSession(fmtDateLong(state.viewingDate)))}</span><button type="button" class="odo-btn odo-btn-outline odo-btn-xs" data-act="return-now">${P.history.returnToCurrent}</button></div>` : ''}
        <div data-role="timeline"${state.timeline && state.timeline.dates.length ? '' : ' hidden'}></div>
        <div class="periodontogram-chart">
          <div data-role="banner">${bannerHtml()}</div>
          <div class="perio-scroll" role="region" aria-label="${P.chart.ariaLabel}"><div class="perio-min">
            ${renderArchBlock(upper, 'upper', readonly)}
            ${renderArchBlock(lower, 'lower', readonly)}
          </div></div>
        </div>
        ${!hasDraft() && !isViewingHistory() ? `<div class="perio-card-row"><span class="odonto-muted odonto-small">${P.session.closedCount(closedCount())}</span>
          <button type="button" class="odo-btn odo-btn-primary odo-btn-sm" data-act="open-draft"${state.starting ? ' disabled' : ''}>+ ${P.session.openDraft}</button></div>` : ''}`;
    } else {
      html = '';
    }
    root.innerHTML = `<div class="periodontogram-view">${html}</div>`;
    const tlEl = q('[data-role="timeline"]');
    if (tlEl && state.timeline && state.timeline.dates.length) {
      timeline = createTimeline(tlEl, {
        dates: state.timeline.dates.map((d) => ({ date: d.date, change_count: d.change_count })),
        currentDate: state.viewingDate,
        onChange: (date) => handleDateChange(date),
      });
    }
  }

  function updateBanner() {
    const el = q('[data-role="banner"]');
    if (el && state.snapshot) el.innerHTML = bannerHtml();
  }

  function updateToothVisuals(toothNumber) {
    const s = state.snapshot;
    const tooth = s.teeth.find((t) => t.tooth_number === toothNumber);
    if (!tooth) return;
    root.querySelectorAll(`[data-lateral^="${toothNumber}-"]`).forEach((td) => {
      const face = td.dataset.lateral.split('-')[1];
      td.innerHTML = renderToothLateral(tooth, face, td.dataset.markers);
    });
    const arch = toothNumber < 30 ? 'upper' : 'lower';
    const section = q(`.perio-arch-block[data-arch="${arch}"]`);
    if (section) {
      const ordered = orderedTeeth(s.teeth.filter((t) => (arch === 'upper' ? t.tooth_number < 30 : t.tooth_number >= 30)), arch);
      section.querySelectorAll('[data-strip]').forEach((a) => {
        const face = a.dataset.strip;
        const direction = a.classList.contains('perio-profile-anchor--top') ? 'depth-up' : 'depth-down';
        a.innerHTML = renderStrip(ordered, face, direction);
      });
    }
    updateBanner();
  }

  // ------------------------------------------------------------ data
  async function fetchTimeline() {
    state.timeline = await api.timeline();
  }

  async function fetchSnapshot(id) {
    state.snapshot = await api.snapshot(id);
  }

  async function loadCurrentView() {
    const dates = (state.timeline && state.timeline.dates) || [];
    const latest = dates[dates.length - 1];
    if (hasDraft()) await fetchSnapshot(state.timeline.draft.id);
    else if (latest) await fetchSnapshot(latest.snapshot_id);
    else state.snapshot = null;
    state.viewingDate = null;
  }

  async function refreshAll() {
    state.loading = true; state.error = null;
    if (!state.snapshot) render();
    try {
      await fetchTimeline();
      await loadCurrentView();
    } catch (e) {
      state.error = e.message || 'load_failed';
    }
    state.loading = false;
    render();
  }

  async function handleStart() {
    state.starting = true; render();
    try {
      await api.openDraft();
      await fetchTimeline();
      if (state.timeline.draft) await fetchSnapshot(state.timeline.draft.id);
      state.viewingDate = null;
    } catch (e) {
      toast(e.message || P.errors.saveFailed, { type: 'error' });
    }
    state.starting = false;
    render();
  }

  async function handleDateChange(date) {
    if (date === null) { await loadCurrentView(); render(); return; }
    const entry = state.timeline.dates.find((d) => d.date === date);
    if (!entry) return;
    try {
      await flushPending();
      await fetchSnapshot(entry.snapshot_id);
      state.viewingDate = date;
    } catch (e) {
      toast(e.message || P.errors.loadFailed, { type: 'error' });
    }
    render();
  }

  // ------------------------------------------------------------ autosave
  function schedule(key, patch, exec) {
    state.dirty = true;
    const cur = pending.get(key) || { timer: null, payload: {} };
    cur.payload = { ...cur.payload, ...patch };
    cur.exec = exec;
    clearTimeout(cur.timer);
    cur.timer = setTimeout(() => flushKey(key), DEBOUNCE_MS);
    pending.set(key, cur);
    updateBanner();
  }

  async function flushKey(key) {
    const cur = pending.get(key);
    if (!cur) return;
    pending.delete(key);
    clearTimeout(cur.timer);
    state.saving++;
    updateBanner();
    try {
      await cur.exec(cur.payload);
      if (pending.size === 0) state.dirty = false;
    } catch (e) {
      toast(`${P.errors.saveFailed} ${P.errors.checkConnection}`, { type: 'error' });
    } finally {
      state.saving--;
      updateBanner();
    }
  }

  async function flushPending() {
    const keys = [...pending.keys()];
    for (const k of keys) await flushKey(k);
    state.dirty = false;
  }

  function editSite(toothNumber, code, patch) {
    if (isReadOnly()) return;
    const s = state.snapshot;
    const tooth = s.teeth.find((t) => t.tooth_number === toothNumber);
    if (!tooth) return;
    let site = siteOf(tooth, code);
    if (!site) {
      site = { site_code: code, probing_depth_mm: null, gingival_margin_mm: null, bleeding_on_probing: false, plaque: false, suppuration: false };
      tooth.sites.push(site);
    }
    Object.assign(site, patch);
    const sid = s.id;
    schedule(`site:${toothNumber}:${code}`, patch, (payload) => api.patchSite(sid, toothNumber, code, payload));
    updateToothVisuals(toothNumber);
  }

  function editTooth(toothNumber, patch) {
    if (isReadOnly()) return;
    const s = state.snapshot;
    const tooth = s.teeth.find((t) => t.tooth_number === toothNumber);
    if (!tooth) return;
    Object.assign(tooth, patch);
    const sid = s.id;
    schedule(`tooth:${toothNumber}`, patch, (payload) => api.patchTooth(sid, toothNumber, payload));
  }

  // ------------------------------------------------------------ actions
  function askClose() {
    confirmDialog({
      title: P.session.closeTitle,
      text: P.session.closeDescription,
      confirmLabel: P.session.closeButton,
      cancelLabel: P.session.cancel,
      onConfirm: async () => {
        try {
          await flushPending();
          state.saving++; updateBanner();
          await api.close(state.snapshot.id);
          state.saving--;
          await refreshAll();
        } catch (e) {
          state.saving = Math.max(0, state.saving - 1);
          toast(e.message || P.errors.saveFailed, { type: 'error' });
          updateBanner();
        }
      },
    });
  }

  function askDiscard() {
    confirmDialog({
      title: P.session.discardTitle,
      text: P.session.discardDescription,
      confirmLabel: P.session.discardButton,
      cancelLabel: P.session.cancel,
      danger: true,
      onConfirm: async () => {
        try {
          for (const [, cur] of pending) clearTimeout(cur.timer);
          pending.clear();
          state.dirty = false;
          await api.discard(state.snapshot.id);
          state.snapshot = null;
          await refreshAll();
        } catch (e) {
          toast(e.message || P.errors.saveFailed, { type: 'error' });
        }
      },
    });
  }

  function parseIntOrNull(raw) {
    if (String(raw).trim() === '') return null;
    const n = Number(raw);
    if (!Number.isFinite(n)) return null;
    return Math.round(n);
  }

  function clamp(v, min, max) {
    if (v === null) return null;
    return Math.max(min, Math.min(max, v));
  }

  // ------------------------------------------------------------ events
  function onClick(e) {
    const act = e.target.closest('[data-act]');
    if (!act || !root.contains(act)) return;
    const n = Number(act.dataset.tooth);
    switch (act.dataset.act) {
      case 'retry': refreshAll(); break;
      case 'start':
      case 'open-draft': handleStart(); break;
      case 'return-now': handleDateChange(null); break;
      case 'close-session': askClose(); break;
      case 'discard': askDiscard(); break;
      case 'implant': {
        const tooth = state.snapshot.teeth.find((t) => t.tooth_number === n);
        if (!tooth || isReadOnly()) return;
        editTooth(n, { is_implant: !tooth.is_implant });
        act.classList.toggle('is-implant', tooth.is_implant);
        act.textContent = tooth.is_implant ? '●' : '·';
        act.title = tooth.is_implant ? P.arch.implantToggleOn : P.arch.implantToggleOff;
        updateToothVisuals(n);
        break;
      }
      case 'cycle': {
        const tooth = state.snapshot.teeth.find((t) => t.tooth_number === n);
        if (!tooth || isReadOnly() || !tooth.is_present) return;
        const field = act.dataset.field;
        let next;
        if (field === 'mobility') next = nextInCycle(MOBILITY_CYCLE, tooth.mobility ?? null);
        else if (field === 'prognosis') next = nextInCycle(PROGNOSIS_CYCLE, tooth.prognosis ?? null);
        else next = nextInCycle(FURCA_CYCLE, tooth[field] ?? null);
        editTooth(n, { [field]: next });
        act.textContent = field === 'mobility' ? mobilityGlyph(next) : field === 'prognosis' ? prognosisGlyph(next) : furcaGlyph(next);
        break;
      }
      case 'site-toggle': {
        const tooth = state.snapshot.teeth.find((t) => t.tooth_number === n);
        if (!tooth || isReadOnly() || !tooth.is_present) return;
        const site = siteOf(tooth, act.dataset.site);
        const field = act.dataset.field;
        const value = !(site && site[field]);
        editSite(n, act.dataset.site, { [field]: value });
        act.classList.toggle('is-on', value);
        break;
      }
      default: break;
    }
  }

  function onChange(e) {
    const el = e.target.closest('[data-act="site-num"], [data-act="tooth-num"]');
    if (!el || !root.contains(el)) return;
    const n = Number(el.dataset.tooth);
    const field = el.dataset.field;
    const min = Number(el.min), max = Number(el.max);
    const v = clamp(parseIntOrNull(el.value), min, max);
    el.value = v === null ? '' : v;
    if (el.dataset.act === 'site-num') editSite(n, el.dataset.site, { [field]: v });
    else editTooth(n, { [field]: v });
  }

  function onFocusIn(e) {
    const el = e.target;
    if (el && el.classList && el.classList.contains('perio-cell-input') && el.select) el.select();
  }

  function onBeforeUnload(e) {
    if (state.dirty || state.saving > 0) { e.preventDefault(); e.returnValue = ''; }
  }

  root.addEventListener('click', onClick);
  root.addEventListener('change', onChange);
  root.addEventListener('focusin', onFocusIn);
  window.addEventListener('beforeunload', onBeforeUnload);

  refreshAll();

  return {
    refresh: refreshAll,
    destroy() {
      root.removeEventListener('click', onClick);
      root.removeEventListener('change', onChange);
      root.removeEventListener('focusin', onFocusIn);
      window.removeEventListener('beforeunload', onBeforeUnload);
      if (timeline) timeline.destroy();
      root.innerHTML = '';
    },
  };
}
