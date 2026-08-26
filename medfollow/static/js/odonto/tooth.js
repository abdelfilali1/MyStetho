/**
 * Rendu d'une dent en double vue (port de dentalpin `ToothDualView.vue`) :
 * SVG latéral (racines/implant, couronne, pulpe, icônes) + SVG occlusal
 * (faces, motifs, marqueurs) + indicateur « P » planifié + numéro FDI.
 *
 * `viewsForTooth` aplatit un traitement (en-tête + dents) en vues par dent
 * (port de `utils/treatmentView.ts`).
 */

import {
  OCCLUSAL_VISUALIZATION, PATTERN_CONFIG, PULP_FILL_CONFIG, STATUS_STYLES,
  getTreatmentColor, hasVisualizationRule, normalizeTreatmentType, esc,
} from './constants.js';
import {
  PATTERN_DEFINITIONS, getIconAnchors, getLateralPath, getOcclusalPath, getPatternId,
  getToothDisplayConfig, getToothTransform, implantSvg, isDeciduousTooth, isUpperTooth, makesToothTransparent,
} from './paths.js';

export function viewForTooth(treatment, toothNumber) {
  const member = (treatment.teeth || []).find((t) => t.tooth_number === toothNumber);
  if (!member) return null;
  return {
    id: `${treatment.id}:${member.id}`,
    treatment_id: treatment.id,
    tooth_number: toothNumber,
    treatment_type: treatment.clinical_type,
    clinical_type: treatment.clinical_type,
    surfaces: member.surfaces || null,
    role: member.role || null,
    status: treatment.status,
    recorded_at: treatment.recorded_at,
    performed_at: treatment.performed_at,
    performed_by: treatment.performed_by,
    performed_by_name: treatment.performed_by_name,
    created_at: treatment.created_at,
    is_multi: (treatment.teeth || []).length > 1,
    teeth_count: (treatment.teeth || []).length,
  };
}

export function viewsForTooth(treatments, toothNumber) {
  const out = [];
  for (const t of treatments) {
    const v = viewForTooth(t, toothNumber);
    if (v) out.push(v);
  }
  return out;
}

const SOLID_CROWN_FILL_TYPES = ['bridge', 'crown_on_implant', 'provisional_crown_on_implant'];
const ORTHO_TYPES = ['bracket', 'tube', 'band', 'attachment', 'retainer'];

function opacityOf(t) {
  return (STATUS_STYLES[t.status] && STATUS_STYLES[t.status].opacity) || 1;
}

/**
 * @param {object} o
 * @param {number} o.toothNumber
 * @param {string} o.generalCondition
 * @param {Array} o.treatments  vues par dent (viewsForTooth)
 * @param {boolean} [o.selected]
 * @param {boolean} [o.readonly]
 * @param {boolean} [o.isDisplaced]
 * @param {boolean} [o.isRotated]
 * @param {boolean} [o.isHovered]
 * @param {boolean} [o.isHighlighted]
 * @param {{type:string,status:string}|null} [o.pendingTreatment]
 */
