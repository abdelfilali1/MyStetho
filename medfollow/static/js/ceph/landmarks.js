/**
 * Catalogue des points céphalométriques (téléradiographie de profil).
 *
 * `id` est la clé utilisée partout dans le moteur d'analyse. Les définitions
 * sont les définitions anatomiques conventionnelles, affichées au praticien au
 * moment où il pose le point.
 */

/**
 * Les couleurs de groupe servent à la fois de marqueurs sur la radio et de
 * texte dans les panneaux : elles sont donc de tonalité moyenne — assez
 * saturées pour ressortir sur l'os gris, assez sombres pour rester lisibles
 * sur fond blanc.
 */
export const LANDMARK_GROUPS = [
    { id: 'cranial-base', label: 'Base du crâne', color: '#2563eb' },
    { id: 'maxilla', label: 'Maxillaire', color: '#059669' },
    { id: 'mandible', label: 'Mandibule', color: '#d97706' },
    { id: 'dental', label: 'Dentaire', color: '#db2777' },
    { id: 'soft-tissue', label: 'Tissus mous', color: '#7c3aed' },
];

export const LANDMARKS = [
    // ---------- Base du crâne ----------
    {
        id: 'S', name: 'Sella (selle turcique)', abbr: 'S', group: 'cranial-base',
        definition: 'Centre géométrique de la selle turcique (fosse hypophysaire).',
    },
    {
        id: 'N', name: 'Nasion', abbr: 'N', group: 'cranial-base',
        definition: 'Point le plus antérieur de la suture fronto-nasale, dans le plan sagittal médian.',
    },
    {
        id: 'Po', name: 'Porion', abbr: 'Po', group: 'cranial-base',
        definition: 'Point le plus supérieur du conduit auditif externe.',
    },
    {
        id: 'Or', name: 'Orbitale', abbr: 'Or', group: 'cranial-base',
        definition: 'Point le plus inférieur du rebord infra-orbitaire.',
    },
    {
        id: 'Ba', name: 'Basion', abbr: 'Ba', group: 'cranial-base',
        definition: 'Point le plus inféro-postérieur du bord antérieur du foramen magnum.',
    },
    {
        id: 'Ar', name: 'Articulare', abbr: 'Ar', group: 'cranial-base',
        definition: 'Intersection de la face inférieure de la base du crâne et du bord postérieur du condyle mandibulaire.',
    },
    {
        id: 'Co', name: 'Condylion', abbr: 'Co', group: 'cranial-base',
        definition: 'Point le plus supéro-postérieur de la tête du condyle mandibulaire.',
    },
    {
        id: 'Bo', name: 'Point de Bolton', abbr: 'Bo', group: 'cranial-base',
        definition: 'Point le plus haut de la concavité rétro-condylienne, en arrière du condyle occipital.',
    },
    {
        id: 'Pt', name: 'Point ptérygoïdien', abbr: 'Pt', group: 'cranial-base',
        definition: 'Point le plus supéro-postérieur du contour de la fissure ptérygo-maxillaire (foramen rond).',
    },
    {
        id: 'PTM', name: 'Fissure ptérygo-maxillaire', abbr: 'PTM', group: 'cranial-base',
        definition: 'Point le plus inférieur de la fissure ptérygo-maxillaire (en forme de goutte).',
    },
    {
        id: 'Cc', name: 'Centre du crâne', abbr: 'Cc', group: 'cranial-base',
        definition: 'Intersection du plan Basion–Nasion et de la verticale ptérygoïdienne (axe Pt–Gn).',
    },

    // ---------- Maxillaire ----------
    {
        id: 'ANS', name: 'Épine nasale antérieure', abbr: 'ENA', group: 'maxilla',
        definition: 'Sommet de l’épine nasale antérieure osseuse, dans le plan sagittal médian.',
    },
    {
        id: 'PNS', name: 'Épine nasale postérieure', abbr: 'ENP', group: 'maxilla',
        definition: 'Point le plus postérieur du palais osseux, dans le plan sagittal médian.',
    },
    {
        id: 'A', name: 'Point A (sous-épineux)', abbr: 'A', group: 'maxilla',
        definition: 'Point le plus profond de la concavité antérieure du maxillaire, entre ENA et le prosthion.',
    },
    {
        id: 'Pr', name: 'Prosthion', abbr: 'Pr', group: 'maxilla',
        definition: 'Point le plus antéro-inférieur du procès alvéolaire maxillaire, entre les incisives centrales.',
    },
    {
        id: 'Key', name: 'Crête zygomatique (key ridge)', abbr: 'KR', group: 'maxilla',
        definition: 'Point le plus inférieur de la crête zygomatique du maxillaire.',
    },

    // ---------- Mandibule ----------
    {
        id: 'B', name: 'Point B (supra-mentonnier)', abbr: 'B', group: 'mandible',
        definition: 'Point le plus profond de la concavité antérieure de la symphyse mandibulaire, entre infradentale et pogonion.',
    },
    {
        id: 'Pog', name: 'Pogonion', abbr: 'Pog', group: 'mandible',
        definition: 'Point le plus antérieur du menton osseux, dans le plan sagittal médian.',
    },
    {
        id: 'Gn', name: 'Gnathion', abbr: 'Gn', group: 'mandible',
        definition: 'Point le plus antéro-inférieur du menton osseux ; milieu entre pogonion et menton.',
    },
    {
        id: 'Me', name: 'Menton', abbr: 'Me', group: 'mandible',
        definition: 'Point le plus inférieur de la symphyse mandibulaire.',
    },
    {
        id: 'Go', name: 'Gonion', abbr: 'Go', group: 'mandible',
        definition: 'Milieu de l’angle mandibulaire : bissectrice des tangentes au bord postérieur du ramus et au bord inférieur du corps.',
    },
    {
        id: 'Id', name: 'Infradentale', abbr: 'Id', group: 'mandible',
        definition: 'Point le plus antéro-supérieur du procès alvéolaire mandibulaire, entre les incisives centrales.',
    },
    {
        id: 'Pm', name: 'Supra-pogonion (protuberantia menti)', abbr: 'Pm', group: 'mandible',
        definition: 'Point où la courbure symphysaire passe de concave à convexe, entre B et le pogonion.',
    },
    {
        id: 'D', name: 'Point D', abbr: 'D', group: 'mandible',
        definition: 'Centre de la section de la symphyse mandibulaire.',
    },
    {
        id: 'Xi', name: 'Point Xi', abbr: 'Xi', group: 'mandible',
        definition: 'Centre géométrique du ramus mandibulaire, construit sur les bords du ramus dans le repère Francfort / PTV.',
    },
    {
        id: 'Dc', name: 'Point Dc', abbr: 'Dc', group: 'mandible',
        definition: 'Centre du col du condyle, sur le plan Basion–Nasion.',
    },
    {
        id: 'RamusPost', name: 'Bord postérieur du ramus', abbr: 'R1', group: 'mandible',
        definition: 'Point le plus profond du bord postérieur du ramus mandibulaire.',
    },

    // ---------- Dentaire ----------
    {
        id: 'U1T', name: 'Bord libre incisive supérieure', abbr: 'IS bord', group: 'dental',
        definition: 'Bord incisif de l’incisive centrale maxillaire la plus antérieure.',
    },
    {
        id: 'U1A', name: 'Apex incisive supérieure', abbr: 'IS apex', group: 'dental',
        definition: 'Apex radiculaire de l’incisive centrale maxillaire la plus antérieure.',
    },
    {
        id: 'L1T', name: 'Bord libre incisive inférieure', abbr: 'II bord', group: 'dental',
        definition: 'Bord incisif de l’incisive centrale mandibulaire la plus antérieure.',
    },
    {
        id: 'L1A', name: 'Apex incisive inférieure', abbr: 'II apex', group: 'dental',
        definition: 'Apex radiculaire de l’incisive centrale mandibulaire la plus antérieure.',
    },
    {
        id: 'U6O', name: 'Molaire supérieure — cuspide', abbr: 'M6 sup', group: 'dental',
        definition: 'Pointe de la cuspide mésio-vestibulaire de la première molaire permanente maxillaire.',
    },
    {
        id: 'L6O', name: 'Molaire inférieure — cuspide', abbr: 'M6 inf', group: 'dental',
        definition: 'Pointe de la cuspide mésio-vestibulaire de la première molaire permanente mandibulaire.',
    },
    {
        id: 'U6D', name: 'Molaire supérieure — face distale', abbr: 'M6 dist', group: 'dental',
        definition: 'Point le plus distal de la couronne de la première molaire permanente maxillaire.',
    },
    {
        id: 'PmCusp', name: 'Cuspide prémolaire', abbr: 'PmC', group: 'dental',
        definition: 'Point de recouvrement cuspidien des premières prémolaires ; sert, avec les cuspides molaires, à construire le plan d’occlusion fonctionnel.',
    },

    // ---------- Tissus mous ----------
    {
        id: 'G_', name: 'Glabelle cutanée', abbr: "G'", group: 'soft-tissue',
        definition: 'Point le plus proéminent du front, dans le plan sagittal médian.',
    },
    {
        id: 'N_', name: 'Nasion cutané', abbr: "N'", group: 'soft-tissue',
        definition: 'Point le plus profond de la concavité cutanée à la racine du nez.',
    },
    {
        id: 'Prn', name: 'Pronasale (pointe du nez)', abbr: 'Prn', group: 'soft-tissue',
        definition: 'Point le plus proéminent de la pointe du nez.',
    },
    {
        id: 'Cm', name: 'Columelle', abbr: 'Cm', group: 'soft-tissue',
        definition: 'Point le plus antérieur de la columelle du nez.',
    },
    {
        id: 'Sn', name: 'Sous-nasal', abbr: 'Sn', group: 'soft-tissue',
        definition: 'Point de jonction de la columelle et de la lèvre supérieure, dans le plan sagittal médian.',
    },
    {
        id: 'A_', name: 'Point A cutané', abbr: "A'", group: 'soft-tissue',
        definition: 'Point le plus profond de la concavité de la lèvre supérieure, entre le sous-nasal et le labrale superius.',
    },
    {
        id: 'Ls', name: 'Labrale superius', abbr: 'Ls', group: 'soft-tissue',
        definition: 'Point le plus antérieur du bord vermillon de la lèvre supérieure.',
    },
    {
        id: 'Stms', name: 'Stomion superius', abbr: 'Stms', group: 'soft-tissue',
        definition: 'Point le plus inférieur de la lèvre supérieure.',
    },
    {
        id: 'Stmi', name: 'Stomion inferius', abbr: 'Stmi', group: 'soft-tissue',
        definition: 'Point le plus supérieur de la lèvre inférieure.',
    },
    {
        id: 'Li', name: 'Labrale inferius', abbr: 'Li', group: 'soft-tissue',
        definition: 'Point le plus antérieur du bord vermillon de la lèvre inférieure.',
    },
    {
        id: 'B_', name: 'Point B cutané', abbr: "B'", group: 'soft-tissue',
        definition: 'Point le plus profond de la concavité de la lèvre inférieure, entre le labrale inferius et le pogonion cutané.',
    },
    {
        id: 'Pog_', name: 'Pogonion cutané', abbr: "Pog'", group: 'soft-tissue',
        definition: 'Point le plus antérieur du menton cutané.',
    },
    {
        id: 'Gn_', name: 'Gnathion cutané', abbr: "Gn'", group: 'soft-tissue',
        definition: 'Point le plus antéro-inférieur du menton cutané.',
    },
    {
        id: 'Me_', name: 'Menton cutané', abbr: "Me'", group: 'soft-tissue',
        definition: 'Point le plus inférieur du menton cutané.',
    },
    {
        id: 'C', name: 'Point cervical', abbr: 'C', group: 'soft-tissue',
        definition: 'Point le plus profond de la concavité entre la région sous-mentale et le cou.',
    },
];

export const LANDMARK_BY_ID = Object.fromEntries(LANDMARKS.map((l) => [l.id, l]));

const CANONICAL_ORDER = Object.fromEntries(LANDMARKS.map((l, i) => [l.id, i]));

/**
 * Trie des identifiants de points dans l'ordre où il faut les digitaliser :
 * base du crâne d'abord, puis maxillaire, mandibule, denture et enfin tissus
 * mous. C'est l'ordre du tracé manuel : on part des repères squelettiques
 * stables et on progresse vers l'extérieur.
 */
export function orderLandmarks(ids) {
    return [...ids]
        .filter((id) => id in CANONICAL_ORDER)
        .sort((a, b) => CANONICAL_ORDER[a] - CANONICAL_ORDER[b]);
}

export const GROUP_COLOR = Object.fromEntries(LANDMARK_GROUPS.map((g) => [g.id, g.color]));
export const GROUP_LABEL = Object.fromEntries(LANDMARK_GROUPS.map((g) => [g.id, g.label]));
