/**
 * Odontogramme — constantes (port de dentalpin `odontogramConstants.ts`,
 * `constants/odontogram.ts` et des libellés FR de `fr.json`).
 */

// ============================================================================
// Dents (notation FDI)
// ============================================================================

export const PERMANENT_TEETH = {
  upperRight: [18, 17, 16, 15, 14, 13, 12, 11],
  upperLeft: [21, 22, 23, 24, 25, 26, 27, 28],
  lowerRight: [48, 47, 46, 45, 44, 43, 42, 41],
  lowerLeft: [31, 32, 33, 34, 35, 36, 37, 38],
};

export const DECIDUOUS_TEETH = {
  upperRight: [55, 54, 53, 52, 51],
  upperLeft: [61, 62, 63, 64, 65],
  lowerRight: [85, 84, 83, 82, 81],
  lowerLeft: [71, 72, 73, 74, 75],
};

export const SURFACES = ['M', 'D', 'O', 'V', 'L'];

export const UPPER_ARCH_ORDER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28];
export const LOWER_ARCH_ORDER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38];

export function isDeciduousTooth(n) {
  const q = Math.floor(n / 10);
  return q >= 5 && q <= 8;
}

export function isUpperTooth(n) {
  const q = Math.floor(n / 10);
  return q === 1 || q === 2 || q === 5 || q === 6;
}

export function isRightTooth(n) {
  const q = Math.floor(n / 10);
  return q === 1 || q === 4 || q === 5 || q === 8;
}

export function getToothCategory(n) {
  const q = Math.floor(n / 10);
  const p = n % 10;
  if (q >= 5 && q <= 8) {
    if (p === 1 || p === 2) return 'incisor';
    if (p === 3) return 'canine';
    return 'molar';
  }
  if (p === 1 || p === 2) return 'incisor';
  if (p === 3) return 'canine';
  if (p === 4 || p === 5) return 'premolar';
  return 'molar';
}

export function getArchOrder(n) {
  if (UPPER_ARCH_ORDER.includes(n)) return UPPER_ARCH_ORDER;
  if (LOWER_ARCH_ORDER.includes(n)) return LOWER_ARCH_ORDER;
  return null;
}

/** Dents contiguës entre `start` et `end` (inclus) sur la même arcade. Lève 'same_arch_required'. */
export function calculateToothRange(start, end) {
  const arch = getArchOrder(start);
  if (!arch || !arch.includes(end)) throw new Error('same_arch_required');
  const i = arch.indexOf(start);
  const j = arch.indexOf(end);
  const [a, b] = i <= j ? [i, j] : [j, i];
  return arch.slice(a, b + 1);
}

export function isSameArch(teeth) {
  if (teeth.length <= 1) return true;
  const first = getArchOrder(teeth[0]);
  if (!first) return false;
  return teeth.every((t) => getArchOrder(t) === first);
}

// ============================================================================
// Libellés FR
// ============================================================================

