/**
 * Sections repliables sous l'odontogramme (port de dentalpin
 * `OdontogramLegend`, `TreatmentListSection`, `ChangeHistorySection`).
 */

import {
  PLANNED_INDICATOR_COLOR, T, TREATMENT_CATEGORIES, esc, formatDate, formatDateTime,
  getTreatmentColor, toothName, typeLabel,
} from './constants.js';
import { TREATMENT_ICONS, iconSvg } from './icons.js';
import { viewForTooth } from './tooth.js';

function chevron(open) {
  return `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="${open ? 'm18 15-6-6-6 6' : 'm6 9 6 6 6-6'}"/></svg>`;
}

export function createLegend(el) {
  let expanded = false;

  function render() {
    const sections = TREATMENT_CATEGORIES.map((c) => `<div class="legend-section"><h4 class="section-title">${T.categories[c.key]}</h4>
      <div class="legend-grid">${c.treatments.map((t) => `<div class="legend-item">
        ${TREATMENT_ICONS[t] ? `<div class="legend-icon">${iconSvg(t, 20, getTreatmentColor(t))}</div>` : `<span class="legend-color" style="background:${getTreatmentColor(t)}"></span>`}
        <span class="item-label">${esc(typeLabel(t))}</span></div>`).join('')}</div></div>`).join('');
    el.innerHTML = `<div class="odontogram-legend">
      <button type="button" class="legend-header" data-act="toggle"><div class="header-content">ⓘ <span class="header-title">${T.legend}</span></div>${chevron(expanded)}</button>
      <div class="legend-content"${expanded ? '' : ' hidden'}>
        <div class="legend-section"><h4 class="section-title">${T.statusLegend}</h4><div class="status-list">
          <div class="status-item"><span class="status-indicator" style="background:#94A3B8"></span><span class="item-label">${T.status.existing}</span></div>
          <div class="status-item"><span class="status-indicator planned" style="background:#94A3B8"><span class="planned-p" style="color:${PLANNED_INDICATOR_COLOR}">P</span></span><span class="item-label">${T.status.planned}</span></div>
        </div></div>
        ${sections}
      </div></div>`;
  }

  el.addEventListener('click', (e) => {
    if (e.target.closest('[data-act="toggle"]')) { expanded = !expanded; render(); }
  });
  render();
  return { destroy() { el.innerHTML = ''; } };
}

function flatten(treatments) {
  const rows = [];
  for (const t of treatments) {
    for (const tooth of t.teeth || []) {
      const v = viewForTooth(t, tooth.tooth_number);
      if (v) rows.push(v);
    }
  }
  return rows;
}

export function createTreatmentList(el) {
  let expanded = false;
  let treatments = [];

  function render() {
    const rows = flatten(treatments).sort((a, b) => new Date(b.performed_at || b.recorded_at) - new Date(a.performed_at || a.recorded_at));
    el.innerHTML = `<div class="odo-section">
      <button type="button" class="odo-section-header" data-act="toggle"><div class="header-content">☰ <span>${T.treatmentList.title}</span>${treatments.length ? `<span class="odo-badge odo-badge-neutral odo-badge-xs">${treatments.length}</span>` : ''}</div>${chevron(expanded)}</button>
      <div class="odo-section-body"${expanded ? '' : ' hidden'}>
        ${rows.length === 0 ? `<div class="odo-section-empty">${T.treatmentList.noTreatments}</div>` : `<ul class="odo-treatment-list">${rows.map((v) => `<li>
          <span class="odonto-dot" style="background:${getTreatmentColor(v.treatment_type)}"></span>
          <div class="odo-tl-main"><div><span class="odonto-strong">${v.tooth_number}</span> <span class="odonto-muted">${esc(toothName(v.tooth_number))}</span></div>
            <div class="odonto-small"><span class="odonto-muted">${esc(typeLabel(v.treatment_type))}</span>${v.surfaces && v.surfaces.length ? ` <span class="odonto-subtle">(${v.surfaces.join(', ')})</span>` : ''}</div></div>
          <div class="odo-tl-side"><span class="odo-badge odo-badge-xs ${v.status === 'planned' ? 'odo-badge-warning' : 'odo-badge-neutral'}">${T.status[v.status]}</span><span class="odonto-small odonto-subtle">${esc(formatDate(v.performed_at || v.recorded_at))}</span></div>
        </li>`).join('')}</ul>`}
      </div></div>`;
  }

  el.addEventListener('click', (e) => {
    if (e.target.closest('[data-act="toggle"]')) { expanded = !expanded; render(); }
  });
  render();
  return {
    update(next) { treatments = next || []; render(); },
    destroy() { el.innerHTML = ''; },
  };
}