export function renderTooth(o) {
  const n = o.toothNumber;
  const treatments = o.treatments || [];
  const upper = isUpperTooth(n);
  const deciduous = isDeciduousTooth(n);
  const lateral = getLateralPath(n);
  const occlusal = getOcclusalPath(n);
  const transform = getToothTransform(n);
  const cfg = getToothDisplayConfig(n);

  const vb = lateral.viewBox.split(' ').map(Number);
  const vbX = vb[0] || 0, vbY = vb[1] || 0, vbW = vb[2] || 60, vbH = vb[3] || 130;
  const displayWidth = Math.round(55 * cfg.scale);
  const displayHeight = Math.round(displayWidth / (vbW / vbH));

  const has = (type) => treatments.some((t) => t.treatment_type === type);
  const first = (type) => treatments.find((t) => t.treatment_type === type);

  const hasReplacement = treatments.some((t) =>
    t.treatment_type === 'implant' || t.treatment_type === 'bridge' || t.treatment_type === 'crown_on_implant'
    || t.treatment_type === 'provisional_crown_on_implant' || hasVisualizationRule(t.treatment_type, 'pattern_fill'));

  let transparent = false;
  if (!hasReplacement) {
    if (o.generalCondition === 'missing' || o.generalCondition === 'extraction_indicated') transparent = true;
    else transparent = treatments.some((t) => makesToothTransparent(t.treatment_type) && t.status === 'existing');
  }
  const toothOpacity = transparent ? 0.25 : 1;

  const hasImplant = has('implant');
  const bridge = first('bridge');
  const isPontic = !!(bridge && bridge.role === 'pontic');
  const crownFill = treatments.find((t) => SOLID_CROWN_FILL_TYPES.includes(t.treatment_type));

  const pulpTreatments = treatments.filter((t) => hasVisualizationRule(t.treatment_type, 'pulp_fill'));
  const pulpTreatment = pulpTreatments[0];
  const pulpCfg = pulpTreatment ? PULP_FILL_CONFIG[normalizeTreatmentType(pulpTreatment.treatment_type)] : null;
  const pulpLevel = (pulpCfg && pulpCfg.level) || 'full';
  const needsPulpClip = !!pulpTreatment && pulpLevel !== 'full';
  const pulpClipId = `pulp-clip-${n}`;
  let pulpClipY = vbY, pulpClipH = vbH;
  if (pulpLevel === 'half') { pulpClipY = vbY + vbH * 0.35; pulpClipH = vbH * 0.5; }
  else if (pulpLevel === 'two_thirds') { pulpClipY = vbY + vbH * 0.2; pulpClipH = vbH * 0.7; }

  const anchors = getIconAnchors(n);
  const lateralIconTreatments = treatments.filter((t) => hasVisualizationRule(t.treatment_type, 'lateral_icon') && t.treatment_type !== 'implant');
  const occlusalSurfaceTreatments = treatments.filter((t) => hasVisualizationRule(t.treatment_type, 'occlusal_surface'));
  const patternFillTreatments = treatments.filter((t) => hasVisualizationRule(t.treatment_type, 'pattern_fill'));
  const wholeToothOther = treatments.filter((t) =>
    !hasVisualizationRule(t.treatment_type, 'occlusal_surface')
    && !hasVisualizationRule(t.treatment_type, 'pattern_fill')
    && !ORTHO_TYPES.includes(t.treatment_type)
    && !['implant', 'bridge', 'crown_on_implant', 'provisional_crown_on_implant'].includes(t.treatment_type)
    && !hasVisualizationRule(t.treatment_type, 'pulp_fill')
    && !hasVisualizationRule(t.treatment_type, 'lateral_icon'));

  const hasPlannedOcclusal = treatments.some((t) => t.status === 'planned'
    && (hasVisualizationRule(t.treatment_type, 'occlusal_surface') || hasVisualizationRule(t.treatment_type, 'pattern_fill')));
  const hasPlannedLateral = treatments.some((t) => t.status === 'planned'
    && (hasVisualizationRule(t.treatment_type, 'pulp_fill') || hasVisualizationRule(t.treatment_type, 'lateral_icon')));

  const showingPreview = !!(o.isHovered && o.pendingTreatment);

  // ------------------------------------------------------------ latéral
  let lat = '';
  if (needsPulpClip) {
    lat += `<defs><clipPath id="${pulpClipId}"><rect x="${vbX}" y="${pulpClipY}" width="${vbW}" height="${pulpClipH}"/></clipPath></defs>`;
  }
  if (!hasImplant && !isPontic) {
    lat += `<g class="roots" opacity="${toothOpacity}">`;
    if (lateral.root) {
      lat += `<path d="${lateral.root}" class="tooth-root" stroke-width="0.6" stroke-linecap="round" stroke-linejoin="round"/>`;
    } else if (lateral.roots) {
      for (const r of lateral.roots) lat += `<path d="${r}" class="tooth-root" stroke-width="0.6" stroke-linecap="round" stroke-linejoin="round"/>`;
    }
    lat += '</g>';
  }
  if (hasImplant) {
    const impl = first('implant');
    lat += `<g class="implant-root">${implantSvg(lateral.viewBox, getTreatmentColor('implant'), opacityOf(impl))}</g>`;
  }
  lat += '<g class="crown">';
  lat += `<path d="${lateral.crown}" class="tooth-crown" stroke-width="0.6" stroke-linecap="round" stroke-linejoin="round" opacity="${toothOpacity}"/>`;
  if (crownFill) {
    lat += `<path d="${lateral.crown}" fill="${getTreatmentColor(crownFill.treatment_type)}" fill-opacity="${opacityOf(crownFill)}" stroke="none" class="bridge-crown-fill"/>`;
  }
  if (lateral.pulp && !hasImplant && !pulpTreatment && !crownFill) {
    lat += `<path d="${lateral.pulp}" class="tooth-pulp" fill="none" stroke-width="0.5" stroke-linecap="round" stroke-linejoin="round" opacity="${toothOpacity}"/>`;
  }
  if (lateral.pulp && pulpTreatment && !hasImplant && needsPulpClip && !crownFill) {
    lat += `<path d="${lateral.pulp}" class="tooth-pulp" fill="none" stroke-width="0.5" stroke-linecap="round" stroke-linejoin="round" opacity="${toothOpacity}"/>`;
  }
  if (pulpTreatment && !hasImplant && !crownFill) {
    const color = (pulpCfg && pulpCfg.color) || getTreatmentColor(pulpTreatment.treatment_type);
    lat += `<path d="${lateral.pulp}" class="tooth-pulp pulp-filled" fill="${color}" fill-opacity="${opacityOf(pulpTreatment)}" stroke="none"${needsPulpClip ? ` clip-path="url(#${pulpClipId})"` : ''}/>`;
  }
  for (const h of lateral.highlight || []) {
    lat += `<path d="${h}" class="tooth-highlight" stroke-width="0.35" stroke-linecap="round" stroke-linejoin="round" fill="none" opacity="${toothOpacity}"/>`;
  }
  lat += '</g>';

  lat += '<g class="treatment-overlays-lateral">';
  if (has('post')) {
    const p = first('post');
    lat += `<path d="M 28,35 L 28,60 L 32,60 L 32,35 Z" fill="${getTreatmentColor('post')}" opacity="${opacityOf(p)}" stroke="#6B7280" stroke-width="0.5"/>`;
  }
  for (const t of lateralIconTreatments) {
    const type = t.treatment_type;
    const color = getTreatmentColor(type);
    const op = opacityOf(t);
    if (!anchors) continue;
    const cc = anchors.crownCenter;
    if (type === 'root_canal_overfill') {
      lat += `<circle cx="${anchors.apex.x}" cy="${anchors.apex.y}" r="6" fill="${color}" fill-opacity="${op}" stroke="${color}" stroke-width="1"/>`;
    } else if ((type === 'extraction' || type === 'missing') && !hasReplacement) {
      lat += `<g transform="translate(${cc.x}, ${cc.y})" opacity="${type === 'missing' ? 0.5 : op}">
        <line x1="-20" y1="-20" x2="20" y2="20" stroke="${color}" stroke-width="5" stroke-linecap="round"/>
        <line x1="20" y1="-20" x2="-20" y2="20" stroke="${color}" stroke-width="5" stroke-linecap="round"/></g>`;
    } else if (type.startsWith('periapical_')) {
      const dy = type === 'periapical_large' ? 12 : type === 'periapical_medium' ? 8 : 4;
      const r = type === 'periapical_large' ? 16 : type === 'periapical_medium' ? 10 : 6;
      lat += `<circle cx="${anchors.apex.x}" cy="${anchors.apex.y - dy}" r="${r}" fill="${color}" fill-opacity="${0.7 * op}" stroke="${color}" stroke-width="1"/>`;
    } else if (type === 'fracture') {
      lat += `<path d="M ${cc.x - 6},${cc.y - 16} L ${cc.x},${cc.y - 8} L ${cc.x - 4},${cc.y} L ${cc.x + 2},${cc.y + 8} L ${cc.x - 2},${cc.y + 16}" fill="none" stroke="${color}" stroke-width="3" stroke-opacity="${op}" stroke-linecap="round" stroke-linejoin="round"/>`;
    } else if (type === 'apicoectomy') {
      lat += `<line x1="${anchors.apex.x - 16}" y1="${anchors.apex.y + 4}" x2="${anchors.apex.x + 16}" y2="${anchors.apex.y + 4}" stroke="${color}" stroke-width="4" stroke-opacity="${op}" stroke-linecap="round"/>`;
    } else if (type === 'rotated') {
      lat += `<g transform="translate(${cc.x}, ${cc.y})"><path d="M 9,0 A 9,9 0 1,1 0,-9 C 2.52,-9 4.93,-8 6.74,-6.26 L 9,-4 M 9,-9 V -4 H 4" fill="none" stroke="${color}" stroke-width="2" stroke-opacity="${op}" stroke-linecap="round" stroke-linejoin="round"/></g>`;
    } else if (type === 'displaced') {
      const bc = anchors.besideCrown;
      lat += `<g transform="translate(${bc.x}, ${bc.y})"><path d="M -16,0 L 16,0" fill="none" stroke="${color}" stroke-width="3" stroke-opacity="${op}" stroke-linecap="round"/><path d="M 10,-6 L 16,0 L 10,6" fill="none" stroke="${color}" stroke-width="3" stroke-opacity="${op}" stroke-linecap="round" stroke-linejoin="round"/></g>`;
    } else if (type === 'post') {
      const rc = anchors.rootCenter;
      lat += `<rect x="${rc.x - 4}" y="${rc.y - 15}" width="8" height="50" rx="2" fill="${color}" fill-opacity="${op}"/>`;
    } else if (ORTHO_TYPES.includes(type)) {
      lat += `<g transform="translate(${cc.x}, ${cc.y})">`;
      if (type === 'bracket') {
        lat += `<rect x="-8" y="-8" width="16" height="16" fill="${color}" fill-opacity="${0.8 * op}"/><line x1="-12" y1="0" x2="12" y2="0" stroke="${color}" stroke-width="2"/>`;
      } else if (type === 'tube') {
        lat += `<rect x="-10" y="-6" width="20" height="12" rx="2" fill="${color}" fill-opacity="${0.8 * op}"/><circle cx="0" cy="0" r="3" fill="white"/>`;
      } else if (type === 'band') {
        lat += `<line x1="-16" y1="-4" x2="16" y2="-4" stroke="${color}" stroke-width="3"/><line x1="-16" y1="4" x2="16" y2="4" stroke="${color}" stroke-width="3"/>`;
      } else if (type === 'attachment') {
        lat += `<ellipse cx="0" cy="0" rx="8" ry="6" fill="${color}" fill-opacity="${op}"/>`;
      } else if (type === 'retainer') {
        lat += `<path d="M -20,0 Q -14,-6 -8,0 Q -2,6 4,0 Q 10,-6 16,0" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round"/>`;
      }
      lat += '</g>';
    } else if (type === 'splint') {
      lat += `<line x1="0" y1="${cc.y}" x2="${vbW}" y2="${cc.y}" stroke="${color}" stroke-width="3" stroke-opacity="${op}" stroke-linecap="round"/>`;
    }
  }
  lat += '</g>';

  // ------------------------------------------------------------ occlusal
  let occ = PATTERN_DEFINITIONS;
  occ += '<rect x="0" y="0" width="50" height="50" fill="transparent" pointer-events="none"/>';
  occ += `<path d="${occlusal.outline}" class="tooth-occlusal" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" pointer-events="none" opacity="${toothOpacity}"/>`;
  for (const h of occlusal.highlight) {
    occ += `<path d="${h}" class="tooth-highlight" stroke-width="0.6" stroke-linecap="round" stroke-linejoin="round" fill="none" pointer-events="none" opacity="${toothOpacity}"/>`;
  }
  occ += '<g class="treatment-overlays">';
  const dotPos = { O: [25, 25], M: [12, 25], D: [38, 25], V: [25, 12], L: [25, 38] };
  for (const t of occlusalSurfaceTreatments) {
    const cfgO = OCCLUSAL_VISUALIZATION[normalizeTreatmentType(t.treatment_type)];
    const color = getTreatmentColor(t.treatment_type);
    const op = opacityOf(t);
    const surfaces = t.surfaces && t.surfaces.length ? t.surfaces : null;
    const kind = cfgO ? cfgO.type : 'solid_fill';
    if (kind === 'solid_fill') {
      for (const s of surfaces || ['O']) {
        if (occlusal.surfaces[s]) occ += `<path d="${occlusal.surfaces[s]}" fill="${color}" fill-opacity="${op}" stroke="none" class="treatment-surface-overlay"/>`;
      }
    } else if (kind === 'dot') {
      for (const s of surfaces || ['O']) {
        const [cx, cy] = dotPos[s] || [25, 25];
        occ += `<circle cx="${cx}" cy="${cy}" r="4" fill="${color}" fill-opacity="${op}" class="treatment-dot-overlay"/>`;
      }
    } else if (kind === 'outline') {
      for (const s of surfaces || ['O']) {
        if (occlusal.surfaces[s]) occ += `<path d="${occlusal.surfaces[s]}" fill="none" stroke="${color}" stroke-width="1.5" stroke-opacity="${op}" class="treatment-outline-overlay"/>`;
      }
    }
  }
  for (const t of patternFillTreatments) {
    const pid = getPatternId(t.treatment_type);
    const color = getTreatmentColor(t.treatment_type);
    occ += `<path d="${occlusal.outline}" fill="${pid ? `url(#${pid})` : color}" fill-opacity="${opacityOf(t)}" stroke="${color}" stroke-width="1.5" class="pattern-fill-overlay"/>`;
  }
  for (const t of wholeToothOther) {
    const color = getTreatmentColor(t.treatment_type);
    occ += `<g class="whole-tooth-indicator"><path d="${occlusal.outline}" fill="${color}" fill-opacity="${opacityOf(t) * 0.4}" stroke="${color}" stroke-width="2"/></g>`;
  }
  occ += '</g>';
  if (o.generalCondition === 'missing' && !hasReplacement) {
    occ += `<g class="missing-indicator" pointer-events="none"><line x1="8" y1="8" x2="42" y2="42" stroke="#6B7280" stroke-width="2.5" stroke-linecap="round"/><line x1="42" y1="8" x2="8" y2="42" stroke="#6B7280" stroke-width="2.5" stroke-linecap="round"/></g>`;
  }
  if (o.generalCondition === 'extraction_indicated' && !hasReplacement) {
    occ += `<g class="extraction-indicator" pointer-events="none"><line x1="10" y1="10" x2="40" y2="40" stroke="#DC2626" stroke-width="2" stroke-dasharray="5,3" stroke-linecap="round"/><line x1="40" y1="10" x2="10" y2="40" stroke="#DC2626" stroke-width="2" stroke-dasharray="5,3" stroke-linecap="round"/></g>`;
  }
  if (showingPreview) {
    occ += `<g class="preview-overlay" opacity="0.5" pointer-events="none"><path d="${occlusal.outline}" fill="${getTreatmentColor(o.pendingTreatment.type)}" stroke="var(--odontogram-selected)" stroke-width="2"/></g>`;
  }
  if (o.selected) {
    occ += `<path d="${occlusal.outline}" fill="none" stroke="var(--odontogram-selected)" stroke-width="2.5" class="selection-ring" pointer-events="none"/>`;
  }

  const classes = ['tooth-dual-view-wrapper', upper ? 'is-upper' : 'is-lower'];
  if (o.selected) classes.push('selected');
  if (o.readonly) classes.push('readonly');
  if (o.isDisplaced) classes.push('displaced');
  if (o.isRotated) classes.push('rotated');
  if (o.isHighlighted) classes.push('highlighted');
  if (showingPreview) classes.push('has-preview');
  if (deciduous) classes.push('is-deciduous');

  const transformStyle = transform ? ` style="transform:${transform};transform-origin:center center"` : '';

  return `<div class="${classes.join(' ')}" data-tooth="${n}">
  <div class="lateral-view-container ${upper ? 'upper' : 'lower'}">
    <svg width="${displayWidth}" height="${displayHeight}" viewBox="${esc(lateral.viewBox)}" class="lateral-view"${transformStyle}>${lat}</svg>
    ${hasPlannedLateral ? '<div class="planned-indicator-lateral"><span class="planned-p">P</span></div>' : ''}
  </div>
  <div class="occlusal-view-container">
    <svg width="55" height="55" viewBox="0 0 50 50" class="occlusal-view"${transformStyle}>${occ}</svg>
    ${hasPlannedOcclusal ? '<div class="planned-indicator-occlusal"><span class="planned-p">P</span></div>' : ''}
  </div>
  <div class="tooth-number${o.selected ? ' selected' : ''}">${n}</div>
</div>`;
}