export const T = {
  title: 'Odontogramme',
  tooth: 'Dent',
  readOnly: 'Lecture seule',
  legend: 'Légende',
  statusLegend: 'Statut du traitement',
  dentition: { permanent: 'Permanentes', deciduous: 'Temporaires' },
  quadrants: { upper: 'Arcade supérieure', lower: 'Arcade inférieure' },
  surfaces: { M: 'Mésiale', D: 'Distale', O: 'Occlusale', V: 'Vestibulaire', L: 'Linguale' },
  status: { existing: 'Existant', planned: 'Planifié' },
  categories: {
    diagnostico: 'Diagnostic',
    preventivo: 'Préventif',
    restauradora: 'Restauration',
    cirugia: 'Chirurgie',
    endodoncia: 'Endodontie',
    periodoncia: 'Parodontie',
    ortodoncia: 'Orthodontie',
    estetica: 'Esthétique',
    protesis: 'Prothèses',
    pediatrica: 'Odontologie pédiatrique',
  },
  globals: {
    category: 'Bouche complète',
    applied: (name) => `${name} ajouté`,
    archPickerTitle: (name) => `Quelle arcade pour « ${name} » ?`,
    upperArch: 'Arcade supérieure',
    lowerArch: 'Arcade inférieure',
  },
  types: {
    pulpitis: 'Pulpite',
    caries: 'Carie',
    incipient_caries: 'Carie naissante',
    pigmentation: 'Pigmentation',
    fracture: 'Fracture',
    missing: 'Absente',
    periapical_small: 'Lésion périapicale <2 mm',
    periapical_medium: 'Lésion périapicale 2-4 mm',
    periapical_large: 'Lésion périapicale >4 mm',
    rotated: 'Tournée',
    displaced: 'Déplacée',
    unerupted: 'Non éruptée',
    filling: 'Obturation',
    filling_composite: 'Obturation en composite',
    filling_amalgam: 'Obturation en amalgame',
    filling_temporary: 'Obturation provisoire',
    sealant: 'Scellant',
    veneer: 'Facette',
    inlay: 'Inlay',
    overlay: 'Onlay',
    crown: 'Couronne',
    crown_on_implant: 'Couronne sur implant',
    provisional_crown_on_implant: 'Couronne provisoire sur implant',
    pontic: 'Pont',
    bridge_abutment: 'Pilier de bridge',
    bridge: 'Bridge fixe',
    splint: 'Attelle',
    extraction: 'Extraction',
    implant: 'Implant',
    apicoectomy: 'Apicectomie',
    root_canal: 'Traitement canalaire',
    root_canal_full: 'Dépulpage complet',
    root_canal_two_thirds: 'Traitement canalaire 2/3',
    root_canal_half: 'Traitement canalaire 1/2',
    root_canal_overfill: 'Surcharge de traitement canalaire',
    post: 'Tenon radiculaire',
    bracket: 'Bracket',
    tube: 'Tube',
    band: 'Bague',
    attachment: 'Attachement',
    retainer: 'Contention',
    other: 'Autre traitement',
  },
  conditions: {
    healthy: 'Saine',
    caries: 'Carie',
    filling: 'Obturation',
    crown: 'Couronne',
    missing: 'Absente',
    root_canal: 'Traitement canalaire',
    implant: 'Implant',
    extraction_indicated: 'Extraction indiquée',
    sealant: 'Scellant',
    fracture: 'Fracture',
  },
  historyChangeTypes: {
    created: 'Créé',
    general_condition: 'État général',
    surface_update: 'Mise à jour de surface',
  },
  toothNames: {
    centralIncisor: 'Incisive centrale',
    lateralIncisor: 'Incisive latérale',
    canine: 'Canine',
    firstPremolar: 'Première prémolaire',
    secondPremolar: 'Deuxième prémolaire',
    firstMolar: 'Première molaire',
    secondMolar: 'Deuxième molaire',
    thirdMolar: 'Troisième molaire',
  },
  positions: { upper: 'supérieure', lower: 'inférieure', left: 'gauche', right: 'droite' },
  views: { occlusal: 'Vue occlusale', lateral: 'Vue latérale' },
  selectSurfaces: 'Sélectionner les surfaces',
  selectedSurfaces: 'Surfaces sélectionnées',
  surfacesSelected: 'surface(s) sélectionnée(s)',
  instructions: {
    selectTreatment: 'Sélectionnez un traitement à appliquer',
    clickTooth: 'Cliquez sur la dent pour appliquer',
  },
  oneTooth: '1 dent',
  multipleTeeth: 'Plusieurs dents',
  tooltip: { clickToEdit: 'Cliquer pour modifier', noTreatments: 'Aucun traitement enregistré' },
  treatments: {
    selectStatus: 'Sélectionner le statut',
    markPerformed: 'Marquer comme réalisé',
    treatmentAdded: 'Traitement ajouté',
    treatmentPerformed: 'Traitement marqué comme réalisé',
    treatmentDeleted: 'Traitement supprimé',
    updated: 'Odontogramme mis à jour',
  },
  treatmentList: { title: 'Liste des traitements', noTreatments: 'Aucun traitement enregistré' },
  changeHistory: { title: 'Historique des modifications', noChanges: 'Aucune modification enregistrée', treatmentAdded: 'Traitement' },
  timeline: {
    title: 'Chronologie',
    returnToNow: "Revenir à l'état actuel",
    noHistory: 'Aucun historique antérieur',
  },
  messages: { loadError: "Impossible de charger l'odontogramme", error: "Erreur lors de la mise à jour de l'odontogramme" },
  multiTooth: {
    labels: {
      bridge: 'Bridge fixe',
      splint: 'Attelle',
      multiple_veneers: 'Facettes multiples',
      multiple_crowns: 'Couronnes multiples',
    },
    pillar: 'pilier',
    pontic: 'pont',
    roleHint: 'Cliquez sur une dent pour basculer pilier / pont.',
    needPillar: 'Le bridge nécessite au moins une dent pilier.',
    confirmHint: (n) => `Vous êtes sur le point de créer un groupe de traitement avec ${n} dents.`,
    willBePlanned: 'Le groupe sera marqué comme planifié.',
    willBeExisting: 'Le groupe sera enregistré comme existant.',
    hints: {
      range: 'Cliquez sur la première dent, puis sur la dernière',
      free: 'Cliquez pour ajouter ou retirer des dents',
    },
    errors: {
      tooFew: (n) => `Au moins ${n} dents requises`,
      tooMany: (n) => `Maximum ${n} dents autorisées`,
      sameArchRequired: 'Les dents doivent être dans la même arcade',
    },
  },
  common: {
    now: 'Maintenant',
    cancel: 'Annuler',
    undo: 'Annuler',
    undone: 'Annulé',
    confirm: 'Confirmer',
    save: 'Enregistrer',
    delete: 'Supprimer',
    retry: 'Réessayer',
    error: 'Erreur',
    change: (n) => (n > 1 ? 'modifications' : 'modification'),
    today: "Aujourd'hui",
  },
};

