const SPEC_ICONS = {
  'Cardiologie': '<path d="M8 13s-5-3.5-5-7a3 3 0 016 0 3 3 0 016 0c0 3.5-5 7-5 7" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round"/>',
  'Pédiatrie': '<circle cx="8" cy="6" r="3" stroke="currentColor" stroke-width="1.4" fill="none"/><path d="M3 14c0-2.8 2.2-5 5-5s5 2.2 5 5" stroke="currentColor" stroke-width="1.4" fill="none"/>',
  'Dermatologie': '<path d="M8 2a5 5 0 015 5c0 3-3 6-5 8-2-2-5-5-5-8a5 5 0 015-5z" stroke="currentColor" stroke-width="1.4" fill="none"/>',
  'Gynécologie': '<circle cx="8" cy="7" r="4" stroke="currentColor" stroke-width="1.4" fill="none"/><path d="M8 11v4M6 13h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
  'Orthopédie': '<path d="M5 2l2 4h2l2-4M8 6v8M5 14h6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" fill="none"/>',
  'Neurologie': '<path d="M4 8c0-2.2 1.8-4 4-4s4 1.8 4 4c0 1.5-.9 2.8-2 3.5V13H6v-1.5C4.9 10.8 4 9.5 4 8z" stroke="currentColor" stroke-width="1.4" fill="none"/>',
  'Ophtalmologie': '<ellipse cx="8" cy="8" rx="5" ry="3.5" stroke="currentColor" stroke-width="1.4" fill="none"/><circle cx="8" cy="8" r="1.8" fill="currentColor"/>',
  'Médecine générale': '<path d="M8 2v12M2 8h12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  'ORL': '<path d="M8 3a4 4 0 014 4c0 2-1 3-2 4H6c-1-1-2-2-2-4a4 4 0 014-4z" stroke="currentColor" stroke-width="1.4" fill="none"/><path d="M6 11v2h4v-2" stroke="currentColor" stroke-width="1.4" fill="none"/>',
  'Psychiatrie': '<path d="M5 5a3 3 0 016 0c0 1.5-1 2.5-2 3L8 11" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round"/><circle cx="8" cy="13" r="1" fill="currentColor"/>',
  'Rhumatologie': '<circle cx="8" cy="5" r="2.5" stroke="currentColor" stroke-width="1.4" fill="none"/><circle cx="4" cy="11" r="2" stroke="currentColor" stroke-width="1.4" fill="none"/><circle cx="12" cy="11" r="2" stroke="currentColor" stroke-width="1.4" fill="none"/>',
  'Endocrinologie': '<path d="M8 2a3 3 0 013 3c0 3-3 4-3 4s-3-1-3-4a3 3 0 013-3z" stroke="currentColor" stroke-width="1.4" fill="none"/><path d="M5 10l-1 4M11 10l1 4M8 9v5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
  'Gastro-entérologie': '<path d="M6 3c-2 0-3 2-3 4 0 3 2 5 5 7 3-2 5-4 5-7 0-2-1-4-3-4-1 0-2 1-2 1s-1-1-2-1z" stroke="currentColor" stroke-width="1.4" fill="none"/>',
  'Urologie': '<path d="M8 2v8M6 6l2 4 2-4M5 10a3 3 0 006 0" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" fill="none"/>',
  'Pneumologie': '<path d="M8 4v4M5 5c-2 1-3 3-3 5 0 1.5 1.5 3 3 2M11 5c2 1 3 3 3 5 0 1.5-1.5 3-3 2" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round"/>',
  'Chirurgie dentaire': '<path d="M5 2c-1 1-2 3-2 4 0 2 1 4 2 6h6c1-2 2-4 2-6 0-1-1-3-2-4" stroke="currentColor" stroke-width="1.4" fill="none"/><path d="M6 12l1 2 1-2 1 2 1-2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
  'Chirurgie': '<path d="M3 13l4-4M10 3l3 3-7 7H3v-3l7-7z" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
};

function avatarHTML(d, size) {
  const initials = (d.prenom[0] + d.nom[0]).toUpperCase();
  const cls = d.sexe === 'F' ? 'dv-avatar dv-avatar-f' : 'dv-avatar';
  return `<div class="${cls}" style="width:${size}px;height:${size}px;font-size:${Math.round(size*0.36)}px;">${initials}</div>`;
}

function starsHTML(note, avis, compact) {
  const full = Math.floor(note);
  let s = '';
  for (let i = 1; i <= 5; i++)
    s += `<span style="color:${i <= full ? 'var(--gold)' : 'var(--border-strong)'}">★</span>`;
  if (compact)
    return `<span class="dv-stars"><span class="dv-stars-rating">${s}</span> ${note}</span>`;
  return `<span class="dv-stars"><span class="dv-stars-rating">${s}</span> ${note} <span style="color:var(--text-soft);font-weight:400;">(${avis})</span></span>`;
}

function verifiedHTML() {
  return `<span class="dv-badge dv-badge-verified"><svg viewBox="0 0 12 12" fill="none"><path d="M10 3L5 9 2 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg> Vérifié</span>`;
}

function convHTML() {
  return `<span class="dv-badge dv-badge-conv">Conventionné</span>`;
}

async function apiPost(path, data) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
