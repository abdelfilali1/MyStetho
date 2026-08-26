/**
 * Client API + toast pour l'odontogramme et le parodontogramme.
 *
 * Pose lui-même les en-têtes CSRF (cookie `csrf_token`) pour fonctionner
 * aussi hors de base.html (page /dental/{id}?embed=1).
 */

export class ApiError extends Error {
  constructor(status, message, details) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

function getCookie(name) {
  const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
  return m ? decodeURIComponent(m[1]) : '';
}

export async function request(method, url, body) {
  const headers = { Accept: 'application/json', 'X-Requested-With': 'fetch' };
  if (method !== 'GET' && method !== 'HEAD') {
    headers['X-CSRF-Token'] = getCookie('csrf_token');
  }
  const init = { method, headers, credentials: 'same-origin' };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(url, init);
  if (res.status === 204) return null;
  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch (e) { data = null; }
  }
  if (!res.ok) {
    const msg = (data && (data.error || data.detail)) || `Erreur HTTP ${res.status}`;
    throw new ApiError(res.status, typeof msg === 'string' ? msg : `Erreur HTTP ${res.status}`, data && data.details);
  }
  return data;
}

// ============================================================================
// Toast (avec action optionnelle, ex. « Annuler »)
// ============================================================================

let _toastEl = null;
let _toastTimer = null;

export function toast(message, opts = {}) {
  const { type = 'success', action = null, duration = 3200 } = opts;
  if (!_toastEl) {
    _toastEl = document.createElement('div');
    _toastEl.className = 'odonto-toast';
    _toastEl.setAttribute('role', 'status');
    document.body.appendChild(_toastEl);
  }
  _toastEl.className = `odonto-toast odonto-toast-${type}`;
  _toastEl.innerHTML = '';
  const span = document.createElement('span');
  span.textContent = message;
  _toastEl.appendChild(span);
  if (action) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'odonto-toast-action';
    btn.textContent = action.label;
    btn.addEventListener('click', () => {
      hideToast();
      action.onClick();
    });
    _toastEl.appendChild(btn);
  }
  requestAnimationFrame(() => _toastEl.classList.add('visible'));
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(hideToast, duration);
}

function hideToast() {
  if (_toastEl) _toastEl.classList.remove('visible');
}

// ============================================================================
// Statuts : back « planned | performed » ↔ UI « planned | existing »
// ============================================================================

export function toBackendStatus(s) {
  return s === 'existing' ? 'performed' : s;
}

export function fromBackendStatus(s) {
  return s === 'performed' ? 'existing' : 'planned';
}

export function normalizeTreatment(t) {
  return { ...t, status: fromBackendStatus(t.status) };
}

// ============================================================================
// Odontogramme
// ============================================================================

export function odontoApi(patientId) {
  const base = `/odonto/${patientId}`;
  return {
    async get() {
      const d = await request('GET', base);
      return { ...d, treatments: (d.treatments || []).map(normalizeTreatment) };
    },
    updateTooth(toothNumber, payload) {
      return request('PUT', `${base}/teeth/${toothNumber}`, payload);
    },
    history(page = 1, pageSize = 100) {
      return request('GET', `${base}/history?page=${page}&page_size=${pageSize}`);
    },
    timeline() {
      return request('GET', `${base}/timeline`);
    },
    async at(date) {
      const d = await request('GET', `${base}/at?date=${encodeURIComponent(date)}`);
      return { ...d, treatments: (d.treatments || []).map(normalizeTreatment) };
    },
    async createTreatment(payload) {
      const body = { ...payload, status: toBackendStatus(payload.status) };
      return normalizeTreatment(await request('POST', `${base}/treatments`, body));
    },
    async listTreatments() {
      const d = await request('GET', `${base}/treatments`);
      return (d.data || []).map(normalizeTreatment);
    },
    async updateTreatment(id, payload) {
      const body = { ...payload };
      if (body.status) body.status = toBackendStatus(body.status);
      return normalizeTreatment(await request('PUT', `${base}/treatments/${id}`, body));
    },
    async performTreatment(id, consultationId) {
      return normalizeTreatment(await request('PATCH', `${base}/treatments/${id}/perform`, { consultation_id: consultationId || null }));
    },
    deleteTreatment(id) {
      return request('DELETE', `${base}/treatments/${id}`);
    },
  };
}

// ============================================================================
// Parodontogramme
// ============================================================================

export function perioApi(patientId) {
  const base = `/perio/${patientId}`;
  return {
    timeline: () => request('GET', `${base}/timeline`),
    draft: () => request('GET', `${base}/draft`),
    openDraft: () => request('POST', `${base}/draft`, {}),
    snapshot: (id) => request('GET', `${base}/snapshots/${id}`),
    patchTooth: (id, tooth, patch) => request('PATCH', `${base}/snapshots/${id}/teeth/${tooth}`, patch),
    patchSite: (id, tooth, code, patch) => request('PATCH', `${base}/snapshots/${id}/teeth/${tooth}/sites/${code}`, patch),
    close: (id) => request('POST', `${base}/snapshots/${id}/close`, {}),
    discard: (id) => request('DELETE', `${base}/snapshots/${id}`),
    indices: (id) => request('GET', `${base}/snapshots/${id}/indices`),
  };
}
