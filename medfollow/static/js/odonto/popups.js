/**
 * Modales et infobulle de l'odontogramme (port de dentalpin
 * `SurfaceSelectorPopup`, `TreatmentEditModal`, `MultiToothConfirmPopup`, `ToothTooltip`).
 */

import {
  SURFACES, T, esc, formatDate, getAllowedStatusesForTreatment, getTreatmentColor,
  isSurfaceTreatment, toothName, typeLabel,
} from './constants.js';
import { getLateralPath, getOcclusalPath, getToothTransform } from './paths.js';

// ============================================================================
// Modale générique
// ============================================================================

export function openModal({ title, subtitle, body, footer, className = '', onClose, closeOnOverlay = true }) {
  const overlay = document.createElement('div');
  overlay.className = 'odonto-modal-overlay';
  overlay.innerHTML = `<div class="odonto-modal ${className}" role="dialog" aria-modal="true">
    ${title !== undefined ? `<div class="odonto-modal-header"><div class="odonto-modal-heading">${title}${subtitle ? `<p class="odonto-modal-subtitle">${subtitle}</p>` : ''}</div>
      <button type="button" class="odonto-modal-close" data-act="close" aria-label="Fermer">✕</button></div>` : ''}
    <div class="odonto-modal-body">${body || ''}</div>
    ${footer ? `<div class="odonto-modal-footer">${footer}</div>` : ''}
  </div>`;
  document.body.appendChild(overlay);
  document.body.classList.add('odonto-modal-open');
  let closed = false;

  function close() {
    if (closed) return;
    closed = true;
    document.removeEventListener('keydown', onKey);
    overlay.remove();
    if (!document.querySelector('.odonto-modal-overlay')) document.body.classList.remove('odonto-modal-open');
    if (onClose) onClose();
  }

  function onKey(e) {
    if (e.key === 'Escape') { e.stopPropagation(); close(); }
  }

  overlay.addEventListener('click', (e) => {
    if (e.target.closest('[data-act="close"]')) { close(); return; }
    if (closeOnOverlay && e.target === overlay) close();
  });
  document.addEventListener('keydown', onKey);
  return { el: overlay, modal: overlay.firstElementChild, close };
}

export function confirmDialog({ title, text, confirmLabel = T.common.confirm, cancelLabel = T.common.cancel, danger = false, onConfirm }) {
  const m = openModal({
    title: esc(title),
    body: `<p class="odonto-muted">${esc(text)}</p>`,
    footer: `<button type="button" class="odo-btn odo-btn-outline" data-act="close">${esc(cancelLabel)}</button>
      <button type="button" class="odo-btn ${danger ? 'odo-btn-danger' : 'odo-btn-primary'}" data-act="confirm">${esc(confirmLabel)}</button>`,
    className: 'odonto-modal-sm',
  });
  m.el.querySelector('[data-act="confirm"]').addEventListener('click', async () => {
    m.close();
    await onConfirm();
  });
  return m;
}

// ============================================================================
// Sélecteur de faces
// ============================================================================

