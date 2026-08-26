/**
 * Barre de traitements (port de dentalpin `TreatmentBar.vue`, mode « full »,
 * branche catalogue : un bouton par acte du catalogue, repli sur les constantes
 * pour les catégories sans acte — le Diagnostic notamment).
 */

import {
  ATOMIC_MULTI_TOOTH_TYPES, MULTI_TOOTH_WRAPPER_BY_TYPE, T, TREATMENT_CATEGORIES, esc,
  getAllowedStatusesForTreatment, getMultiToothConfig, getTreatmentColor, isMultiToothOnlyType,
  isSurfaceTreatment, supportsBothModes, typeLabel,
} from './constants.js';
import { iconSvg, resolveIconKey } from './icons.js';

const ICON_LINK = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>';
const ICON_SPLINT = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="4" y="5" width="6" height="14" rx="2"/><rect x="14" y="7" width="6" height="10" rx="2"/><path d="M12 2v20"/></svg>';
const ICON_LAYERS = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m12 2 8.5 4.5L12 11 3.5 6.5 12 2z"/><path d="m3.5 11.5 8.5 4.5 8.5-4.5"/><path d="m3.5 16.5 8.5 4.5 8.5-4.5"/></svg>';
const ICON_CLICK = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 9l5 12 1.8-5.2L21 14 9 9z"/><path d="M7.2 2.2 8 5.1"/><path d="m5.1 8-2.9-.8"/><path d="M14 4.1 12 6"/><path d="m6 12-1.9 2"/></svg>';
const ICON_HAND = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 11V6a2 2 0 0 0-4 0v1"/><path d="M14 10V4a2 2 0 0 0-4 0v2"/><path d="M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></svg>';
const ICON_UP = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>';
const ICON_DOWN = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>';

const ATOMIC_MULTI_ICONS = { bridge: ICON_LINK, splint: ICON_SPLINT };

function isGlobalScope(scope) {
  return scope === 'global_mouth' || scope === 'global_arch';
}

/**
 * createTreatmentBar(el, { onSelect(type, catalogCode), onStatus(status), onCancel(), onGlobal(item, arch) })
 * update({ selectedType?, selectedCode?, selectedStatus?, catalog?, categories? })
 */
