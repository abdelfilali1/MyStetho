/**
 * Barre de traitements (port de dentalpin `TreatmentBar.vue`, mode « full »,
 * sans catalogue : les boutons viennent des constantes).
 */

import {
  ATOMIC_MULTI_TOOTH_TYPES, MULTI_TOOTH_WRAPPER_BY_TYPE, T, TREATMENT_CATEGORIES, esc,
  getAllowedStatusesForTreatment, getMultiToothConfig, getTreatmentColor, isMultiToothOnlyType,
  isSurfaceTreatment, supportsBothModes, typeLabel,
} from './constants.js';
import { iconSvg } from './icons.js';

const ICON_LINK = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>';
const ICON_SPLINT = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="4" y="5" width="6" height="14" rx="2"/><rect x="14" y="7" width="6" height="10" rx="2"/><path d="M12 2v20"/></svg>';
const ICON_LAYERS = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m12 2 8.5 4.5L12 11 3.5 6.5 12 2z"/><path d="m3.5 11.5 8.5 4.5 8.5-4.5"/><path d="m3.5 16.5 8.5 4.5 8.5-4.5"/></svg>';
const ICON_CLICK = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 9l5 12 1.8-5.2L21 14 9 9z"/><path d="M7.2 2.2 8 5.1"/><path d="m5.1 8-2.9-.8"/><path d="M14 4.1 12 6"/><path d="m6 12-1.9 2"/></svg>';
const ICON_HAND = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 11V6a2 2 0 0 0-4 0v1"/><path d="M14 10V4a2 2 0 0 0-4 0v2"/><path d="M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></svg>';

export function createTreatmentBar(el, { onSelect, onStatus, onCancel }) {
  let activeCategory = 'diagnostico';
  let selectedType = null;
  let selectedStatus = 'existing';

  const isSelected = (type) => selectedType === type || (MULTI_TOOTH_WRAPPER_BY_TYPE[type] && MULTI_TOOTH_WRAPPER_BY_TYPE[type] === selectedType);
  const isMultiMode = () => selectedType && Object.values(MULTI_TOOTH_WRAPPER_BY_TYPE).includes(selectedType);

  function render() {
    const cfg = selectedType ? getMultiToothConfig(selectedType) : null;
    const allowed = selectedType && !cfg ? getAllowedStatusesForTreatment(selectedType) : ['existing', 'planned'];
    const statusOptions = [
      { value: 'existing', color: 'gray' },
      { value: 'planned', color: 'red' },
    ].filter((o) => allowed.includes(o.value));

    let instructions;
    if (cfg) {
      instructions = `${ICON_LINK}<span>${cfg.selectionMode === 'range' ? T.multiTooth.hints.range : T.multiTooth.hints.free}</span>`;
    } else if (selectedType) {
      instructions = `${ICON_CLICK}<span>${T.instructions.clickTooth}</span>`;
    } else {
      instructions = `${ICON_HAND}<span>${T.instructions.selectTreatment}</span>`;
    }

    const category = TREATMENT_CATEGORIES.find((c) => c.key === activeCategory) || TREATMENT_CATEGORIES[0];
    const items = category.treatments.filter((t) => !isMultiToothOnlyType(t));

    el.innerHTML = `<div class="treatment-bar">
      <div class="top-row">
        <div class="status-toggle">
          ${statusOptions.map((o) => `<button type="button" class="status-btn status-${o.color}${selectedStatus === o.value ? ' selected' : ''}" data-status="${o.value}"><span class="status-dot"></span><span class="status-label">${T.status[o.value]}</span></button>`).join('')}
        </div>
        <div class="divider"></div>
        <div class="category-tabs">
          ${TREATMENT_CATEGORIES.map((c) => `<button type="button" class="category-tab${c.key === activeCategory ? ' active' : ''}" data-category="${c.key}">${T.categories[c.key]}</button>`).join('')}
        </div>
        <div class="spacer"></div>
        ${selectedType ? `<div class="cancel-section"><button type="button" class="odo-btn odo-btn-ghost odo-btn-sm" data-act="cancel">✕ ${T.common.cancel}</button></div>` : ''}
        <div class="instructions${cfg ? ' multi-tooth-hint' : ''}">${instructions}</div>
      </div>
      <div class="treatment-grid">
        ${items.map((type) => {
          const atomic = ATOMIC_MULTI_TOOTH_TYPES.has(type);
          const sel = isSelected(type);
          const both = supportsBothModes(type);
          return `<div class="treatment-cell">
            <button type="button" class="treatment-btn${sel ? ' selected' : ''}${isSurfaceTreatment(type) ? ' is-surface' : ''}${atomic ? ' atomic-multi-btn' : ''}${sel && both ? ' has-mode-selector' : ''}" data-type="${type}" title="${esc(typeLabel(type))}">
              <div class="treatment-icon">${iconSvg(type, 22, getTreatmentColor(type))}</div>
              <span class="treatment-label">${esc(typeLabel(type))}</span>
              ${atomic ? `<span class="multi-tooth-badge">${type === 'bridge' ? ICON_LINK : ICON_SPLINT}</span>` : both ? `<span class="multi-tooth-badge multi-tooth-badge-hint">${ICON_LAYERS}</span>` : ''}
            </button>
            ${sel && both ? `<div class="mode-selector-inline">
              <button type="button" class="mode-chip${!isMultiMode() ? ' active' : ''}" data-multi="0" data-type="${type}">◦ ${T.oneTooth}</button>
              <button type="button" class="mode-chip${isMultiMode() ? ' active' : ''}" data-multi="1" data-type="${type}">${ICON_LINK} ${T.multipleTeeth}</button>
            </div>` : ''}
          </div>`;
        }).join('')}
      </div>
    </div>`;
  }

  function onClick(e) {
    const chip = e.target.closest('.mode-chip');
    if (chip) {
      e.stopPropagation();
      const type = chip.dataset.type;
      const next = chip.dataset.multi === '1' ? MULTI_TOOTH_WRAPPER_BY_TYPE[type] : type;
      if (next && next !== selectedType) { selectedType = next; render(); onSelect(next); }
      return;
    }
    const sb = e.target.closest('[data-status]');
    if (sb) { selectedStatus = sb.dataset.status; render(); onStatus(selectedStatus); return; }
    const cat = e.target.closest('[data-category]');
    if (cat) { activeCategory = cat.dataset.category; render(); return; }
    if (e.target.closest('[data-act="cancel"]')) { selectedType = null; render(); onCancel(); return; }
    const btn = e.target.closest('.treatment-btn');
    if (btn) {
      const type = btn.dataset.type;
      const allowed = getAllowedStatusesForTreatment(type);
      if (!allowed.includes(selectedStatus)) { selectedStatus = allowed[0]; onStatus(selectedStatus); }
      selectedType = type;
      render();
      onSelect(type);
    }
  }

  el.addEventListener('click', onClick);
  render();

  return {
    update(next) {
      if ('selectedType' in next) selectedType = next.selectedType;
      if ('selectedStatus' in next) selectedStatus = next.selectedStatus;
      render();
    },
    destroy() { el.removeEventListener('click', onClick); el.innerHTML = ''; },
  };
}