export function openSurfaceSelector({ toothNumber, treatmentType, status, onConfirm, onCancel }) {
  const selected = new Set();
  const occlusal = getOcclusalPath(toothNumber);
  const lateral = getLateralPath(toothNumber);
  const transform = getToothTransform(toothNumber);
  const q = Math.floor(toothNumber / 10);
  const isLeft = [2, 3, 6, 7].includes(q);
  const isLower = [3, 4, 7, 8].includes(q);
  const color = getTreatmentColor(treatmentType);

  let groupTransform = '';
  if (isLeft && isLower) groupTransform = 'translate(50, 50) scale(-1, -1)';
  else if (isLeft) groupTransform = 'translate(50, 0) scale(-1, 1)';
  else if (isLower) groupTransform = 'translate(0, 50) scale(1, -1)';
  const mX = isLeft ? 43 : 4, dX = isLeft ? 4 : 43, vY = isLower ? 47 : 8, lY = isLower ? 8 : 47;

  // Vue latérale rognée sur la couronne
  const vb = lateral.viewBox.split(' ').map(Number);
  const vbW = vb[2] || 60, vbH = vb[3] || 100;
  const match = lateral.gumLine.match(/M\s*\d+(?:\.\d+)?\s*,\s*(\d+(?:\.\d+)?)/);
  const gumY = match ? parseFloat(match[1]) : vbH * 0.65;
  const cropY = Math.max(0, gumY - 6);
  const cropH = vbH - cropY + 4;
  const latW = 160, latH = Math.round(latW / (vbW / cropH));

  function bodyHtml() {
    const fill = (s) => (selected.has(s) ? (status === 'planned' ? 'url(#surface-pattern)' : color) : 'var(--odontogram-fill)');
    const surfacePaths = SURFACES.map((s) => `<path d="${occlusal.surfaces[s]}" fill="${fill(s)}" opacity="${selected.has(s) ? 0.8 : 1}" stroke="${selected.has(s) ? color : 'var(--odontogram-outline-light)'}" stroke-width="${selected.has(s) ? 2 : 0.5}" stroke-linecap="round" stroke-linejoin="round" class="surface-path" data-surface="${s}"/>`).join('');
    const buttons = SURFACES.map((s) => `<button type="button" class="surface-btn${selected.has(s) ? ' selected' : ''}" data-surface="${s}"${selected.has(s) ? ` style="border-color:${color};background:${color}15"` : ''}>
      <span class="surface-letter">${s}</span><span class="surface-name">${T.surfaces[s]}</span></button>`).join('');
    const summary = selected.size ? `<div class="selected-summary"><span class="summary-label">${T.selectedSurfaces} :</span><div class="summary-badges">${[...selected].map((s) => `<span class="summary-badge" style="background:${color}20;color:${color}">${s} - ${T.surfaces[s]}</span>`).join('')}</div></div>` : '';
    return `<div class="surface-selector">
      <div class="tooth-views">
        <div class="view-container"><div class="view-label">${T.views.occlusal}</div>
          <svg width="160" height="160" viewBox="0 0 50 50" class="tooth-svg">
            <defs><pattern id="surface-pattern" patternUnits="userSpaceOnUse" width="4" height="4" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4" stroke="${color}" stroke-width="2"/></pattern></defs>
            <g transform="${groupTransform}">
              <path d="${occlusal.outline}" fill="var(--odontogram-fill-shade)" stroke="var(--odontogram-outline)" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>
              ${occlusal.highlight.map((h) => `<path d="${h}" fill="none" stroke="var(--odontogram-detail)" stroke-width="0.75" stroke-linecap="round" pointer-events="none"/>`).join('')}
              ${surfacePaths}
            </g>
            <text x="${mX}" y="27" class="surface-label" data-surface="M">M</text>
            <text x="${dX}" y="27" class="surface-label" data-surface="D">D</text>
            <text x="24" y="${vY}" class="surface-label" data-surface="V">V</text>
            <text x="24" y="${lY}" class="surface-label" data-surface="L">L</text>
            <text x="24" y="28" class="surface-label-center" data-surface="O">O</text>
          </svg></div>
        <div class="view-container"><div class="view-label">${T.views.lateral}</div>
          <svg width="${latW}" height="${latH}" viewBox="0 ${cropY} ${vbW} ${cropH}" class="tooth-svg lateral" style="transform:${transform};transform-origin:center center">
            <path d="${lateral.gumLine}" fill="none" stroke="var(--odontogram-gum)" stroke-width="1.5"/>
            <path d="${lateral.crown}" fill="var(--odontogram-fill)" stroke="var(--odontogram-outline)" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>
          </svg></div>
      </div>
      <div class="surface-buttons">${buttons}</div>
      ${summary}
      <div class="tooth-info">ℹ ${esc(toothName(toothNumber))}</div>
    </div>`;
  }

  const m = openModal({
    title: `<div class="odonto-title-row"><span class="odonto-color-chip" style="background:${color}20"><span style="background:${color}"></span></span><div><h3>${T.selectSurfaces}</h3></div></div>`,
    subtitle: `${esc(typeLabel(treatmentType))} - ${T.tooth} ${toothNumber}`,
    body: bodyHtml(),
    footer: `<span class="odonto-muted odonto-small" data-role="count">0 ${T.surfacesSelected}</span>
      <div class="odonto-actions"><button type="button" class="odo-btn odo-btn-ghost" data-act="cancel">${T.common.cancel}</button>
      <button type="button" class="odo-btn odo-btn-primary" data-act="confirm" disabled>${T.common.confirm}</button></div>`,
    className: 'odonto-modal-lg',
    onClose: () => { if (!confirmed && onCancel) onCancel(); },
  });
  let confirmed = false;
  const bodyEl = m.el.querySelector('.odonto-modal-body');
  const countEl = m.el.querySelector('[data-role="count"]');
  const confirmBtn = m.el.querySelector('[data-act="confirm"]');

  function refresh() {
    bodyEl.innerHTML = bodyHtml();
    countEl.textContent = `${selected.size} ${T.surfacesSelected}`;
    confirmBtn.disabled = selected.size === 0;
  }

  bodyEl.addEventListener('click', (e) => {
    const t = e.target.closest('[data-surface]');
    if (!t) return;
    const s = t.dataset.surface;
    if (selected.has(s)) selected.delete(s); else selected.add(s);
    refresh();
  });
  m.el.querySelector('[data-act="cancel"]').addEventListener('click', () => m.close());
  confirmBtn.addEventListener('click', () => {
    if (!selected.size) return;
    confirmed = true;
    const list = SURFACES.filter((s) => selected.has(s));
    m.close();
    onConfirm(list);
  });
  return m;
}

