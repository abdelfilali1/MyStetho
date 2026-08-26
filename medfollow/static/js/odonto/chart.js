/**
 * Odontogramme — contrôleur principal (port de dentalpin `OdontogramChart.vue`
 * + `ToothQuadrant.vue`, mode « full »).
 *
 * mountOdontogram(root, { patientId, consultationId }) → { refresh, destroy }
 */

import { odontoApi, toast } from './api.js';
import {
  DECIDUOUS_TEETH, PERMANENT_TEETH, T, TREATMENT_SHORTCUTS, calculateToothRange, esc,
  getMultiToothConfig, isSameArch, isSurfaceTreatment, isUpperTooth, typeLabel,
} from './constants.js';
import { createTooltipManager, openMultiToothConfirm, openSurfaceSelector, openTreatmentEditModal } from './popups.js';
import { createChangeHistory, createLegend, createTreatmentList } from './sections.js';
import { createTimeline } from './timeline.js';
import { renderTooth, viewsForTooth } from './tooth.js';
import { createTreatmentBar } from './treatment-bar.js';

export function mountOdontogram(root, opts) {
  const api = odontoApi(opts.patientId);
  const consultationId = opts.consultationId || null;

  const state = {
    teeth: [],
    treatments: [],
    timelineDates: [],
    viewingDate: null,
    historical: null,
    dentition: 'permanent',
    selectedTooth: null,
    hoveredTooth: null,
    selectedType: null,
    selectedStatus: 'existing',
    multiSel: { teeth: [], anchor: null },
    multiConfirmOpen: false,
    undoStack: [],
    loading: true,
    error: null,
  };

  root.classList.add('odontogram-root');
  root.innerHTML = `<div class="odontogram-chart">
    <div class="odo-chart-header">
      <div class="odo-chart-title"><h3>${T.title}</h3>
        <span class="odo-badge odo-badge-neutral" data-role="readonly-badge" hidden>${T.readOnly}</span>
        <span class="odo-badge odo-badge-primary" data-role="mode-badge" hidden></span></div>
      <div class="odo-segmented" data-role="dentition">
        <button type="button" class="active" data-dentition="permanent">${T.dentition.permanent}</button>
        <button type="button" data-dentition="deciduous">${T.dentition.deciduous}</button>
      </div>
    </div>
    <div data-role="timeline" hidden></div>
    <div class="odo-loading" data-role="loading"><span class="odo-spinner"></span></div>
    <div class="odo-alert odo-alert-error" data-role="error" hidden></div>
    <div data-role="body" hidden>
      <div class="odontogram-wrapper"><div class="odontogram-grid" data-role="grid"></div></div>
      <div data-role="treatment-bar"></div>
      <div data-role="legend"></div>
      <div data-role="treatment-list"></div>
      <div data-role="history"></div>
    </div>
  </div>
  <div class="odo-multi-bar" data-role="multi-bar" hidden></div>`;

  const q = (role) => root.querySelector(`[data-role="${role}"]`);
  const gridEl = q('grid');
  const bodyEl = q('body');

  // ------------------------------------------------------------ derived
  const isReadonly = () => state.viewingDate !== null;
  const isClickToApply = () => state.selectedType !== null;
  const multiConfig = () => (state.selectedType ? getMultiToothConfig(state.selectedType) : null);
  const layout = () => (state.dentition === 'permanent' ? PERMANENT_TEETH : DECIDUOUS_TEETH);
  const pendingTreatment = () => (state.selectedType && !multiConfig() ? { type: state.selectedType, status: state.selectedStatus } : null);

  function toothRecord(n) {
    const source = state.viewingDate ? (state.historical ? state.historical.teeth : []) : state.teeth;
    return source.find((t) => t.tooth_number === n);
  }

  function toothData(n) {
    const r = toothRecord(n);
    return {
      generalCondition: (r && r.general_condition) || 'healthy',
      isDisplaced: !!(r && r.is_displaced),
      isRotated: !!(r && r.is_rotated),
    };
  }

  function treatmentsFor(n) {
    const source = state.viewingDate ? (state.historical ? state.historical.treatments : []) : state.treatments;
    return viewsForTooth(source, n);
  }

  function groupOf(n) {
    return treatmentsFor(n).find((v) => v.is_multi) || null;
  }

  // ------------------------------------------------------------ rendering
  function toothHtml(n) {
    const d = toothData(n);
    return renderTooth({
      toothNumber: n,
      generalCondition: d.generalCondition,
      isDisplaced: d.isDisplaced,
      isRotated: d.isRotated,
      treatments: treatmentsFor(n),
      readonly: isReadonly(),
      selected: state.selectedTooth === n,
      isHovered: state.hoveredTooth === n,
      pendingTreatment: state.hoveredTooth === n ? pendingTreatment() : null,
    });
  }

  function cellClass(n) {
    const g = groupOf(n);
    const cls = ['tooth-cell', 'tooth-cell-dual'];
    if (g && g.clinical_type !== 'bridge') cls.push('in-group');
    if (state.multiSel.teeth.includes(n)) cls.push('in-multi-selection');
    return cls.join(' ');
  }

  function quadrantHtml(teeth) {
    let html = '';
    teeth.forEach((n, idx) => {
      html += `<div class="${cellClass(n)}" data-cell="${n}">${toothHtml(n)}</div>`;
      const next = teeth[idx + 1];
      const g = groupOf(n);
      const gn = next !== undefined ? groupOf(next) : null;
      if (g && gn && g.treatment_id === gn.treatment_id && g.clinical_type !== 'bridge') {
        html += `<div class="group-connector status-${g.status}"></div>`;
      }
    });
    teeth.forEach((n, idx) => {
      const next = teeth[idx + 1];
      const g = groupOf(n);
      const gn = next !== undefined ? groupOf(next) : null;
      if (g && gn && g.treatment_id === gn.treatment_id && g.clinical_type === 'bridge') {
        html += `<div class="bridge-connector status-${g.status} ${isUpperTooth(n) ? 'upper' : 'lower'}" style="left:${idx * 62 + 61}px"></div>`;
      }
    });
    return `<div class="tooth-row">${html}</div>`;
  }

  function midlineStatus(left, right) {
    const a = groupOf(left), b = groupOf(right);
    if (!a || !b || a.treatment_id !== b.treatment_id || a.clinical_type !== 'bridge') return null;
    return a.status;
  }

  function renderGrid() {
    const L = layout();
    const up = midlineStatus(L.upperRight[L.upperRight.length - 1], L.upperLeft[0]);
    const low = midlineStatus(L.lowerRight[L.lowerRight.length - 1], L.lowerLeft[0]);
    gridEl.classList.toggle('cursor-crosshair', isClickToApply());
    gridEl.innerHTML = `<div class="arch-container">
      <div class="odo-arch-label">${T.quadrants.upper}</div>
      <div class="odo-arch-row">${up ? `<div class="midline-bridge upper status-${up}"></div>` : ''}${quadrantHtml(L.upperRight)}<div class="odo-divider-v"></div>${quadrantHtml(L.upperLeft)}</div>
    </div>
    <div class="odo-divider-h"></div>
    <div class="arch-container">
      <div class="odo-arch-row">${low ? `<div class="midline-bridge lower status-${low}"></div>` : ''}${quadrantHtml(L.lowerRight)}<div class="odo-divider-v"></div>${quadrantHtml(L.lowerLeft)}</div>
      <div class="odo-arch-label">${T.quadrants.lower}</div>
    </div>`;
  }

  function rerenderTooth(n) {
    const cell = gridEl.querySelector(`.tooth-cell[data-cell="${n}"]`);
    if (!cell) return;
    cell.className = cellClass(n);
    cell.innerHTML = toothHtml(n);
  }

  function renderHeader() {
    q('readonly-badge').hidden = !isReadonly();
    const mb = q('mode-badge');
    const cfg = multiConfig();
    if (isClickToApply()) {
      mb.hidden = false;
      mb.textContent = cfg ? cfg.label : typeLabel(state.selectedType);
    } else mb.hidden = true;
    q('dentition').querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.dentition === state.dentition));
  }

  function renderMultiBar() {
    const bar = q('multi-bar');
    const cfg = multiConfig();
    if (cfg && cfg.selectionMode === 'free' && state.multiSel.teeth.length > 0 && !state.multiConfirmOpen) {
      bar.hidden = false;
      bar.innerHTML = `<span class="odo-multi-icon">🔗</span><span class="odonto-strong">${esc(cfg.label)}</span>
        <span class="odo-badge odo-badge-primary">${state.multiSel.teeth.length}</span>
        <button type="button" class="odo-btn odo-btn-ghost odo-btn-xs" data-act="multi-cancel">${T.common.cancel}</button>
        <button type="button" class="odo-btn odo-btn-primary odo-btn-xs" data-act="multi-confirm"${canConfirmFree() ? '' : ' disabled'}>${T.common.confirm}</button>`;
    } else {
      bar.hidden = true;
      bar.innerHTML = '';
    }
  }

  function renderAll() {
    renderHeader();
    q('loading').hidden = !state.loading;
    q('error').hidden = !state.error;
    if (state.error) q('error').innerHTML = `⚠ ${esc(state.error)} <button type="button" class="odo-btn odo-btn-outline odo-btn-xs" data-act="retry">${T.common.retry}</button>`;
    bodyEl.hidden = state.loading || !!state.error;
    if (!bodyEl.hidden) {
      renderGrid();
      q('treatment-bar').hidden = isReadonly();
      if (bar) bar.update({ selectedType: state.selectedType, selectedStatus: state.selectedStatus });
      list.update(state.treatments);
      history.update(state.treatments);
    }
    const tlEl = q('timeline');
    if (state.timelineDates.length > 1) {
      tlEl.hidden = false;
      timeline.update({ dates: state.timelineDates, currentDate: state.viewingDate });
    } else {
      tlEl.hidden = true;
    }
    renderMultiBar();
    tooltip.refresh();
  }

  // ------------------------------------------------------------ sub-components
  const timeline = createTimeline(q('timeline'), {
    dates: [], currentDate: null,
    onChange: (date) => handleTimelineChange(date),
  });
  const legend = createLegend(q('legend'));
  const list = createTreatmentList(q('treatment-list'));
  const history = createChangeHistory(q('history'), { loadHistory: () => api.history() });
  const tooltip = createTooltipManager(gridEl, {
    getTreatments: treatmentsFor,
    onEdit: (v) => handleEdit(v),
    enabled: () => !state.multiConfirmOpen,
  });
  let bar = null;
  bar = createTreatmentBar(q('treatment-bar'), {
    onSelect: (type) => { state.selectedType = type; resetMultiSelection(); renderHeader(); renderGrid(); renderMultiBar(); },
    onStatus: (s) => { state.selectedStatus = s; },
    onCancel: () => cancelClickToApply(),
  });

  // ------------------------------------------------------------ data
  async function loadAll() {
    state.loading = true; state.error = null; renderAll();
    try {
      const [odo, tl] = await Promise.all([api.get(), api.timeline()]);
      state.teeth = odo.teeth || [];
      state.treatments = odo.treatments || [];
      state.timelineDates = tl.dates || [];
    } catch (e) {
      state.error = T.messages.loadError;
    }
    state.loading = false;
    renderAll();
  }

  async function refreshData() {
    try {
      const [odo, tl] = await Promise.all([api.get(), api.timeline()]);
      state.teeth = odo.teeth || [];
      state.treatments = odo.treatments || [];
      state.timelineDates = tl.dates || [];
    } catch (e) {
      toast(T.messages.error, { type: 'error' });
    }
    renderAll();
  }

  async function handleTimelineChange(date) {
    if (date === null) {
      state.viewingDate = null; state.historical = null;
      cancelClickToApply();
      renderAll();
      return;
    }
    try {
      const data = await api.at(date);
      state.historical = { teeth: data.teeth || [], treatments: data.treatments || [] };
      state.viewingDate = date;
      cancelClickToApply();
    } catch (e) {
      toast(T.common.error, { type: 'error' });
    }
    renderAll();
  }

  // ------------------------------------------------------------ click-to-apply
  function handleToothClick(n) {
    if (isReadonly() || !isClickToApply()) return;
    if (multiConfig()) { handleMultiToothClick(n); return; }
    if (isSurfaceTreatment(state.selectedType)) {
      state.selectedTooth = n;
      rerenderTooth(n);
      tooltip.hide();
      openSurfaceSelector({
        toothNumber: n,
        treatmentType: state.selectedType,
        status: state.selectedStatus,
        onConfirm: (surfaces) => { const tooth = state.selectedTooth; state.selectedTooth = null; applyTreatment(tooth, surfaces); },
        onCancel: () => { const tooth = state.selectedTooth; state.selectedTooth = null; if (tooth) rerenderTooth(tooth); },
      });
    } else {
      applyTreatment(n);
    }
  }

  function handleMultiToothClick(n) {
    const cfg = multiConfig();
    if (!cfg) return;
    if (cfg.selectionMode === 'range') {
      if (state.multiSel.anchor === null) {
        state.multiSel = { teeth: [n], anchor: n };
        renderGrid();
        return;
      }
      try {
        const range = calculateToothRange(state.multiSel.anchor, n);
        if (range.length < cfg.minTeeth) { toast(T.multiTooth.errors.tooFew(cfg.minTeeth), { type: 'warning' }); return; }
        if (range.length > cfg.maxTeeth) { toast(T.multiTooth.errors.tooMany(cfg.maxTeeth), { type: 'warning' }); return; }
        state.multiSel.teeth = range;
        renderGrid();
        requestMultiConfirm(true);
      } catch (e) {
        toast(T.multiTooth.errors.sameArchRequired, { type: 'warning' });
      }
      return;
    }
    const existing = state.multiSel.teeth;
    const idx = existing.indexOf(n);
    if (idx === -1) {
      const candidate = [...existing, n];
      if (cfg.requiresSameArch && !isSameArch(candidate)) { toast(T.multiTooth.errors.sameArchRequired, { type: 'warning' }); return; }
      if (candidate.length > cfg.maxTeeth) { toast(T.multiTooth.errors.tooMany(cfg.maxTeeth), { type: 'warning' }); return; }
      state.multiSel = { ...state.multiSel, teeth: candidate };
    } else {
      state.multiSel = { ...state.multiSel, teeth: existing.filter((t) => t !== n) };
    }
    renderGrid();
    renderMultiBar();
  }

  function canConfirmFree() {
    const cfg = multiConfig();
    return !!cfg && cfg.selectionMode === 'free' && state.multiSel.teeth.length >= cfg.minTeeth;
  }

  function requestMultiConfirm(force) {
    const cfg = multiConfig();
    if (!cfg) return;
    if (!force && !canConfirmFree()) return;
    state.multiConfirmOpen = true;
    tooltip.hide();
    renderMultiBar();
    openMultiToothConfirm({
      config: cfg,
      teeth: state.multiSel.teeth,
      status: state.selectedStatus,
      onConfirm: (teethRoles) => { state.multiConfirmOpen = false; confirmMultiToothSelection(teethRoles); },
      onCancel: () => { state.multiConfirmOpen = false; resetMultiSelection(); renderGrid(); renderMultiBar(); },
    });
  }

  async function confirmMultiToothSelection(teethRoles) {
    const cfg = multiConfig();
    if (!cfg) return;
    const sorted = [...state.multiSel.teeth].sort((a, b) => a - b);
    const payload = { scope: 'multi_tooth', status: state.selectedStatus, consultation_id: consultationId };
    if (cfg.mode === 'bridge' && teethRoles && teethRoles.length) payload.teeth = teethRoles;
    else payload.tooth_numbers = sorted;
    payload.clinical_type = cfg.mode === 'uniform' ? cfg.key : 'bridge';
    try {
      const created = await api.createTreatment(payload);
      state.undoStack.push({ id: created.id, type: cfg.key });
      resetMultiSelection();
      state.selectedType = null;
      toast(`${cfg.label} - ${sorted.join(', ')} · ${T.treatments.treatmentAdded}`, { action: { label: T.common.undo, onClick: handleUndo } });
      await refreshData();
    } catch (e) {
      toast(e.message || T.messages.error, { type: 'error' });
      resetMultiSelection();
      renderGrid(); renderMultiBar();
    }
  }

  function resetMultiSelection() {
    state.multiSel = { teeth: [], anchor: null };
    state.multiConfirmOpen = false;
  }

  async function applyTreatment(n, surfaces) {
    if (!state.selectedType) return;
    const payload = { tooth_numbers: [n], status: state.selectedStatus, scope: 'tooth', clinical_type: state.selectedType, consultation_id: consultationId };
    if (surfaces && surfaces.length) payload.surfaces = surfaces;
    try {
      const created = await api.createTreatment(payload);
      state.undoStack.push({ id: created.id, type: created.clinical_type });
      toast(`${typeLabel(created.clinical_type)} - ${T.tooth} ${n} · ${T.treatments.treatmentAdded}`, { action: { label: T.common.undo, onClick: handleUndo } });
      state.selectedType = null;
      await refreshData();
    } catch (e) {
      toast(e.message || T.messages.error, { type: 'error' });
      renderGrid();
    }
  }

  async function handleUndo() {
    const last = state.undoStack.pop();
    if (!last) return;
    try {
      await api.deleteTreatment(last.id);
      toast(T.common.undone, { type: 'neutral' });
      await refreshData();
    } catch (e) {
      toast(e.message || T.messages.error, { type: 'error' });
    }
  }

  function cancelClickToApply() {
    state.selectedType = null;
    state.hoveredTooth = null;
    resetMultiSelection();
    if (bar) bar.update({ selectedType: null, selectedStatus: state.selectedStatus });
    renderHeader(); renderGrid(); renderMultiBar();
  }

  // ------------------------------------------------------------ edition
  function handleEdit(view) {
    if (isReadonly()) return;
    openTreatmentEditModal({
      treatment: view,
      onUpdate: async (id, data) => {
        try { await api.updateTreatment(id, data); toast(T.treatments.updated); await refreshData(); }
        catch (e) { toast(e.message || T.messages.error, { type: 'error' }); }
      },
      onDelete: async (id) => {
        try { await api.deleteTreatment(id); toast(T.treatments.treatmentDeleted); await refreshData(); }
        catch (e) { toast(e.message || T.messages.error, { type: 'error' }); }
      },
      onPerform: async (id) => {
        try { await api.performTreatment(id, consultationId); toast(T.treatments.treatmentPerformed); await refreshData(); }
        catch (e) { toast(e.message || T.messages.error, { type: 'error' }); }
      },
    });
  }

  // ------------------------------------------------------------ events
  function onClick(e) {
    if (e.target.closest('[data-act="retry"]')) { loadAll(); return; }
    const dent = e.target.closest('[data-dentition]');
    if (dent) { state.dentition = dent.dataset.dentition; resetMultiSelection(); renderHeader(); renderGrid(); renderMultiBar(); return; }
    if (e.target.closest('[data-act="multi-cancel"]')) { resetMultiSelection(); renderGrid(); renderMultiBar(); return; }
    if (e.target.closest('[data-act="multi-confirm"]')) { requestMultiConfirm(false); return; }
    const w = e.target.closest('.tooth-dual-view-wrapper');
    if (w && gridEl.contains(w)) handleToothClick(Number(w.dataset.tooth));
  }

  function onOver(e) {
    const w = e.target.closest('.tooth-dual-view-wrapper');
    if (!w || !gridEl.contains(w)) return;
    const n = Number(w.dataset.tooth);
    if (state.hoveredTooth === n) return;
    const prev = state.hoveredTooth;
    state.hoveredTooth = n;
    if (pendingTreatment()) { if (prev !== null) rerenderTooth(prev); rerenderTooth(n); }
  }

  function onOut(e) {
    const w = e.target.closest('.tooth-dual-view-wrapper');
    if (!w) return;
    if (e.relatedTarget && w.contains(e.relatedTarget)) return;
    const prev = state.hoveredTooth;
    state.hoveredTooth = null;
    if (prev !== null && pendingTreatment()) rerenderTooth(prev);
  }

  function onKeydown(e) {
    if (root.offsetParent === null) return;
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
    if (document.querySelector('.odonto-modal-overlay')) return;
    if (e.key === 'Escape') {
      if (multiConfig() && state.multiSel.teeth.length > 0) { resetMultiSelection(); renderGrid(); renderMultiBar(); return; }
      cancelClickToApply();
      return;
    }
    if (e.key === 'Enter' && multiConfig()) {
      if (!state.multiConfirmOpen) requestMultiConfirm(false);
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); handleUndo(); return; }
    if (e.key.toLowerCase() === 'p') { state.selectedStatus = 'planned'; bar.update({ selectedStatus: 'planned' }); return; }
    if (e.key.toLowerCase() === 'e') { state.selectedStatus = 'existing'; bar.update({ selectedStatus: 'existing' }); return; }
    const shortcut = TREATMENT_SHORTCUTS[e.key];
    if (shortcut && !isReadonly()) {
      state.selectedType = shortcut;
      resetMultiSelection();
      bar.update({ selectedType: shortcut, selectedStatus: state.selectedStatus });
      renderHeader(); renderGrid(); renderMultiBar();
    }
  }

  root.addEventListener('click', onClick);
  root.addEventListener('mouseover', onOver);
  root.addEventListener('mouseout', onOut);
  window.addEventListener('keydown', onKeydown);

  loadAll();

  return {
    refresh: refreshData,
    destroy() {
      root.removeEventListener('click', onClick);
      root.removeEventListener('mouseover', onOver);
      root.removeEventListener('mouseout', onOut);
      window.removeEventListener('keydown', onKeydown);
      timeline.destroy(); legend.destroy(); list.destroy(); history.destroy(); tooltip.destroy(); bar.destroy();
      root.innerHTML = '';
    },
  };
}