export function typeLabel(type) {
  return T.types[type] || type;
}

/** Libellé d'un traitement : nom de l'acte du catalogue si présent, sinon le type clinique
 *  (port de `getTreatmentDisplayName`). Accepte un traitement brut ou une vue par dent. */
export function treatmentLabel(v) {
  if (!v) return '';
  return v.catalog_label || typeLabel(v.treatment_type || v.clinical_type);
}

export function archLabel(arch) {
  if (arch === 'upper') return T.globals.upperArch;
  if (arch === 'lower') return T.globals.lowerArch;
  return '';
}

export function getToothNameKey(n) {
  const p = n % 10;
  if (isDeciduousTooth(n)) {
    return { 1: 'centralIncisor', 2: 'lateralIncisor', 3: 'canine', 4: 'firstMolar', 5: 'secondMolar' }[p] || 'centralIncisor';
  }
  return {
    1: 'centralIncisor', 2: 'lateralIncisor', 3: 'canine', 4: 'firstPremolar',
    5: 'secondPremolar', 6: 'firstMolar', 7: 'secondMolar', 8: 'thirdMolar',
  }[p] || 'centralIncisor';
}

/** « Première molaire supérieure droite » */
export function toothName(n) {
  const name = T.toothNames[getToothNameKey(n)];
  const vertical = isUpperTooth(n) ? T.positions.upper : T.positions.lower;
  const horizontal = isRightTooth(n) ? T.positions.right : T.positions.left;
  return `${name} ${vertical} ${horizontal}`;
}

// ============================================================================
// Règles de visualisation
// ============================================================================

export const VISUALIZATION_RULES = {
  pulp_fill: ['pulpitis', 'root_canal_full', 'root_canal_two_thirds', 'root_canal_half', 'root_canal_overfill'],
  occlusal_surface: ['caries', 'incipient_caries', 'pigmentation', 'filling_composite', 'filling_amalgam', 'filling_temporary', 'sealant', 'veneer'],
  lateral_icon: [
    'fracture', 'missing', 'periapical_small', 'periapical_medium', 'periapical_large', 'rotated', 'displaced',
    'implant', 'apicoectomy', 'extraction', 'post', 'root_canal_overfill', 'bracket', 'tube', 'band',
    'attachment', 'retainer', 'splint',
  ],
  pattern_fill: ['unerupted', 'inlay', 'pontic', 'bridge_abutment', 'overlay', 'crown'],
};

export const OCCLUSAL_VISUALIZATION = {
  caries: { type: 'solid_fill', color: '#EF4444' },
  incipient_caries: { type: 'dot', color: '#F97316' },
  pigmentation: { type: 'dot', color: '#92400E' },
  filling_composite: { type: 'solid_fill', color: '#3B82F6' },
  filling_amalgam: { type: 'solid_fill', color: '#6B7280' },
  filling_temporary: { type: 'solid_fill', color: '#22C55E' },
  sealant: { type: 'outline', color: '#7DD3FC' },
  veneer: { type: 'solid_fill', color: '#FEF3C7' },
};