export function createTreatmentBar(el, { onSelect, onStatus, onCancel, onGlobal }) {
  let activeCategory = 'diagnostico';
  let selectedType = null;
  let selectedCode = null;
  let selectedStatus = 'existing';
  let catalog = [];
  let categories = [];
  let typeDescriptions = {};
  let archPickerItem = null;

  /** Infobulle native : nom de l'acte puis description clinique. */
  function tooltipFor(item) {
    return item.description ? `${item.label}\n\n${item.description}` : item.label;
  }

  // ------------------------------------------------------------ items
  function itemFromCatalog(c) {
    const isAtomic = ATOMIC_MULTI_TOOTH_TYPES.has(c.clinical_type);
    return {
      key: c.code,
      label: c.label,
      type: c.clinical_type,
      code: c.code,
      scope: c.scope || 'tooth',
      description: c.description || typeDescriptions[c.clinical_type] || '',
      iconKey: resolveIconKey(c.clinical_type, c.code),
      isAtomic,
      atomicIcon: isAtomic ? ATOMIC_MULTI_ICONS[c.clinical_type] : null,
    };
  }

  function itemFromType(type) {
    const isAtomic = ATOMIC_MULTI_TOOTH_TYPES.has(type);
    return {
      key: type,
      label: typeLabel(type),
      type,
      code: null,
      scope: 'tooth',
      description: typeDescriptions[type] || '',
      iconKey: type,
      isAtomic,
      atomicIcon: isAtomic ? ATOMIC_MULTI_ICONS[type] : null,
    };
  }

  /** Un bouton par acte du catalogue de la catégorie ; repli sur les constantes (Diagnostic…). */
  function itemsFor(categoryKey) {
    const fromCatalog = catalog.filter((c) => c.category === categoryKey && c.clinical_type && !isMultiToothOnlyType(c.clinical_type));
    if (fromCatalog.length) return fromCatalog.map(itemFromCatalog);
    const constant = TREATMENT_CATEGORIES.find((c) => c.key === categoryKey);
    if (!constant) return [];
    return constant.treatments.filter((t) => !isMultiToothOnlyType(t)).map(itemFromType);
  }

  /** Ordre dentalpin : catégories des constantes d'abord, puis celles apportées par le catalogue. */
  function categoryKeys() {
    const keys = TREATMENT_CATEGORIES.map((c) => c.key);
    for (const c of categories) if (!keys.includes(c.key)) keys.push(c.key);
    for (const c of catalog) if (c.category && !keys.includes(c.category)) keys.push(c.category);
    return keys.filter((k) => itemsFor(k).length > 0);
  }

  function categoryLabel(key) {
    const c = categories.find((x) => x.key === key);
    return (c && c.label) || T.categories[key] || key;
  }

  function findItem(type, code) {
    if (code) {
      const c = catalog.find((x) => x.code === code);
      return c ? itemFromCatalog(c) : null;
    }
    return type ? itemFromType(type) : null;
  }

  const isMultiMode = () => !!selectedType && Object.values(MULTI_TOOTH_WRAPPER_BY_TYPE).includes(selectedType);

  // Un bouton est « sélectionné » s'il correspond à l'acte cliqué (par code pour le catalogue,
  // plusieurs boutons partageant le même type clinique ne doivent pas tous s'allumer).
  function isSelected(item) {
    if (item.code) return selectedCode === item.code;
    if (selectedCode) return false;
    return selectedType === item.type || (MULTI_TOOTH_WRAPPER_BY_TYPE[item.type] && MULTI_TOOTH_WRAPPER_BY_TYPE[item.type] === selectedType);
  }

  // ------------------------------------------------------------ rendu
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

    const keys = categoryKeys();
    if (!keys.includes(activeCategory)) activeCategory = keys[0] || 'diagnostico';
    const items = itemsFor(activeCategory);

    const archPicker = archPickerItem ? `<div class="arch-picker">
        <div class="arch-picker-label">${esc(T.globals.archPickerTitle(archPickerItem.label))}</div>
        <div class="arch-picker-buttons">
          <button type="button" class="arch-btn" data-arch="upper">${ICON_UP}<span>${T.globals.upperArch}</span></button>
          <button type="button" class="arch-btn" data-arch="lower">${ICON_DOWN}<span>${T.globals.lowerArch}</span></button>
          <button type="button" class="arch-btn arch-btn-cancel" data-act="arch-cancel">✕ <span>${T.common.cancel}</span></button>
        </div>
      </div>` : '';

    el.innerHTML = `<div class="treatment-bar">
      <div class="top-row">
        <div class="status-toggle">
          ${statusOptions.map((o) => `<button type="button" class="status-btn status-${o.color}${selectedStatus === o.value ? ' selected' : ''}" data-status="${o.value}"><span class="status-dot"></span><span class="status-label">${T.status[o.value]}</span></button>`).join('')}
        </div>
        <div class="divider"></div>
        <div class="category-tabs">
          ${keys.map((k) => `<button type="button" class="category-tab${k === activeCategory ? ' active' : ''}" data-category="${k}">${esc(categoryLabel(k))}</button>`).join('')}
        </div>
        <div class="spacer"></div>
        ${selectedType ? `<div class="cancel-section"><button type="button" class="odo-btn odo-btn-ghost odo-btn-sm" data-act="cancel">✕ ${T.common.cancel}</button></div>` : ''}
        <div class="instructions${cfg ? ' multi-tooth-hint' : ''}">${instructions}</div>
      </div>
      ${archPicker}
      <div class="treatment-grid">
        ${items.map((item) => {
          const sel = isSelected(item);
          const both = supportsBothModes(item.type);
          const badge = item.isAtomic
            ? `<span class="multi-tooth-badge">${item.atomicIcon}</span>`
            : both ? `<span class="multi-tooth-badge multi-tooth-badge-hint">${ICON_LAYERS}</span>` : '';
          return `<div class="treatment-cell">
            <button type="button" class="treatment-btn${sel ? ' selected' : ''}${isSurfaceTreatment(item.type) ? ' is-surface' : ''}${item.isAtomic ? ' atomic-multi-btn' : ''}${sel && both ? ' has-mode-selector' : ''}${isGlobalScope(item.scope) ? ' is-global' : ''}"
              data-type="${item.type}"${item.code ? ` data-code="${esc(item.code)}"` : ''} data-scope="${item.scope}" title="${esc(tooltipFor(item))}">
              <div class="treatment-icon">${iconSvg(item.iconKey, 22, getTreatmentColor(item.type))}</div>
              <span class="treatment-label">${esc(item.label)}</span>
              ${badge}
            </button>
            ${sel && both ? `<div class="mode-selector-inline">
              <button type="button" class="mode-chip${!isMultiMode() ? ' active' : ''}" data-multi="0" data-type="${item.type}">◦ ${T.oneTooth}</button>
              <button type="button" class="mode-chip${isMultiMode() ? ' active' : ''}" data-multi="1" data-type="${item.type}">${ICON_LINK} ${T.multipleTeeth}</button>
            </div>` : ''}
          </div>`;
        }).join('')}
      </div>
    </div>`;
  }

  // ------------------------------------------------------------ sélection
  function selectRegular(item) {
    const allowed = getAllowedStatusesForTreatment(item.type);
    if (!allowed.includes(selectedStatus)) { selectedStatus = allowed[0]; onStatus(selectedStatus); }
    selectedType = item.type;
    selectedCode = item.code;
    archPickerItem = null;
    render();
    onSelect(item.type, item.code);
  }

  function selectItem(item) {
    if (isGlobalScope(item.scope)) {
      // Raccourci global : bouche complète → application directe ; arcade → choix de l'arcade.
      if (item.scope === 'global_mouth') { archPickerItem = null; render(); if (onGlobal) onGlobal(item, null); return; }
      archPickerItem = item;
      render();
      return;
    }
    selectRegular(item);
  }

  function onClick(e) {
    const chip = e.target.closest('.mode-chip');
    if (chip) {
      e.stopPropagation();
      const type = chip.dataset.type;
      const next = chip.dataset.multi === '1' ? MULTI_TOOTH_WRAPPER_BY_TYPE[type] : type;
      if (next && next !== selectedType) { selectedType = next; render(); onSelect(next, selectedCode); }
      return;
    }
    const archBtn = e.target.closest('[data-arch]');
    if (archBtn && archPickerItem) {
      const item = archPickerItem;
      archPickerItem = null;
      render();
      if (onGlobal) onGlobal(item, archBtn.dataset.arch);
      return;
    }
    if (e.target.closest('[data-act="arch-cancel"]')) { archPickerItem = null; render(); return; }
    const sb = e.target.closest('[data-status]');
    if (sb) { selectedStatus = sb.dataset.status; render(); onStatus(selectedStatus); return; }
    const cat = e.target.closest('[data-category]');
    if (cat) { activeCategory = cat.dataset.category; archPickerItem = null; render(); return; }
    if (e.target.closest('[data-act="cancel"]')) { selectedType = null; selectedCode = null; archPickerItem = null; render(); onCancel(); return; }
    const btn = e.target.closest('.treatment-btn');
    if (btn) {
      const item = findItem(btn.dataset.type, btn.dataset.code || null);
      if (item) selectItem(item);
    }
  }

  el.addEventListener('click', onClick);
  render();

  return {
    update(next) {
      if ('catalog' in next) catalog = next.catalog || [];
      if ('categories' in next) categories = next.categories || [];
      if ('typeDescriptions' in next) typeDescriptions = next.typeDescriptions || {};
      if ('selectedType' in next) selectedType = next.selectedType;
      if ('selectedCode' in next) selectedCode = next.selectedCode || null;
      if ('selectedStatus' in next) selectedStatus = next.selectedStatus;
      render();
    },
    /** Libellé de la sélection courante (acte du catalogue ou type). */
    selectedLabel() {
      const item = findItem(selectedType, selectedCode);
      return item ? item.label : '';
    },
    destroy() { el.removeEventListener('click', onClick); el.innerHTML = ''; },
  };
}