export function createChangeHistory(el, { loadHistory }) {
  let expanded = false;
  let loading = false;
  let loaded = false;
  let history = [];
  let treatments = [];

  function entries() {
    const out = [];
    for (const h of history) {
      if (h.change_type === 'created' && !h.old_condition && (!h.new_condition || h.new_condition === 'healthy')) continue;
      out.push({ id: `h-${h.id}`, type: 'history', toothNumber: h.tooth_number, date: new Date(h.changed_at), h });
    }
    for (const v of flatten(treatments)) {
      out.push({ id: `t-${v.id}`, type: 'treatment', toothNumber: v.tooth_number, date: new Date(v.performed_at || v.recorded_at), v });
    }
    return out.sort((a, b) => b.date - a.date);
  }

  function condLabel(c) {
    if (!c) return '-';
    return T.types[c] || T.conditions[c] || c;
  }

  function render() {
    const list = entries();
    let body;
    if (loading) body = '<div class="odo-section-empty">…</div>';
    else if (list.length === 0) body = `<div class="odo-section-empty">${T.changeHistory.noChanges}</div>`;
    else {
      body = `<div class="odo-history-list">${list.map((e) => {
        if (e.type === 'treatment') {
          const v = e.v;
          return `<div class="odo-history-entry"><div class="odo-history-rail"><div class="odo-history-dot treatment"></div><div class="odo-history-line"></div></div>
            <div class="odo-history-content">
              <div class="odo-history-row"><span class="odonto-strong">${v.tooth_number}</span><span class="odonto-muted">${esc(toothName(v.tooth_number))}</span>${v.surfaces && v.surfaces.length ? `<span class="odonto-subtle">(${v.surfaces.join(', ')})</span>` : ''}<span class="odo-badge odo-badge-success odo-badge-xs">${T.changeHistory.treatmentAdded}</span></div>
              <div class="odo-history-row odonto-small"><span class="odo-color-square" style="background:${getTreatmentColor(v.treatment_type)}"></span><span class="odonto-muted odonto-strong">${esc(typeLabel(v.treatment_type))}</span><span class="${v.status === 'planned' ? 'odo-text-warning' : 'odonto-muted'}">(${T.status[v.status]})</span></div>
              <div class="odo-history-row odonto-small odonto-subtle">📅 ${esc(formatDateTime(e.date))}${v.performed_by_name ? ` • 👤 ${esc(v.performed_by_name)}` : ''}</div>
            </div></div>`;
        }
        const h = e.h;
        return `<div class="odo-history-entry"><div class="odo-history-rail"><div class="odo-history-dot history"></div><div class="odo-history-line"></div></div>
          <div class="odo-history-content">
            <div class="odo-history-row"><span class="odonto-strong">${h.tooth_number}</span><span class="odonto-muted">${esc(toothName(h.tooth_number))}</span>${h.surface ? `<span class="odonto-subtle">(${esc(h.surface)})</span>` : ''}<span class="odo-badge odo-badge-neutral odo-badge-xs">${esc(T.historyChangeTypes[h.change_type] || h.change_type)}</span></div>
            ${h.old_condition || h.new_condition ? `<div class="odo-history-row odonto-small">${h.old_condition ? `<span class="odo-color-square" style="background:${getTreatmentColor(h.old_condition)}"></span><span class="odonto-subtle">${esc(condLabel(h.old_condition))}</span>` : ''}${h.old_condition && h.new_condition ? '<span class="odonto-subtle">→</span>' : ''}${h.new_condition ? `<span class="odo-color-square" style="background:${getTreatmentColor(h.new_condition)}"></span><span class="odonto-muted">${esc(condLabel(h.new_condition))}</span>` : ''}</div>` : ''}
            <div class="odo-history-row odonto-small odonto-subtle">👤 ${esc(h.changed_by_name || h.changed_by || '')} • ${esc(formatDateTime(h.changed_at))}</div>
          </div></div>`;
      }).join('')}</div>`;
    }
    el.innerHTML = `<div class="odo-section">
      <button type="button" class="odo-section-header" data-act="toggle"><div class="header-content">🕘 <span>${T.changeHistory.title}</span>${list.length ? `<span class="odo-badge odo-badge-neutral odo-badge-xs">${list.length}</span>` : ''}</div>${chevron(expanded)}</button>
      <div class="odo-section-body"${expanded ? '' : ' hidden'}>${body}</div></div>`;
  }

  async function load() {
    loading = true; render();
    try {
      const res = await loadHistory();
      history = (res && res.data) || [];
      loaded = true;
    } catch (e) { history = []; }
    loading = false; render();
  }

  el.addEventListener('click', (e) => {
    if (e.target.closest('[data-act="toggle"]')) {
      expanded = !expanded;
      render();
      if (expanded && !loaded) load();
    }
  });
  render();
  return {
    update(next) { treatments = next || []; if (expanded) { loaded = false; load(); } else render(); },
    destroy() { el.innerHTML = ''; },
  };
}