export const PATTERN_CONFIG = {
  unerupted: { type: 'diagonal_stripes', color: '#9CA3AF' },
  inlay: { type: 'dots', color: '#3B82F6' },
  pontic: { type: 'grid', color: '#3B82F6' },
  bridge_abutment: { type: 'vertical_stripes', color: '#3B82F6' },
  overlay: { type: 'horizontal_stripes', color: '#3B82F6' },
  crown: { type: 'diagonal_stripes', color: '#F59E0B' },
};

export const PULP_FILL_CONFIG = {
  pulpitis: { level: 'full', color: '#EF4444' },
  root_canal_full: { level: 'full', color: '#3B82F6' },
  root_canal_two_thirds: { level: 'two_thirds', color: '#3B82F6' },
  root_canal_half: { level: 'half', color: '#3B82F6' },
  root_canal_overfill: { level: 'full', color: '#3B82F6' },
};

export const SURFACE_TREATMENTS = [
  'caries', 'incipient_caries', 'pigmentation', 'filling_composite', 'filling_amalgam',
  'filling_temporary', 'sealant', 'veneer', 'inlay', 'filling',
];

export const WHOLE_TOOTH_TREATMENTS = [
  'pulpitis', 'fracture', 'missing', 'periapical_small', 'periapical_medium', 'periapical_large', 'rotated',
  'displaced', 'unerupted', 'overlay', 'crown', 'crown_on_implant', 'provisional_crown_on_implant', 'pontic',
  'bridge_abutment', 'bridge', 'splint', 'extraction', 'implant', 'apicoectomy', 'root_canal_full',
  'root_canal_two_thirds', 'root_canal_half', 'post', 'root_canal_overfill', 'bracket', 'tube', 'band',
  'attachment', 'retainer', 'root_canal', 'bridge_pontic',
];

export const LEGACY_TREATMENT_MAPPING = {
  filling: 'filling_composite',
  root_canal: 'root_canal_full',
  bridge_pontic: 'pontic',
};

export function normalizeTreatmentType(t) {
  return LEGACY_TREATMENT_MAPPING[t] || t;
}

export function isSurfaceTreatment(t) {
  return SURFACE_TREATMENTS.includes(normalizeTreatmentType(t));
}

export function isWholeToothTreatment(t) {
  return WHOLE_TOOTH_TREATMENTS.includes(normalizeTreatmentType(t));
}

export function getVisualizationRules(t) {
  const n = normalizeTreatmentType(t);
  return Object.keys(VISUALIZATION_RULES).filter((rule) => VISUALIZATION_RULES[rule].includes(n));
}

export function hasVisualizationRule(t, rule) {
  return VISUALIZATION_RULES[rule].includes(normalizeTreatmentType(t));
}

// ============================================================================
// Couleurs / statuts
// ============================================================================

export const TREATMENT_COLORS = {
  pulpitis: '#EF4444',
  caries: '#EF4444',
  incipient_caries: '#F97316',
  pigmentation: '#92400E',
  fracture: '#BE185D',
  missing: '#6B7280',
  periapical_small: '#EF4444',
  periapical_medium: '#DC2626',
  periapical_large: '#B91C1C',
  rotated: '#8B5CF6',
  displaced: '#F59E0B',
  unerupted: '#9CA3AF',
  filling_composite: '#3B82F6',
  filling_amalgam: '#6B7280',
  filling_temporary: '#22C55E',
  sealant: '#06B6D4',
  veneer: '#EC4899',
  inlay: '#3B82F6',
  overlay: '#3B82F6',
  crown: '#F59E0B',
  crown_on_implant: '#F59E0B',
  provisional_crown_on_implant: '#FCD34D',
  pontic: '#F97316',
  bridge_abutment: '#FBBF24',
  bridge: '#F59E0B',
  splint: '#3B82F6',
  extraction: '#DC2626',
  implant: '#10B981',
  apicoectomy: '#6366F1',
  root_canal_full: '#8B5CF6',
  root_canal_two_thirds: '#8B5CF6',
  root_canal_half: '#8B5CF6',
  post: '#7C3AED',
  root_canal_overfill: '#3B82F6',
  bracket: '#6366F1',
  tube: '#6366F1',
  band: '#8B5CF6',
  attachment: '#EC4899',
  retainer: '#14B8A6',
  filling: '#3B82F6',
  root_canal: '#8B5CF6',
  bridge_pontic: '#F97316',
};

