/**
 * Curseur chronologique (port de dentalpin `TimelineSlider.vue`).
 *
 * - positions discrètes (une par date) + nœud « Maintenant »
 * - libellés, badge sur le pouce, drag souris/tactile
 * - clavier ←/→/Début/Fin, bouton « Revenir à l'état actuel »
 */

import { T, esc, formatShortDate } from './constants.js';

function todayIso() {
  const d = new Date();
  const p = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/**
 * @param {HTMLElement} el
 * @param {{dates:Array<{date:string,change_count:number}>, currentDate:string|null, disabled?:boolean, onChange:(date:string|null)=>void}} opts
 */
export function createTimeline(el, opts) {
  let dates = opts.dates || [];
  let currentDate = opts.currentDate || null;
  let disabled = !!opts.disabled;
  let dragging = false;
  let track = null;

  const lastDateIsToday = () => dates.length > 0 && dates[dates.length - 1].date === todayIso();
  const currentIndex = () => (currentDate ? dates.findIndex((d) => d.date === currentDate) : null);
  const totalPositions = () => (lastDateIsToday() ? dates.length : dates.length + 1);
  const positionPercent = (i) => (totalPositions() <= 1 ? 100 : (i / (totalPositions() - 1)) * 100);

  function markerState(i) {
    const isLastAndToday = lastDateIsToday() && i === dates.length - 1;
    const ci = currentIndex();
    if (isLastAndToday && ci === null) return 'now';
    if (ci === i) return 'selected';
    if (ci !== null && i < ci) return 'past';
    return 'future';
  }

  function selectIndex(i) {
    if (disabled) return;
    if (i === null || i < 0 || i >= dates.length) { emit(null); return; }
    if (lastDateIsToday() && i === dates.length - 1) { emit(null); return; }
    emit(dates[i].date);
  }

  function emit(date) {
    if (date === currentDate) return;
    currentDate = date;
    render();
    opts.onChange(date);
  }

  function goPrev() {
    const ci = currentIndex();
    if (ci === null) {
      const last = lastDateIsToday() ? dates.length - 2 : dates.length - 1;
      if (last >= 0) selectIndex(last);
    } else if (ci > 0) selectIndex(ci - 1);
  }

  function goNext() {
    const ci = currentIndex();
    if (ci === null) return;
    const last = lastDateIsToday() ? dates.length - 2 : dates.length - 1;
    if (ci < last) selectIndex(ci + 1); else selectIndex(null);
  }

  function indexFromClientX(clientX) {
    const rect = track.getBoundingClientRect();
    const pct = Math.max(0, Math.min(100, ((clientX - rect.left) / rect.width) * 100));
    const target = Math.round((pct / 100) * (totalPositions() - 1));
    return target >= dates.length ? null : target;
  }

  function render() {
    const ci = currentIndex();
    const viewingHistory = currentDate !== null;
    const thumbPos = ci === null ? (lastDateIsToday() ? positionPercent(dates.length - 1) : 100) : positionPercent(ci);
    const thumbLabel = ci === null || !dates[ci] ? T.common.now : formatShortDate(dates[ci].date);

    let markers = '';
    dates.forEach((entry, i) => {
      const st = markerState(i);
      const isLastAndToday = lastDateIsToday() && i === dates.length - 1;
      const label = isLastAndToday ? T.common.now : formatShortDate(entry.date);
      markers += `<div class="odo-tl-marker" data-index="${i}" style="left:${positionPercent(i)}%" title="${esc(formatShortDate(entry.date))} (${entry.change_count} ${T.common.change(entry.change_count)})">
        <div class="odo-tl-dot state-${st}"></div>
        <span class="odo-tl-label state-${st}">${esc(label)}</span>
      </div>`;
    });
    if (!lastDateIsToday()) {
      markers += `<div class="odo-tl-marker odo-tl-now" data-index="now" style="left:100%">
        <div class="odo-tl-dot state-now${ci === null ? ' active' : ''}"></div>
        <span class="odo-tl-label ${ci === null ? 'state-now' : 'state-past'}">${T.common.now}</span>
      </div>`;
    }

    el.innerHTML = `<div class="odo-timeline${disabled ? ' disabled' : ''}">
      <div class="odo-tl-header">
        <span class="odo-tl-title">${T.timeline.title}</span>
        <div class="odo-tl-return">${viewingHistory ? `<button type="button" class="odo-btn odo-btn-soft odo-btn-xs" data-act="now">${T.timeline.returnToNow}</button>` : ''}</div>
      </div>
      <div class="odo-tl-track" tabindex="0" role="slider" aria-valuemin="0" aria-valuemax="${dates.length}" aria-valuenow="${ci === null ? dates.length : ci}">
        <div class="odo-tl-line"></div>
        ${markers}
        <div class="odo-tl-thumb${dragging ? ' dragging' : ''}" style="left:${thumbPos}%">
          <div class="odo-tl-badge ${ci === null ? 'now' : 'selected'}">${esc(thumbLabel)}</div>
          <div class="odo-tl-knob"></div>
        </div>
      </div>
    </div>`;
    track = el.querySelector('.odo-tl-track');
  }

  function onClick(e) {
    const btn = e.target.closest('[data-act="now"]');
    if (btn) { emit(null); return; }
    const marker = e.target.closest('.odo-tl-marker');
    if (marker) {
      const idx = marker.dataset.index;
      selectIndex(idx === 'now' ? null : Number(idx));
      return;
    }
    if (e.target.closest('.odo-tl-knob')) return;
    if (e.target.closest('.odo-tl-track')) selectIndex(indexFromClientX(e.clientX));
  }

  function onKeydown(e) {
    if (!e.target.closest('.odo-tl-track') || disabled) return;
    const map = { ArrowLeft: goPrev, ArrowRight: goNext, Home: () => selectIndex(0), End: () => selectIndex(null) };
    if (map[e.key]) { e.preventDefault(); map[e.key](); }
  }

  function onDragStart(e) {
    if (!e.target.closest('.odo-tl-knob') || disabled) return;
    dragging = true;
    e.preventDefault();
  }

  function onDragMove(e) {
    if (!dragging || !track) return;
    const clientX = e.touches ? (e.touches[0] && e.touches[0].clientX) : e.clientX;
    if (clientX === undefined) return;
    selectIndex(indexFromClientX(clientX));
  }

  function onDragEnd() {
    if (dragging) { dragging = false; render(); }
  }

  el.addEventListener('click', onClick);
  el.addEventListener('keydown', onKeydown);
  el.addEventListener('mousedown', onDragStart);
  el.addEventListener('touchstart', onDragStart, { passive: false });
  document.addEventListener('mousemove', onDragMove);
  document.addEventListener('mouseup', onDragEnd);
  document.addEventListener('touchmove', onDragMove);
  document.addEventListener('touchend', onDragEnd);

  render();

  return {
    update(next) {
      if (next.dates) dates = next.dates;
      if ('currentDate' in next) currentDate = next.currentDate;
      if ('disabled' in next) disabled = !!next.disabled;
      render();
    },
    destroy() {
      el.removeEventListener('click', onClick);
      el.removeEventListener('keydown', onKeydown);
      el.removeEventListener('mousedown', onDragStart);
      el.removeEventListener('touchstart', onDragStart);
      document.removeEventListener('mousemove', onDragMove);
      document.removeEventListener('mouseup', onDragEnd);
      document.removeEventListener('touchmove', onDragMove);
      document.removeEventListener('touchend', onDragEnd);
      el.innerHTML = '';
    },
  };
}