// ============================================================================
// Modale d'édition d'un traitement
// ============================================================================

export function openTreatmentEditModal({ treatment, onUpdate, onDelete, onPerform }) {
  let status = treatment.status;
  const surfaces = new Set(treatment.surfaces || []);
  const surfaceType = isSurfaceTreatment(treatment.treatment_type);
  const color = getTreatmentColor(treatment.treatment_type);
  const allowed = getAllowedStatusesForTreatment(treatment.treatment_type);

  function bodyHtml() {
    const statusBtns = allowed.map((s) => `<button type="button" class="odo-btn odo-btn-sm ${status === s ? (s === 'planned' ? 'odo-btn-warning' : 'odo-btn-dark') : 'odo-btn-outline'}" data-status="${s}">${T.status[s]}</button>`).join('');
    const surf = surfaceType ? `<div class="odonto-field"><label>${T.selectSurfaces}</label><div class="odonto-actions wrap">
      ${SURFACES.map((s) => `<button type="button" class="odo-btn odo-btn-sm ${surfaces.has(s) ? 'odo-btn-primary' : 'odo-btn-outline'}" data-surface="${s}">${s} - ${T.surfaces[s]}</button>`).join('')}
      </div>${surfaces.size ? `<p class="odonto-muted odonto-small">${surfaces.size} ${T.surfacesSelected}</p>` : ''}</div>` : '';
    const perform = treatment.status === 'planned' ? `<div class="odonto-field odonto-field-sep"><button type="button" class="odo-btn odo-btn-success odo-btn-block" data-act="perform">✓ ${T.treatments.markPerformed}</button></div>` : '';
    return `<div class="odonto-field"><label>${T.treatments.selectStatus}</label><div class="odonto-actions">${statusBtns}</div></div>${surf}${perform}`;
  }

  const m = openModal({
    title: `<div class="odonto-title-row"><span class="odonto-dot" style="background:${color}"></span><span class="odonto-strong">${esc(typeLabel(treatment.treatment_type))}</span>
      <span class="odo-badge ${status === 'planned' ? 'odo-badge-warning' : 'odo-badge-neutral'}">${T.tooth} ${treatment.tooth_number}${treatment.is_multi ? ` (+${treatment.teeth_count - 1})` : ''}</span></div>`,
    body: bodyHtml(),
    footer: `<button type="button" class="odo-btn odo-btn-ghost odo-btn-danger-text" data-act="delete">🗑 ${T.common.delete}</button>
      <div class="odonto-actions"><button type="button" class="odo-btn odo-btn-outline" data-act="close">${T.common.cancel}</button>
      <button type="button" class="odo-btn odo-btn-primary" data-act="save">${T.common.save}</button></div>`,
  });
  const bodyEl = m.el.querySelector('.odonto-modal-body');
  bodyEl.addEventListener('click', async (e) => {
    const sb = e.target.closest('[data-status]');
    if (sb) { status = sb.dataset.status; bodyEl.innerHTML = bodyHtml(); return; }
    const sf = e.target.closest('[data-surface]');
    if (sf) { const s = sf.dataset.surface; if (surfaces.has(s)) surfaces.delete(s); else surfaces.add(s); bodyEl.innerHTML = bodyHtml(); return; }
    if (e.target.closest('[data-act="perform"]')) { m.close(); await onPerform(treatment.treatment_id); }
  });
  m.el.querySelector('[data-act="delete"]').addEventListener('click', async () => { m.close(); await onDelete(treatment.treatment_id); });
  m.el.querySelector('[data-act="save"]').addEventListener('click', async () => {
    const data = {};
    if (status !== treatment.status) data.status = status;
    const newSurfaces = SURFACES.filter((s) => surfaces.has(s));
    const oldSurfaces = treatment.surfaces || [];
    if (surfaceType && newSurfaces.join(',') !== oldSurfaces.join(',')) data.surfaces = newSurfaces;
    m.close();
    if (Object.keys(data).length) await onUpdate(treatment.treatment_id, data);
  });
  return m;
}