export function getTreatmentColor(t) {
  return TREATMENT_COLORS[normalizeTreatmentType(t)] || '#6B7280';
}

export const STATUS_STYLES = {
  existing: { opacity: 1.0 },
  planned: { opacity: 0.7 },
};

export const PLANNED_INDICATOR_COLOR = '#EF4444';

// ============================================================================
// Catégories (barre de traitements)
// ============================================================================

export const TREATMENT_CATEGORIES = [
  {
    key: 'diagnostico',
    treatments: ['pulpitis', 'caries', 'incipient_caries', 'pigmentation', 'fracture', 'missing',
      'periapical_small', 'periapical_medium', 'periapical_large', 'rotated', 'displaced', 'unerupted'],
  },
  {
    key: 'restauradora',
    treatments: ['filling_composite', 'filling_amalgam', 'filling_temporary', 'sealant', 'veneer', 'inlay',
      'overlay', 'crown', 'bridge', 'splint'],
  },
  { key: 'cirugia', treatments: ['extraction', 'implant', 'apicoectomy'] },
  { key: 'endodoncia', treatments: ['root_canal_full', 'root_canal_two_thirds', 'root_canal_half', 'post', 'root_canal_overfill'] },
  { key: 'ortodoncia', treatments: ['bracket', 'tube', 'band', 'attachment', 'retainer'] },
];

export const CATEGORY_STATUS_RESTRICTIONS = {
  diagnostico: ['existing'],
  restauradora: ['existing', 'planned'],
  cirugia: ['existing', 'planned'],
  endodoncia: ['existing', 'planned'],
  ortodoncia: ['existing', 'planned'],
};

export function getCategoryForTreatment(t) {
  const n = normalizeTreatmentType(t);
  for (const c of TREATMENT_CATEGORIES) {
    if (c.treatments.includes(n)) return c.key;
  }
  return null;
}

export function getAllowedStatusesForTreatment(t) {
  const c = getCategoryForTreatment(t);
  return (c && CATEGORY_STATUS_RESTRICTIONS[c]) || ['existing', 'planned'];
}

/** Raccourcis clavier 1-8 (types réels). */
export const TREATMENT_SHORTCUTS = {
  1: 'extraction',
  2: 'filling_composite',
  3: 'root_canal_full',
  4: 'crown',
  5: 'implant',
  6: 'veneer',
  7: 'sealant',
  8: 'caries',
};

// ============================================================================
// Multi-dents (bridges, attelles, couronnes / facettes multiples)
// ============================================================================

export const MULTI_TOOTH_TREATMENTS = {
  bridge: { key: 'bridge', label: T.multiTooth.labels.bridge, mode: 'bridge', selectionMode: 'range', minTeeth: 2, maxTeeth: 14, requiresSameArch: true },
  splint: { key: 'splint', label: T.multiTooth.labels.splint, mode: 'uniform', selectionMode: 'free', minTeeth: 2, maxTeeth: 14, requiresSameArch: true },
  multiple_veneers: { key: 'veneer', label: T.multiTooth.labels.multiple_veneers, mode: 'uniform', selectionMode: 'free', minTeeth: 2, maxTeeth: 10, requiresSameArch: false },
  multiple_crowns: { key: 'crown', label: T.multiTooth.labels.multiple_crowns, mode: 'uniform', selectionMode: 'free', minTeeth: 2, maxTeeth: 28, requiresSameArch: false },
};

export function getMultiToothConfig(key) {
  return MULTI_TOOTH_TREATMENTS[key] || null;
}

export const MULTI_TOOTH_ONLY_TYPES = new Set(['pontic', 'bridge_abutment']);
export const ATOMIC_MULTI_TOOTH_TYPES = new Set(['bridge', 'splint']);
export const MULTI_TOOTH_WRAPPER_BY_TYPE = { crown: 'multiple_crowns', veneer: 'multiple_veneers' };

export function supportsBothModes(t) {
  return t in MULTI_TOOTH_WRAPPER_BY_TYPE;
}

export function isMultiToothOnlyType(t) {
  return MULTI_TOOTH_ONLY_TYPES.has(t);
}

// ============================================================================
// Utilitaires
// ============================================================================

export function esc(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export function formatDate(value) {
  if (!value) return '';
  const d = new Date(value.length === 10 ? value + 'T00:00:00' : value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function formatDateTime(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const p = (x) => String(x).padStart(2, '0');
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function formatShortDate(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
}