// ============================================================================
// Confirmation multi-dents
// ============================================================================

export function openMultiToothConfirm({ config, teeth, status, onConfirm, onCancel }) {
  const isBridge = config.mode === 'bridge';
  const sorted = [...teeth].sort((a, b) => a - b);
  const roles = {};
  if (isBridge) {
    const first = sorted[0], last = sorted[sorted.length - 1];
    for (const n of sorted) roles[n] = sorted.length === 1 || n === first || n === last ? 'pillar' : 'pontic';
  }
  let confirmed = false;

  function badges() {
    return sorted.map((n) => {
      const role = isBridge ? roles[n] : null;
      return `<button type="button" class="odo-badge odo-badge-lg ${role === 'pillar' ? 'odo-badge-primary' : 'odo-badge-neutral'}${isBridge ? ' clickable' : ''}" data-tooth="${n}">${n}${role ? ` <span class="odonto-small odonto-muted">(${T.multiTooth[role]})</span>` : ''}</button>`;
    }).join('');
  }

  const m = openModal({
    title: `<h3>${esc(config.label)}</h3>`,
    body: `<p class="odonto-muted">${T.multiTooth.confirmHint(teeth.length)}</p>
      ${isBridge ? `<p class="odonto-small odonto-muted">${T.multiTooth.roleHint}</p>` : ''}
      <div class="odonto-actions wrap" data-role="badges">${badges()}</div>
      <p class="odonto-small odonto-muted">${status === 'planned' ? T.multiTooth.willBePlanned : T.multiTooth.willBeExisting}</p>`,
    footer: `<button type="button" class="odo-btn odo-btn-ghost" data-act="cancel">${T.common.cancel}</button>
      <button type="button" class="odo-btn odo-btn-primary" data-act="confirm">${T.common.confirm}</button>`,
    className: 'odonto-modal-sm',
    onClose: () => { if (!confirmed && onCancel) onCancel(); },
  });
  const badgesEl = m.el.querySelector('[data-role="badges"]');
  badgesEl.addEventListener('click', (e) => {
    const b = e.target.closest('[data-tooth]');
    if (!b || !isBridge) return;
    const n = Number(b.dataset.tooth);
    roles[n] = roles[n] === 'pillar' ? 'pontic' : 'pillar';
    badgesEl.innerHTML = badges();
  });
  m.el.querySelector('[data-act="cancel"]').addEventListener('click', () => m.close());
  function confirm() {
    if (isBridge) {
      if (!Object.values(roles).some((r) => r === 'pillar')) {
        import('./api.js').then(({ toast }) => toast(T.multiTooth.needPillar, { type: 'warning' }));
        return;
      }
      confirmed = true;
      m.close();
      onConfirm(sorted.map((n) => ({ tooth_number: n, role: roles[n] || 'pontic' })));
    } else {
      confirmed = true;
      m.close();
      onConfirm(null);
    }
  }
  m.el.querySelector('[data-act="confirm"]').addEventListener('click', confirm);
  m.el.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); confirm(); } });
  m.el.querySelector('[data-act="confirm"]').focus();
  return m;
}

// ============================================================================
// Infobulle de dent (survol)
// ============================================================================

export function createTooltipManager(rootEl, { getTreatments, onEdit, enabled }) {
  let tip = null;
  let openTimer = null;
  let closeTimer = null;
  let currentTooth = null;

  function ensureTip() {
    if (tip) return tip;
    tip = document.createElement('div');
    tip.className = 'odonto-tooltip';
    tip.addEventListener('mouseenter', () => clearTimeout(closeTimer));
    tip.addEventListener('mouseleave', scheduleClose);
    tip.addEventListener('click', (e) => {
      const item = e.target.closest('[data-view]');
      if (!item) return;
      e.stopPropagation();
      const views = getTreatments(currentTooth);
      const v = views.find((x) => x.id === item.dataset.view);
      hide();
      if (v && onEdit) onEdit(v);
    });
    document.body.appendChild(tip);
    return tip;
  }

  function contentHtml(n) {
    const views = getTreatments(n);
    const planned = views.filter((v) => v.status === 'planned');
    const existing = views.filter((v) => v.status === 'existing');
    const item = (v) => `<div class="treatment-item" data-view="${esc(v.id)}"><div class="treatment-main">
      <span class="treatment-dot" style="background:${getTreatmentColor(v.treatment_type)}"></span>
      <span class="treatment-name">${esc(typeLabel(v.treatment_type))}${v.role ? ` <span class="odonto-muted odonto-small">(${T.multiTooth[v.role]})</span>` : ''}</span>
      ${v.surfaces && v.surfaces.length ? `<span class="odo-badge odo-badge-neutral odo-badge-xs">${v.surfaces.join('-')}</span>` : ''}</div>
      ${v.performed_at ? `<div class="treatment-date">${esc(formatDate(v.performed_at))}</div>` : ''}</div>`;
    let html = `<div class="tooltip-header"><span class="tooth-number-badge">${n}</span><span class="tooth-name">${esc(toothName(n))}</span></div>`;
    if (views.length) {
      html += '<div class="treatments-section">';
      if (planned.length) html += `<div class="treatment-group"><div class="group-header group-planned">⏱ ${T.status.planned}</div>${planned.map(item).join('')}</div>`;
      if (existing.length) html += `<div class="treatment-group"><div class="group-header group-existing">✓ ${T.status.existing}</div>${existing.map(item).join('')}</div>`;
      html += `</div><div class="click-hint">${T.tooltip.clickToEdit}</div>`;
    } else {
      html += `<div class="empty-state odonto-small odonto-muted">${T.tooltip.noTreatments}</div>`;
    }
    return html;
  }

  function show(n, anchor) {
    if (enabled && !enabled()) return;
    const el = ensureTip();
    currentTooth = n;
    el.innerHTML = contentHtml(n);
    el.classList.add('visible');
    const r = anchor.getBoundingClientRect();
    const tw = el.offsetWidth, th = el.offsetHeight;
    let left = r.left + r.width / 2 - tw / 2 + window.scrollX;
    left = Math.max(8, Math.min(left, window.scrollX + document.documentElement.clientWidth - tw - 8));
    let top = r.bottom + 6 + window.scrollY;
    if (r.bottom + th + 12 > window.innerHeight) top = r.top - th - 6 + window.scrollY;
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
  }

  function hide() {
    if (tip) tip.classList.remove('visible');
    currentTooth = null;
  }

  function scheduleClose() {
    clearTimeout(openTimer);
    clearTimeout(closeTimer);
    closeTimer = setTimeout(hide, 100);
  }

  function onOver(e) {
    const w = e.target.closest('.tooth-dual-view-wrapper');
    if (!w || !rootEl.contains(w)) return;
    const related = e.relatedTarget;
    if (related && w.contains(related)) return;
    clearTimeout(closeTimer);
    clearTimeout(openTimer);
    const n = Number(w.dataset.tooth);
    openTimer = setTimeout(() => show(n, w), 300);
  }

  function onOut(e) {
    const w = e.target.closest('.tooth-dual-view-wrapper');
    if (!w) return;
    const related = e.relatedTarget;
    if (related && (w.contains(related) || (tip && tip.contains(related)))) return;
    scheduleClose();
  }

  rootEl.addEventListener('mouseover', onOver);
  rootEl.addEventListener('mouseout', onOut);

  return {
    hide,
    refresh() { if (tip && tip.classList.contains('visible') && currentTooth) tip.innerHTML = contentHtml(currentTooth); },
    destroy() {
      rootEl.removeEventListener('mouseover', onOver);
      rootEl.removeEventListener('mouseout', onOut);
      clearTimeout(openTimer); clearTimeout(closeTimer);
      if (tip) tip.remove();
      tip = null;
    },
  };
}
