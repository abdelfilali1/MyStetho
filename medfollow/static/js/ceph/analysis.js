/**
 * Moteur d'analyse céphalométrique.
 *
 * Une mesure est une fonction pure des points digitalisés et d'un facteur
 * d'échelle. Chaque mesure déclare les points qu'elle exige : l'interface peut
 * donc afficher ce qui manque au lieu de produire silencieusement un chiffre faux.
 *
 * Trois règles structurent ce fichier :
 *
 * 1. Les conventions de signe sont anatomiques, jamais liées à l'image.
 *    « Antérieur = positif » vient du repère facial : une téléradio d'un patient
 *    regardant à gauche donne exactement les mêmes valeurs (signes compris)
 *    qu'une téléradio du même patient regardant à droite.
 *
 * 2. Une mesure est la GRANDEUR MESURÉE ; sa norme appartient à l'analyse qui la
 *    cite. L'angle plan de Francfort / plan mandibulaire est un seul angle, mais
 *    Downs le norme à 21,9°, Tweed à 25° et Ricketts à 26°. Les analyses portent
 *    donc des normes de substitution, au lieu de dupliquer la géométrie.
 *
 * 3. Les angles sont invariants d'échelle, les millimètres non. Toute valeur en
 *    mm est RETENUE tant que l'image n'est pas calibrée, plutôt qu'exprimée en
 *    pixels.
 */

import {
    acuteAngleBetween, angleAt, angleBetween, angleOfVectors, buildFrame, dist, dot,
    midpoint, perpendicularThrough, projectOnLine, signedDistToLine, signedTilt, vec,
} from './geometry.js';

/** Âge de référence quand l'âge du patient est inconnu. */
const ADULT = 21;

const ageOf = (s) => (s.age === null || s.age === undefined ? ADULT : s.age);
const isFemale = (s) => s.sex === 'female';

/** Contexte d'évaluation transmis à chaque `compute`. */
export class Ctx {
    constructor(pts, mmPerPx, frame, subject) {
        this.pts = pts;
        this.mmPerPx = mmPerPx;   // millimètres par pixel de l'image NATURELLE ; null si non calibré
        this.frame = frame;
        this.subject = subject;
    }

    /** Point par identifiant. Toujours présent : le moteur vérifie `requires` d'abord. */
    p(id) {
        const v = this.pts[id];
        if (!v) throw new Error(`point manquant : ${id}`);
        return v;
    }

    has(id) {
        return !!this.pts[id];
    }

    /** Distance en pixels convertie en millimètres. Lève une erreur si non calibré. */
    mm(px) {
        if (this.mmPerPx === null || this.mmPerPx === undefined) throw new Error('non calibré');
        return px * this.mmPerPx;
    }

    line(a, b) {
        return { a: this.p(a), b: this.p(b) };
    }

    /** Distance entre deux points, en mm. */
    d(a, b) {
        return this.mm(dist(this.p(a), this.p(b)));
    }

    /** Distance perpendiculaire signée à une droite, antérieur = positif, en mm. */
    antDist(p, l) {
        const pt = typeof p === 'string' ? this.p(p) : p;
        return this.mm(signedDistToLine(pt, l, this.frame.anterior));
    }

    /** Distance perpendiculaire signée à une droite, inférieur = positif, en mm. */
    infDist(p, l) {
        const pt = typeof p === 'string' ? this.p(p) : p;
        return this.mm(signedDistToLine(pt, l, this.frame.inferior));
    }

    // ---- Plans de référence construits ----

    get SN() { return this.line('S', 'N'); }                 // base du crâne antérieure
    get FH() { return this.line('Po', 'Or'); }               // plan de Francfort
    get MP() { return this.line('Go', 'Me'); }               // plan mandibulaire (Downs / Tweed / Jarabak)
    get GoGn() { return this.line('Go', 'Gn'); }             // plan mandibulaire de Steiner
    get PP() { return this.line('ANS', 'PNS'); }             // plan palatin
    get facialPlane() { return this.line('N', 'Pog'); }      // plan facial
    get APog() { return this.line('A', 'Pog'); }
    get NA() { return this.line('N', 'A'); }
    get NB() { return this.line('N', 'B'); }
    get Eline() { return this.line('Prn', 'Pog_'); }         // plan esthétique de Ricketts
    get Hline() { return { a: this.p('Pog_'), b: this.p('Ls') }; }  // ligne d'harmonie de Holdaway
    get softFacial() { return this.line('N_', 'Pog_'); }     // plan facial cutané
    get U1() { return this.line('U1A', 'U1T'); }             // grand axe de l'incisive supérieure
    get L1() { return this.line('L1A', 'L1T'); }             // grand axe de l'incisive inférieure

    /**
     * Plan d'occlusion FONCTIONNEL : par le recouvrement cuspidien prémolaire et
     * le recouvrement cuspidien molaire, en excluant délibérément les incisives.
     * C'est le plan sur lequel le Wits est défini ; utiliser le plan bissecteur à
     * la place décale le Wits de plusieurs millimètres. Repli sur le plan
     * bissecteur uniquement si le point prémolaire n'a pas été digitalisé.
     */
    get occlusalPlane() {
        const molar = midpoint(this.p('U6O'), this.p('L6O'));
        if (this.has('PmCusp')) return { a: this.p('PmCusp'), b: molar };
        const incisal = midpoint(this.p('U1T'), this.p('L1T'));
        return { a: incisal, b: molar };
    }

    /** Vrai si le plan d'occlusion est retombé sur la définition bissectrice (incisives). */
    get occlusalIsBisected() {
        return !this.has('PmCusp');
    }

    /** Perpendiculaire de Nasion : verticale par N, normale au plan de Francfort. */
    get nasionPerp() {
        return perpendicularThrough(this.p('N'), this.FH);
    }

    /** Verticale ptérygoïdienne : par Pt, normale au plan de Francfort. */
    get PTV() {
        return perpendicularThrough(this.p('Pt'), this.FH);
    }

    // ---- Demi-droites anatomiques orientées ----
    //
    // Un angle nommé est l'angle entre deux DEMI-DROITES, pas entre deux droites.
    // Construire chaque demi-droite à partir de l'anatomie (au lieu de choisir
    // l'angle supplémentaire le plus proche de la norme) rend l'IMPA, l'axe
    // facial et la profondeur maxillaire — tous normés autour de 90° — non ambigus.

    /** Direction (y-haut) du point `a` vers le point `b`. */
    dir(a, b) {
        return vec(this.p(a), this.p(b));
    }

    get fhPost() { return this.dir('Or', 'Po'); }   // Francfort vers l'arrière
    get fhAnt() { return this.dir('Po', 'Or'); }    // Francfort vers l'avant
    get mpAnt() { return this.dir('Go', 'Me'); }    // plan mandibulaire vers l'avant
    get mpPost() { return this.dir('Me', 'Go'); }   // plan mandibulaire vers l'arrière
    get u1Crown() { return this.dir('U1A', 'U1T'); } // axe incisive sup., vers la couronne
    get u1Root() { return this.dir('U1T', 'U1A'); }  // axe incisive sup., vers l'apex
    get l1Crown() { return this.dir('L1A', 'L1T'); } // axe incisive inf., vers la couronne
    get l1Root() { return this.dir('L1T', 'L1A'); }  // axe incisive inf., vers l'apex

    /** Direction du plan d'occlusion, orientée vers l'avant. */
    get opAnt() {
        const op = this.occlusalPlane;
        const u = vec(op.a, op.b);
        return dot(u, this.frame.anterior) >= 0 ? u : { x: -u.x, y: -u.y };
    }
}

// ---------------------------------------------------------------------------
// Mesures
// ---------------------------------------------------------------------------

const M = (m) => m;
const N = (mean, sd, low, high) => () => ({ mean, sd, low, high });

const SKELETAL_AP = {
    below: 'Tendance squelettique de Classe III',
    normal: 'Classe I squelettique',
    above: 'Tendance squelettique de Classe II',
};
const VERTICAL = {
    below: 'Hypodivergent — schéma de croissance horizontale',
    normal: 'Normodivergent',
    above: 'Hyperdivergent — schéma de croissance verticale',
};

export const MEASUREMENTS = [
    // ------------------------------------------------ Squelettique sagittal
    M({
        id: 'SNA', name: 'SNA', unit: 'deg', requires: ['S', 'N', 'A'],
        description: 'Position antéro-postérieure du maxillaire par rapport à la base du crâne antérieure.',
        norm: N(82, 2),
        compute: (c) => angleAt(c.p('N'), c.p('S'), c.p('A')),
        interpretation: {
            below: 'Maxillaire rétrusif par rapport à la base du crâne',
            normal: 'Maxillaire orthognathe',
            above: 'Maxillaire protrusif par rapport à la base du crâne',
        },
    }),
    M({
        id: 'SNB', name: 'SNB', unit: 'deg', requires: ['S', 'N', 'B'],
        description: 'Position antéro-postérieure de la mandibule par rapport à la base du crâne antérieure.',
        norm: N(80, 2),
        compute: (c) => angleAt(c.p('N'), c.p('S'), c.p('B')),
        interpretation: {
            below: 'Mandibule rétrusive par rapport à la base du crâne',
            normal: 'Mandibule orthognathe',
            above: 'Mandibule protrusive par rapport à la base du crâne',
        },
    }),
    M({
        id: 'ANB', name: 'ANB', unit: 'deg', requires: ['S', 'N', 'A', 'B'],
        description: 'Relation sagittale maxillo-mandibulaire. Calculé comme SNA − SNB : le signe en découle automatiquement.',
        norm: N(2, 2, 0, 4),
        compute: (c) => angleAt(c.p('N'), c.p('S'), c.p('A')) - angleAt(c.p('N'), c.p('S'), c.p('B')),
        interpretation: SKELETAL_AP,
        caveat: 'L’ANB est faussé par un Nasion atypique ou une base du crâne pivotée. À lire avec le Wits et l’angle Bêta.',
    }),
    M({
        id: 'SND', name: 'SND', unit: 'deg', requires: ['S', 'N', 'D'],
        description: 'Position mandibulaire évaluée au point D (centre de la symphyse), insensible au remodelage alvéolaire.',
        norm: N(76, 2),
        compute: (c) => angleAt(c.p('N'), c.p('S'), c.p('D')),
    }),
    M({
        id: 'wits', name: 'Wits (AO-BO)', unit: 'mm',
        requires: ['A', 'B', 'U6O', 'L6O', 'U1T', 'L1T'], optional: ['PmCusp'],
        description: 'Projections de A et B sur le plan d’occlusion fonctionnel. Positif quand AO est en avant de BO. Indépendant de la base du crâne.',
        // Jacobson 1975 : BO se situe ~1 mm en avant de AO chez l'homme, et les
        // deux coïncident chez la femme. Avec la convention « AO antérieur =
        // positif », la moyenne masculine est donc négative. Plusieurs sources
        // modernes publient +1 mm à la place.
        norm: (s) => (isFemale(s) ? { mean: 0, sd: 1.77 } : { mean: -1, sd: 1.9 }),
        compute: (c) => {
            // Le Wits se ramène à la projection de B→A sur la direction du plan
            // d'occlusion orientée vers l'avant ; le point de référence s'annule.
            const u = c.opAnt;
            const ab = vec(c.p('B'), c.p('A'));
            return c.mm(dot(ab, u) / Math.hypot(u.x, u.y));
        },
        interpretation: SKELETAL_AP,
        caveat: 'Aussi fiable que le plan d’occlusion l’est. Un plan d’occlusion pentu ou en denture mixte décale nettement le Wits.',
    }),
    M({
        id: 'beta_angle', name: 'Angle Bêta', unit: 'deg', requires: ['Co', 'A', 'B'],
        description: 'Angle entre A–B et la perpendiculaire abaissée de A sur la droite condylion–B. Indépendant de la base du crâne ET du plan d’occlusion.',
        norm: N(31, 4, 27, 35),
        compute: (c) => {
            const foot = projectOnLine(c.p('A'), c.line('Co', 'B'));
            return angleAt(c.p('A'), foot, c.p('B'));
        },
        interpretation: {
            below: 'Tendance squelettique de Classe II',
            normal: 'Classe I squelettique',
            above: 'Tendance squelettique de Classe III',
        },
    }),
    M({
        id: 'convexity_angle', name: 'Angle de convexité (N-A-Pog)', unit: 'deg',
        requires: ['N', 'A', 'Pog'],
        description: 'Convexité du profil. Positif quand le point A est en avant du plan facial (profil convexe).',
        norm: N(0, 5.1, -8.5, 10),
        compute: (c) => {
            const mag = 180 - angleAt(c.p('A'), c.p('N'), c.p('Pog'));
            const side = signedDistToLine(c.p('A'), c.facialPlane, c.frame.anterior);
            return Math.sign(side || 1) * mag;
        },
        interpretation: { below: 'Profil concave', normal: 'Profil droit', above: 'Profil convexe' },
    }),
    M({
        id: 'ricketts_convexity', name: 'Convexité (A au plan N-Pog)', unit: 'mm',
        requires: ['N', 'A', 'Pog'],
        description: 'Convexité linéaire du profil : avancée du point A par rapport au plan facial.',
        // Ricketts : 2 mm à 9 ans, diminuant d'environ 0,2 mm/an → ≈ 0 chez l'adulte.
        norm: (s) => ({ mean: Math.max(0, 2 - 0.2 * (ageOf(s) - 9)), sd: 2 }),
        compute: (c) => c.antDist('A', c.facialPlane),
        interpretation: {
            below: 'Profil squelettique concave (Classe III)',
            normal: 'Profil squelettique droit',
            above: 'Profil squelettique convexe (Classe II)',
        },
    }),
    M({
        id: 'ab_plane', name: 'Angle du plan A-B', unit: 'deg', requires: ['N', 'A', 'B', 'Pog'],
        description: 'Angle de la droite A-B au plan facial. Négatif quand A est en avant de B — le cas normal.',
        norm: N(-4.6, 4.6, -9, 0),
        compute: (c) => {
            const mag = angleBetween(c.facialPlane, c.line('A', 'B'), 5);
            const aAheadOfB = dot(vec(c.p('B'), c.p('A')), c.frame.anterior) > 0;
            return aAheadOfB ? -mag : mag;
        },
        interpretation: {
            below: 'Décalage squelettique de Classe II accentué',
            normal: 'Rapport des bases apicales normal',
            above: 'Tendance squelettique de Classe III',
        },
    }),
    M({
        id: 'facial_angle', name: 'Angle facial / profondeur faciale (FH à N-Pog)', unit: 'deg',
        requires: ['Po', 'Or', 'N', 'Pog'],
        description: 'Protrusion ou rétrusion mandibulaire par rapport au plan de Francfort.',
        norm: N(87.8, 3.6, 82, 95),
        // Angle postéro-inférieur de Downs : Francfort vers l'arrière, contre N→Pog.
        // Un menton plus prognathe fait pivoter N→Pog vers l'avant et augmente l'angle.
        compute: (c) => angleOfVectors(c.fhPost, c.dir('N', 'Pog')),
        interpretation: {
            below: 'Mandibule rétrognathe (profil squelettique de Classe II)',
            normal: 'Profil orthognathe',
            above: 'Mandibule prognathe (profil squelettique de Classe III)',
        },
    }),
    M({
        id: 'maxillary_depth', name: 'Profondeur maxillaire (FH à N-A)', unit: 'deg',
        requires: ['Po', 'Or', 'N', 'A'],
        description: 'Position horizontale du maxillaire par rapport au plan de Francfort.',
        norm: N(90, 3),
        compute: (c) => angleOfVectors(c.fhPost, c.dir('N', 'A')),
    }),
    M({
        id: 'A_nperp', name: 'A à la perpendiculaire de Nasion', unit: 'mm',
        requires: ['Po', 'Or', 'N', 'A'],
        description: 'Position du maxillaire par rapport à la vraie verticale passant par Nasion.',
        norm: N(0.5, 2, 0, 1),
        compute: (c) => c.antDist('A', c.nasionPerp),
        interpretation: {
            below: 'Rétrusion maxillaire',
            normal: 'Maxillaire bien positionné',
            above: 'Protrusion maxillaire',
        },
    }),
    M({
        id: 'Pog_nperp', name: 'Pog à la perpendiculaire de Nasion', unit: 'mm',
        requires: ['Po', 'Or', 'N', 'Pog'],
        description: 'Position du menton par rapport à la vraie verticale passant par Nasion.',
        norm: (s) => (isFemale(s)
            ? { mean: -3, sd: 2, low: -4, high: -2 }
            : { mean: -2, sd: 2, low: -4, high: 0 }),
        compute: (c) => c.antDist('Pog', c.nasionPerp),
        interpretation: {
            below: 'Rétrusion mandibulaire',
            normal: 'Mandibule bien positionnée',
            above: 'Protrusion mandibulaire',
        },
    }),

    // -------------------------------------------------- Vertical / croissance
    M({
        id: 'FMA', name: 'Angle du plan mandibulaire (FH à Go-Me)', unit: 'deg',
        requires: ['Po', 'Or', 'Go', 'Me'],
        description: 'Angle Francfort–plan mandibulaire, indicateur vertical majeur. Downs le norme à 21,9°, Tweed à 25°, Ricketts à 26° : c’est l’analyse affichée qui fixe la norme.',
        norm: N(25, 5, 16, 35),
        // Angle intérieur du triangle de Tweed au croisement FH/MP : les deux
        // demi-droites pointent vers l'avant. FMA + FMIA + IMPA = 180° en découle.
        compute: (c) => angleOfVectors(c.fhAnt, c.mpAnt),
        interpretation: VERTICAL,
    }),
    M({
        id: 'SN_GoGn', name: 'SN à Go-Gn', unit: 'deg', requires: ['S', 'N', 'Go', 'Gn'],
        description: 'Angle du plan mandibulaire de Steiner : schéma vertical rapporté à la base du crâne.',
        norm: N(32, 4),
        compute: (c) => acuteAngleBetween(c.SN, c.GoGn),
        interpretation: VERTICAL,
    }),
    M({
        id: 'y_axis', name: 'Axe Y (axe de croissance)', unit: 'deg',
        requires: ['Po', 'Or', 'S', 'Gn'],
        description: 'Angle de la droite S-Gn au plan de Francfort : direction de la croissance faciale.',
        norm: N(59.4, 3.8, 53, 66),
        // Angle antéro-inférieur de Downs : Francfort vers l'avant, contre S→Gn.
        compute: (c) => angleOfVectors(c.fhAnt, c.dir('S', 'Gn')),
        interpretation: {
            below: 'Direction de croissance horizontale',
            normal: 'Direction de croissance équilibrée',
            above: 'Direction de croissance verticale',
        },
    }),
    M({
        id: 'facial_axis', name: 'Axe facial (Ba-N à Pt-Gn)', unit: 'deg',
        requires: ['Ba', 'N', 'Pt', 'Gn'],
        description: 'Direction de croissance du menton. L’écart à 90° signe le schéma de croissance ; il ne varie pas avec l’âge.',
        norm: N(90, 3.5),
        // Angle postéro-inférieur de Ricketts : N→Ba contre Pt→Gn. Un menton qui
        // descend et recule rapproche Pt→Gn de N→Ba : l'angle passe sous 90°.
        compute: (c) => angleOfVectors(c.dir('N', 'Ba'), c.dir('Pt', 'Gn')),
        interpretation: {
            below: 'Schéma de croissance verticale (dolichofacial)',
            normal: 'Schéma mésofacial',
            above: 'Schéma de croissance horizontale (brachyfacial)',
        },
    }),
    M({
        id: 'PP_FH', name: 'Plan palatin au Francfort', unit: 'deg',
        requires: ['Po', 'Or', 'ANS', 'PNS'],
        description: 'Bascule du maxillaire par rapport au plan de Francfort. Positif quand le maxillaire antérieur est basculé vers le haut.',
        norm: N(1, 3.5),
        compute: (c) => signedTilt(c.fhAnt, c.dir('PNS', 'ANS'), c.frame.facing),
        interpretation: {
            below: 'Maxillaire antérieur basculé vers le bas (rotation horaire)',
            normal: 'Plan palatin dans les normes',
            above: 'Maxillaire antérieur basculé vers le haut (rotation anti-horaire)',
        },
    }),
    M({
        id: 'lower_face_height', name: 'Hauteur faciale inférieure (ENA-Xi-Pm)', unit: 'deg',
        requires: ['ANS', 'Xi', 'Pm'],
        description: 'Hauteur faciale inférieure angulaire, indépendante de la base du crâne.',
        norm: N(47, 4),
        compute: (c) => angleAt(c.p('Xi'), c.p('ANS'), c.p('Pm')),
        interpretation: VERTICAL,
    }),
    M({
        id: 'mandibular_arc', name: 'Arc mandibulaire (Dc-Xi-Pm)', unit: 'deg',
        requires: ['Dc', 'Xi', 'Pm'],
        description: 'Forme de la mandibule. Les valeurs élevées accompagnent une mandibule carrée, à croissance antérieure.',
        norm: (s) => ({ mean: 26 + 0.5 * (ageOf(s) - 9), sd: 4 }),
        compute: (c) => angleAt(c.p('Xi'), c.p('Dc'), c.p('Pm')),
    }),

    // ------------------------------------------------------- Björk / Jarabak
    M({
        id: 'saddle_angle', name: 'Angle sellaire (N-S-Ar)', unit: 'deg', requires: ['N', 'S', 'Ar'],
        description: 'Flexion de la base du crâne. Un angle plus ouvert déplace la fosse glénoïde vers l’arrière.',
        norm: N(123, 5),
        compute: (c) => angleAt(c.p('S'), c.p('N'), c.p('Ar')),
        interpretation: {
            below: 'Fosse en position antérieure — favorise le prognathisme mandibulaire',
            normal: 'Flexion de la base du crâne normale',
            above: 'Fosse en position postérieure — favorise le rétrognathisme mandibulaire',
        },
    }),
    M({
        id: 'articular_angle', name: 'Angle articulaire (S-Ar-Go)', unit: 'deg',
        requires: ['S', 'Ar', 'Go'],
        description: 'Angle à l’articulare. Il diminue avec le prognathisme mandibulaire.',
        norm: N(143, 6),
        compute: (c) => angleAt(c.p('Ar'), c.p('S'), c.p('Go')),
    }),
    M({
        id: 'gonial_angle', name: 'Angle goniaque (Ar-Go-Me)', unit: 'deg',
        requires: ['Ar', 'Go', 'Me'],
        description: 'Forme mandibulaire. Les valeurs élevées accompagnent une croissance verticale et une tendance à la béance.',
        norm: N(130, 7),
        compute: (c) => angleAt(c.p('Go'), c.p('Ar'), c.p('Me')),
        interpretation: VERTICAL,
    }),
    M({
        id: 'gonial_upper', name: 'Angle goniaque supérieur (Ar-Go-N)', unit: 'deg',
        requires: ['Ar', 'Go', 'N'],
        description: 'Division supérieure de l’angle goniaque ; liée à la direction du ramus.',
        norm: N(53.5, 2, 52, 55),
        compute: (c) => angleAt(c.p('Go'), c.p('Ar'), c.p('N')),
    }),
    M({
        id: 'gonial_lower', name: 'Angle goniaque inférieur (N-Go-Me)', unit: 'deg',
        requires: ['N', 'Go', 'Me'],
        description: 'Division inférieure de l’angle goniaque ; bon prédicteur de la direction de croissance.',
        norm: N(72.5, 3, 70, 75),
        compute: (c) => angleAt(c.p('Go'), c.p('N'), c.p('Me')),
        interpretation: VERTICAL,
    }),
    M({
        id: 'bjork_sum', name: 'Somme de Björk', unit: 'deg', requires: ['N', 'S', 'Ar', 'Go', 'Me'],
        description: 'Sellaire + articulaire + goniaque. Sous 396°, la mandibule tourne vers l’avant (tendance supraclusie) ; au-dessus, vers l’arrière (tendance béance).',
        norm: N(396, 6, 390, 402),
        compute: (c) =>
            angleAt(c.p('S'), c.p('N'), c.p('Ar')) +
            angleAt(c.p('Ar'), c.p('S'), c.p('Go')) +
            angleAt(c.p('Go'), c.p('Ar'), c.p('Me')),
        interpretation: {
            below: 'Rotation mandibulaire antérieure (anti-horaire) — croissance horizontale',
            normal: 'Rotation neutre',
            above: 'Rotation mandibulaire postérieure (horaire) — croissance verticale',
        },
    }),
    M({
        id: 'ant_cranial_base', name: 'Base du crâne antérieure (S-N)', unit: 'mm', requires: ['S', 'N'],
        description: 'Longueur de la base du crâne antérieure.',
        norm: N(71, 3),
        compute: (c) => c.d('S', 'N'),
    }),
    M({
        id: 'post_cranial_base', name: 'Base du crâne postérieure (S-Ar)', unit: 'mm', requires: ['S', 'Ar'],
        description: 'Longueur de la base du crâne postérieure.',
        norm: N(32, 3),
        compute: (c) => c.d('S', 'Ar'),
    }),
    M({
        id: 'ramus_height', name: 'Hauteur du ramus (Ar-Go)', unit: 'mm', requires: ['Ar', 'Go'],
        description: 'Hauteur du ramus mandibulaire.',
        norm: N(44, 5),
        compute: (c) => c.d('Ar', 'Go'),
    }),
    M({
        id: 'mand_body', name: 'Longueur du corps mandibulaire (Go-Me)', unit: 'mm', requires: ['Go', 'Me'],
        description: 'Longueur du corps de la mandibule.',
        norm: N(71, 5),
        compute: (c) => c.d('Go', 'Me'),
    }),
    M({
        id: 'post_face_height', name: 'Hauteur faciale postérieure (S-Go)', unit: 'mm', requires: ['S', 'Go'],
        description: 'Dimension verticale faciale postérieure.',
        norm: N(77.5, 7.5, 70, 85),
        compute: (c) => c.d('S', 'Go'),
    }),
    M({
        id: 'ant_face_height', name: 'Hauteur faciale antérieure (N-Me)', unit: 'mm', requires: ['N', 'Me'],
        description: 'Dimension verticale faciale antérieure totale.',
        norm: N(112.5, 7.5, 105, 120),
        compute: (c) => c.d('N', 'Me'),
    }),
    M({
        id: 'jarabak_ratio', name: 'Rapport de Jarabak (S-Go : N-Me)', unit: '%',
        requires: ['S', 'Go', 'N', 'Me'],
        description: 'Hauteur faciale postérieure sur antérieure. Sous 62 % : croissance verticale ; au-dessus de 65 % : croissance horizontale.',
        norm: N(63.5, 1.5, 62, 65),
        compute: (c) => (c.d('S', 'Go') / c.d('N', 'Me')) * 100,
        interpretation: {
            below: 'Schéma de croissance horaire (verticale)',
            normal: 'Croissance verticale équilibrée',
            above: 'Schéma de croissance anti-horaire (horizontale)',
        },
    }),
    M({
        id: 'LAFH', name: 'Hauteur faciale antéro-inférieure (ENA-Me)', unit: 'mm',
        requires: ['ANS', 'Me'],
        description: 'Dimension verticale de l’étage inférieur ; à lire avec la différence maxillo-mandibulaire.',
        norm: (s) => (isFemale(s)
            ? { mean: 61, sd: 4, low: 60, high: 70 }
            : { mean: 68.6, sd: 5, low: 65, high: 75 }),
        compute: (c) => c.d('ANS', 'Me'),
    }),

    // ------------------------------------------------------------- McNamara
    M({
        id: 'midface_len', name: 'Longueur maxillaire effective (Co-A)', unit: 'mm', requires: ['Co', 'A'],
        description: 'Longueur effective du maxillaire.',
        norm: (s) => (isFemale(s)
            ? { mean: 91, sd: 4, low: 91, high: 96 }
            : { mean: 99.8, sd: 4, low: 95, high: 100 }),
        compute: (c) => c.d('Co', 'A'),
    }),
    M({
        id: 'mand_len', name: 'Longueur mandibulaire effective (Co-Gn)', unit: 'mm', requires: ['Co', 'Gn'],
        description: 'Longueur effective de la mandibule.',
        norm: (s) => (isFemale(s)
            ? { mean: 120, sd: 5, low: 118, high: 128 }
            : { mean: 134.3, sd: 5, low: 125, high: 135 }),
        compute: (c) => c.d('Co', 'Gn'),
    }),
    M({
        id: 'maxmand_diff', name: 'Différence maxillo-mandibulaire', unit: 'mm',
        requires: ['Co', 'A', 'Gn'],
        description: 'Co-Gn moins Co-A. McNamara lit l’harmonie des mâchoires sur cette différence plutôt que sur un angle ; à interpréter avec la hauteur faciale antéro-inférieure.',
        norm: (s) => (isFemale(s) ? { mean: 29.5, sd: 4 } : { mean: 34.5, sd: 4 }),
        compute: (c) => c.d('Co', 'Gn') - c.d('Co', 'A'),
    }),
    M({
        id: 'U1_Avert', name: 'IS à la verticale de A', unit: 'mm',
        requires: ['Po', 'Or', 'A', 'U1T'],
        description: 'Bord libre de l’incisive supérieure par rapport à la verticale passant par le point A.',
        norm: N(5, 2, 4, 6),
        compute: (c) => c.antDist('U1T', perpendicularThrough(c.p('A'), c.FH)),
    }),

    // --------------------------------------------------------------- Dentaire
    M({
        id: 'U1_NA_ang', name: 'IS à NA (angle)', unit: 'deg', requires: ['N', 'A', 'U1A', 'U1T'],
        description: 'Inclinaison de l’incisive centrale maxillaire par rapport à la ligne NA.',
        norm: N(22, 5),
        // Les deux demi-droites descendent : N→A contre l'axe incisif vers la couronne.
        compute: (c) => angleOfVectors(c.dir('N', 'A'), c.u1Crown),
        interpretation: {
            below: 'Incisives supérieures rétro-inclinées',
            normal: 'Inclinaison des incisives supérieures normale',
            above: 'Incisives supérieures vestibulo-versées',
        },
    }),
    M({
        id: 'U1_NA_mm', name: 'IS à NA (distance)', unit: 'mm', requires: ['N', 'A', 'U1T'],
        description: 'Avancée du bord libre de l’incisive maxillaire par rapport à la ligne NA.',
        norm: N(4, 2),
        compute: (c) => c.antDist('U1T', c.NA),
        interpretation: {
            below: 'Incisives supérieures rétruses',
            normal: 'Position des incisives supérieures normale',
            above: 'Incisives supérieures protruses',
        },
    }),
    M({
        id: 'L1_NB_ang', name: 'II à NB (angle)', unit: 'deg', requires: ['N', 'B', 'L1A', 'L1T'],
        description: 'Inclinaison de l’incisive centrale mandibulaire par rapport à la ligne NB.',
        norm: N(25, 5),
        // Les deux demi-droites descendent : N→B contre l'axe incisif vers l'apex.
        compute: (c) => angleOfVectors(c.dir('N', 'B'), c.l1Root),
        interpretation: {
            below: 'Incisives inférieures rétro-inclinées',
            normal: 'Inclinaison des incisives inférieures normale',
            above: 'Incisives inférieures vestibulo-versées',
        },
    }),
    M({
        id: 'L1_NB_mm', name: 'II à NB (distance)', unit: 'mm', requires: ['N', 'B', 'L1T'],
        description: 'Avancée du bord libre de l’incisive mandibulaire par rapport à la ligne NB.',
        norm: N(4, 2),
        compute: (c) => c.antDist('L1T', c.NB),
        interpretation: {
            below: 'Incisives inférieures rétruses',
            normal: 'Position des incisives inférieures normale',
            above: 'Incisives inférieures protruses',
        },
    }),
    M({
        id: 'Pog_NB', name: 'Pog à NB', unit: 'mm', requires: ['N', 'B', 'Pog'],
        description: 'Proéminence du menton osseux en avant de NB. Comparée à II-NB dans le rapport de Holdaway.',
        norm: N(2.5, 1.5, 1, 4),
        compute: (c) => c.antDist('Pog', c.NB),
    }),
    M({
        id: 'holdaway_ratio', name: 'Rapport de Holdaway (II-NB : Pog-NB)', unit: 'ratio',
        requires: ['N', 'B', 'Pog', 'L1T'],
        description: 'Équilibre entre protrusion de l’incisive inférieure et proéminence du menton. Idéalement 1:1.',
        norm: N(1, 0.35),
        compute: (c) => {
            const pog = c.antDist('Pog', c.NB);
            const l1 = c.antDist('L1T', c.NB);
            // Un menton posé sur NB rend le rapport dénué de sens, et pas seulement grand.
            return Math.abs(pog) < 0.5 ? NaN : l1 / pog;
        },
        interpretation: {
            below: 'Incisives redressées par rapport au menton',
            normal: 'Équilibre incisives / menton acceptable',
            above: 'Incisives protrusives par rapport au menton',
        },
    }),
    M({
        id: 'interincisal', name: 'Angle inter-incisif', unit: 'deg',
        requires: ['U1A', 'U1T', 'L1A', 'L1T'],
        description: 'Angle entre les grands axes des incisives centrales supérieure et inférieure.',
        norm: N(131, 6),
        // Mesuré du côté lingual : les deux axes pris depuis les bords libres vers les apex.
        compute: (c) => angleOfVectors(c.u1Root, c.l1Root),
        interpretation: {
            below: 'Incisives vestibulo-versées / biproalvéolie',
            normal: 'Rapport inter-incisif normal',
            above: 'Incisives rétro-inclinées',
        },
    }),
    M({
        id: 'IMPA', name: 'IMPA (II au plan mandibulaire)', unit: 'deg',
        requires: ['Go', 'Me', 'L1A', 'L1T'],
        description: 'Angle incisive–plan mandibulaire : inclinaison axiale de l’incisive inférieure.',
        norm: N(90, 5, 85, 95),
        // Angle intérieur au croisement MP/II : plan mandibulaire vers l'arrière,
        // contre l'axe incisif vers la couronne.
        compute: (c) => angleOfVectors(c.mpPost, c.l1Crown),
        interpretation: {
            below: 'Incisives inférieures rétro-inclinées',
            normal: 'Inclinaison des incisives inférieures normale',
            above: 'Incisives inférieures vestibulo-versées',
        },
    }),
    M({
        id: 'FMIA', name: 'FMIA (FH à II)', unit: 'deg', requires: ['Po', 'Or', 'L1A', 'L1T'],
        description: 'Angle Francfort–incisive mandibulaire. Avec FMA et IMPA, il forme le triangle diagnostique de Tweed, dont la somme vaut 180°.',
        norm: N(65, 5, 60, 75),
        // Angle intérieur au croisement FH/II : Francfort vers l'arrière, contre
        // l'axe incisif vers l'apex.
        compute: (c) => angleOfVectors(c.fhPost, c.l1Root),
        interpretation: {
            below: 'Incisives inférieures vestibulo-versées ; profil probablement plein',
            normal: 'Équilibre incisives / profil favorable',
            above: 'Incisives inférieures redressées ; profil probablement plat',
        },
    }),
    M({
        id: 'U1_SN', name: 'IS à SN', unit: 'deg', requires: ['S', 'N', 'U1A', 'U1T'],
        description: 'Inclinaison de l’incisive supérieure par rapport à la base du crâne antérieure.',
        norm: N(102, 5),
        compute: (c) => angleOfVectors(c.dir('N', 'S'), c.u1Crown),
    }),
    M({
        id: 'U1_FH', name: 'IS au Francfort', unit: 'deg', requires: ['Po', 'Or', 'U1A', 'U1T'],
        description: 'Inclinaison de l’incisive supérieure par rapport au plan de Francfort.',
        norm: N(111, 6),
        compute: (c) => angleOfVectors(c.fhPost, c.u1Crown),
    }),
    M({
        id: 'U1_APog', name: 'IS à A-Pog', unit: 'mm', requires: ['A', 'Pog', 'U1T'],
        description: 'Bord libre de l’incisive supérieure par rapport à la ligne A-Pog.',
        norm: N(2.7, 1.8, -1, 5),
        compute: (c) => c.antDist('U1T', c.APog),
    }),
    M({
        id: 'L1_APog', name: 'II à A-Pog', unit: 'mm', requires: ['A', 'Pog', 'L1T'],
        description: 'Bord libre de l’incisive inférieure par rapport à la ligne A-Pog — limite clé lors de la planification de la position incisive.',
        norm: N(1, 2, 1, 3),
        compute: (c) => c.antDist('L1T', c.APog),
        interpretation: {
            below: 'Incisives inférieures rétruses par rapport à A-Pog',
            normal: 'Position des incisives inférieures acceptable',
            above: 'Incisives inférieures protruses par rapport à A-Pog',
        },
    }),
    M({
        id: 'L1_APog_ang', name: 'Inclinaison de II sur A-Pog', unit: 'deg',
        requires: ['A', 'Pog', 'L1A', 'L1T'],
        description: 'Inclinaison axiale de l’incisive inférieure par rapport à la ligne A-Pog.',
        norm: N(22, 4),
        compute: (c) => angleOfVectors(c.dir('A', 'Pog'), c.l1Root),
    }),
    M({
        id: 'OP_SN', name: 'Plan d’occlusion à SN', unit: 'deg',
        requires: ['S', 'N', 'U6O', 'L6O', 'U1T', 'L1T'], optional: ['PmCusp'],
        description: 'Bascule du plan d’occlusion par rapport à la base du crâne antérieure.',
        norm: N(14, 2),
        compute: (c) => acuteAngleBetween(c.SN, c.occlusalPlane),
    }),
    M({
        id: 'OP_FH', name: 'Bascule du plan d’occlusion (au FH)', unit: 'deg',
        requires: ['Po', 'Or', 'U6O', 'L6O', 'U1T', 'L1T'], optional: ['PmCusp'],
        description: 'Inclinaison du plan d’occlusion par rapport au plan de Francfort.',
        norm: N(9.3, 3.8, 1.5, 14),
        compute: (c) => acuteAngleBetween(c.FH, c.occlusalPlane),
    }),
    M({
        id: 'L1_OP', name: 'II au plan d’occlusion', unit: 'deg',
        requires: ['L1A', 'L1T', 'U6O', 'L6O', 'U1T'], optional: ['PmCusp'],
        description: 'Inclinaison de l’incisive inférieure sur le plan d’occlusion, exprimée comme l’écart à 90°.',
        norm: N(14.5, 3.5, 3.5, 20),
        compute: (c) => 90 - angleOfVectors(c.opAnt, c.l1Crown),
    }),
    M({
        id: 'U6_PTV', name: 'Molaire supérieure à la PTV', unit: 'mm',
        requires: ['Po', 'Or', 'Pt', 'U6D'],
        description: 'Face distale de la première molaire supérieure en avant de la verticale ptérygoïdienne. Ricketts attend (âge ÷ 2) + 3 mm.',
        norm: (s) => ({ mean: ageOf(s) / 2 + 3, sd: 3 }),
        compute: (c) => c.antDist('U6D', c.PTV),
    }),
    M({
        id: 'overjet', name: 'Surplomb (overjet)', unit: 'mm',
        requires: ['U1T', 'L1T', 'U6O', 'L6O'], optional: ['PmCusp'],
        description: 'Recouvrement incisif horizontal, mesuré parallèlement au plan d’occlusion.',
        norm: N(2.5, 1, 1, 4),
        compute: (c) => {
            const op = c.occlusalPlane;
            const u = projectOnLine(c.p('U1T'), op);
            const l = projectOnLine(c.p('L1T'), op);
            return c.mm(dot(vec(l, u), c.frame.anterior));
        },
        interpretation: {
            below: 'Surplomb réduit / occlusion inversée antérieure',
            normal: 'Surplomb normal',
            above: 'Surplomb augmenté',
        },
    }),
    M({
        id: 'overbite', name: 'Recouvrement (overbite)', unit: 'mm',
        requires: ['U1T', 'L1T', 'U6O', 'L6O'], optional: ['PmCusp'],
        description: 'Recouvrement incisif vertical, mesuré perpendiculairement au plan d’occlusion.',
        norm: N(2.5, 1, 1, 4),
        compute: (c) => {
            const op = c.occlusalPlane;
            const dU = signedDistToLine(c.p('U1T'), op, c.frame.inferior);
            const dL = signedDistToLine(c.p('L1T'), op, c.frame.inferior);
            return c.mm(dU - dL);
        },
        interpretation: { below: 'Béance antérieure', normal: 'Recouvrement normal', above: 'Supraclusie' },
    }),

    // ------------------------------------------------------------ Tissus mous
    M({
        id: 'upper_lip_E', name: 'Lèvre supérieure au plan E', unit: 'mm',
        requires: ['Prn', 'Pog_', 'Ls'],
        description: 'Lèvre supérieure par rapport au plan esthétique de Ricketts. Négatif = en arrière du plan.',
        norm: N(-4, 2),
        compute: (c) => c.antDist('Ls', c.Eline),
        interpretation: {
            below: 'Lèvre supérieure rétrusive',
            normal: 'Lèvre supérieure équilibrée',
            above: 'Lèvre supérieure protrusive',
        },
    }),
    M({
        id: 'lower_lip_E', name: 'Lèvre inférieure au plan E', unit: 'mm',
        requires: ['Prn', 'Pog_', 'Li'],
        description: 'Lèvre inférieure par rapport au plan esthétique de Ricketts. Négatif = en arrière du plan.',
        norm: N(-2, 2),
        compute: (c) => c.antDist('Li', c.Eline),
        interpretation: {
            below: 'Lèvre inférieure rétrusive',
            normal: 'Lèvre inférieure équilibrée',
            above: 'Lèvre inférieure protrusive',
        },
    }),
    M({
        id: 'nasolabial', name: 'Angle naso-labial', unit: 'deg', requires: ['Cm', 'Sn', 'Ls'],
        description: 'Angle entre la columelle et la lèvre supérieure — contrainte majeure sur l’ampleur possible de la rétraction des incisives supérieures.',
        norm: N(102, 8, 90, 110),
        compute: (c) => angleAt(c.p('Sn'), c.p('Cm'), c.p('Ls')),
        interpretation: {
            below: 'Aigu — lèvre supérieure procumbente ; rétraction généralement tolérée',
            normal: 'Angle naso-labial dans les normes',
            above: 'Obtus — éviter toute rétraction supplémentaire des incisives supérieures',
        },
    }),
    M({
        id: 'H_angle', name: 'Angle H de Holdaway', unit: 'deg', requires: ['N_', 'Pog_', 'Ls'],
        description: 'Angle entre la ligne H (Ls–Pog′) et le plan facial cutané (N′–Pog′). Certaines sources le mesurent sur la ligne osseuse NB.',
        norm: N(10, 2, 7, 15),
        // Les deux droites se coupent au pogonion cutané : c'est simplement l'angle en ce point.
        compute: (c) => angleAt(c.p('Pog_'), c.p('N_'), c.p('Ls')),
        interpretation: {
            below: 'Profil cutané plat',
            normal: 'Profil cutané équilibré',
            above: 'Profil cutané convexe / lèvre supérieure proéminente',
        },
    }),
    M({
        id: 'soft_facial_angle', name: 'Angle facial cutané (FH à N′-Pog′)', unit: 'deg',
        requires: ['Po', 'Or', 'N_', 'Pog_'],
        description: 'Équivalent cutané de l’angle facial.',
        norm: N(91, 7),
        compute: (c) => angleOfVectors(c.fhPost, c.dir('N_', 'Pog_')),
    }),
    M({
        id: 'Z_angle', name: 'Angle Z (Merrifield)', unit: 'deg',
        requires: ['Po', 'Or', 'Pog_', 'Ls', 'Li'],
        description: 'Angle entre le plan de Francfort et la ligne de profil — la tangente menée du pogonion cutané à la lèvre la plus saillante.',
        norm: N(80, 9, 75, 89),
        compute: (c) => {
            // La ligne de profil est la tangente du pogonion cutané à la lèvre la
            // plus antérieure. Des lèvres protrusives la font pivoter vers l'avant
            // et réduisent l'angle : c'est bien le sens attendu par la norme.
            const ls = c.p('Ls');
            const li = c.p('Li');
            const lip = dot(vec(li, ls), c.frame.anterior) > 0 ? ls : li;
            return angleOfVectors(c.fhAnt, vec(c.p('Pog_'), lip));
        },
        interpretation: {
            below: 'Lèvres protrusives / profil convexe',
            normal: 'Profil équilibré',
            above: 'Lèvres rétrusives / profil plat',
        },
    }),
    M({
        id: 'soft_convexity', name: 'Convexité cutanée (G′-Sn-Pog′)', unit: 'deg',
        requires: ['G_', 'Sn', 'Pog_'],
        description: 'Convexité faciale de Legan–Burstone, nez exclu.',
        norm: N(12, 4),
        compute: (c) => 180 - angleAt(c.p('Sn'), c.p('G_'), c.p('Pog_')),
        interpretation: {
            below: 'Profil cutané concave',
            normal: 'Profil cutané droit',
            above: 'Profil cutané convexe',
        },
    }),
    M({
        id: 'upper_lip_prot', name: 'Protrusion de la lèvre supérieure (Ls à Sn-Pog′)', unit: 'mm',
        requires: ['Ls', 'Sn', 'Pog_'],
        description: 'Protrusion de la lèvre supérieure selon Legan–Burstone.',
        norm: N(3, 1),
        compute: (c) => c.antDist('Ls', c.line('Sn', 'Pog_')),
    }),
    M({
        id: 'lower_lip_prot', name: 'Protrusion de la lèvre inférieure (Li à Sn-Pog′)', unit: 'mm',
        requires: ['Li', 'Sn', 'Pog_'],
        description: 'Protrusion de la lèvre inférieure selon Legan–Burstone.',
        norm: N(2, 1),
        compute: (c) => c.antDist('Li', c.line('Sn', 'Pog_')),
    }),
    M({
        id: 'sup_sulcus', name: 'Profondeur du sillon supérieur (à la ligne H)', unit: 'mm',
        requires: ['A_', 'Ls', 'Pog_'],
        description: 'Profondeur du sillon labial supérieur en arrière de la ligne H.',
        norm: N(3, 1, 1, 4),
        compute: (c) => -c.antDist('A_', c.Hline),
    }),
    M({
        id: 'lower_lip_H', name: 'Lèvre inférieure à la ligne H', unit: 'mm',
        requires: ['Li', 'Ls', 'Pog_'],
        description: 'Position de la lèvre inférieure par rapport à la ligne d’harmonie.',
        norm: N(0.5, 1.5, -1, 2),
        compute: (c) => c.antDist('Li', c.Hline),
    }),
    M({
        id: 'chin_thickness', name: 'Épaisseur du menton cutané (Pog-Pog′)', unit: 'mm',
        requires: ['Pog', 'Pog_'],
        description: 'Épaisseur des tissus mous recouvrant le menton osseux.',
        norm: N(11, 2, 8, 14),
        compute: (c) => c.d('Pog', 'Pog_'),
    }),
    M({
        id: 'lower_face_throat', name: 'Angle cervico-mentonnier (Sn-Gn′-C)', unit: 'deg',
        requires: ['Sn', 'Gn_', 'C'],
        description: 'Angle du cou selon Legan–Burstone ; un cou court ou obtus limite le bénéfice esthétique d’une avancée mentonnière.',
        norm: N(100, 7),
        compute: (c) => angleAt(c.p('Gn_'), c.p('Sn'), c.p('C')),
    }),
    M({
        id: 'upper_lip_len', name: 'Longueur de la lèvre supérieure (Sn-Stms)', unit: 'mm',
        requires: ['Sn', 'Stms'],
        description: 'Longueur verticale de la lèvre supérieure au repos.',
        norm: (s) => (isFemale(s) ? { mean: 20, sd: 2 } : { mean: 22, sd: 2 }),
        compute: (c) => c.d('Sn', 'Stms'),
    }),
    M({
        id: 'interlabial_gap', name: 'Inocclusion labiale', unit: 'mm', requires: ['Stms', 'Stmi'],
        description: 'Écart entre les lèvres au repos. Au-delà de 4 mm environ : incompétence labiale.',
        norm: N(2, 2, 0, 4),
        compute: (c) => c.d('Stms', 'Stmi'),
        interpretation: {
            below: 'Lèvres compétentes',
            normal: 'Lèvres compétentes',
            above: 'Incompétence labiale',
        },
    }),
    M({
        id: 'mentolabial', name: 'Profondeur du sillon labio-mentonnier', unit: 'mm',
        requires: ['Li', 'B_', 'Pog_'],
        description: 'Profondeur du pli labio-mentonnier en arrière de la ligne Li–Pog′.',
        norm: N(4, 2),
        compute: (c) => -c.antDist('B_', c.line('Li', 'Pog_')),
    }),
    M({
        id: 'S_line_upper', name: 'Lèvre supérieure à la ligne S', unit: 'mm',
        requires: ['Cm', 'Pog_', 'Ls'],
        description: 'La ligne S de Steiner joint le pogonion cutané au milieu de la columelle. Des lèvres équilibrées la touchent.',
        norm: N(0, 2),
        compute: (c) => c.antDist('Ls', c.line('Pog_', 'Cm')),
    }),
    M({
        id: 'S_line_lower', name: 'Lèvre inférieure à la ligne S', unit: 'mm',
        requires: ['Cm', 'Pog_', 'Li'],
        description: 'Lèvre inférieure par rapport à la ligne S de Steiner.',
        norm: N(0, 2),
        compute: (c) => c.antDist('Li', c.line('Pog_', 'Cm')),
    }),
];

export const MEASUREMENT_BY_ID = Object.fromEntries(MEASUREMENTS.map((m) => [m.id, m]));

// ---------------------------------------------------------------------------
// Analyses. Chacune cite les normes de son auteur quand elles diffèrent du défaut.
// ---------------------------------------------------------------------------

export const ANALYSES = [
    {
        id: 'steiner',
        name: 'Steiner',
        subtitle: 'Rapports squelettiques et dentaires référencés à la base du crâne',
        citation: 'Steiner CC, 1953',
        measurements: [
            'SNA', 'SNB', 'ANB', 'SND', 'SN_GoGn', 'U1_NA_ang', 'U1_NA_mm',
            'L1_NB_ang', 'L1_NB_mm', 'interincisal', 'Pog_NB', 'holdaway_ratio',
            'OP_SN', 'S_line_upper', 'S_line_lower',
        ],
        norms: {
            U1_NA_ang: N(22, 2),
            L1_NB_ang: N(25, 2),
            U1_NA_mm: N(4, 2),
            L1_NB_mm: N(4, 2),
            interincisal: N(131, 6),
        },
    },
    {
        id: 'downs',
        name: 'Downs',
        subtitle: 'Analyse squelettique et dentaire référencée au plan de Francfort',
        citation: 'Downs WB, 1948',
        measurements: [
            'facial_angle', 'convexity_angle', 'ab_plane', 'FMA', 'y_axis',
            'OP_FH', 'interincisal', 'L1_OP', 'IMPA', 'U1_APog',
        ],
        norms: {
            // Le plan mandibulaire et les normes incisives de Downs diffèrent de Tweed.
            FMA: N(21.9, 3.24, 17, 28),
            IMPA: N(91.4, 3.78, 81, 97),
            interincisal: N(135.4, 5.76, 130, 150.5),
        },
    },
    {
        id: 'tweed',
        name: 'Tweed',
        subtitle: 'Triangle diagnostique — FMA / FMIA / IMPA font 180°',
        citation: 'Tweed CH, 1954',
        measurements: ['FMA', 'FMIA', 'IMPA'],
        norms: {
            FMA: N(25, 5, 16, 35),
            IMPA: N(90, 5, 85, 95),
            FMIA: N(65, 5, 60, 75),
        },
    },
    {
        id: 'ricketts',
        name: 'Ricketts',
        subtitle: 'Analyse synthétique — normes ajustées à l’âge',
        citation: 'Ricketts RM, 1961',
        measurements: [
            'facial_axis', 'facial_angle', 'FMA', 'lower_face_height', 'mandibular_arc',
            'ricketts_convexity', 'L1_APog', 'L1_APog_ang', 'U1_FH', 'interincisal',
            'U6_PTV', 'lower_lip_E', 'maxillary_depth',
        ],
        norms: {
            // La profondeur faciale et l'angle du plan mandibulaire dérivent avec l'âge.
            facial_angle: (s) => ({ mean: 87 + 0.33 * (ageOf(s) - 9), sd: 3 }),
            FMA: (s) => ({ mean: 26 - 0.3 * (ageOf(s) - 9), sd: 4 }),
            interincisal: N(130, 10),
        },
    },
    {
        id: 'mcnamara',
        name: 'McNamara',
        subtitle: 'Analyse linéaire référencée à la perpendiculaire de Nasion',
        citation: 'McNamara JA, 1984',
        measurements: [
            'A_nperp', 'Pog_nperp', 'midface_len', 'mand_len', 'maxmand_diff',
            'LAFH', 'FMA', 'facial_axis', 'U1_Avert', 'L1_APog', 'nasolabial',
        ],
        norms: {
            FMA: N(22, 4),
            L1_APog: N(2, 1, 1, 3),
        },
    },
    {
        id: 'jarabak',
        name: 'Jarabak / Björk',
        subtitle: 'Polygone de croissance et hauteurs faciales',
        citation: 'Jarabak JR, 1972 · Björk A, 1969',
        measurements: [
            'saddle_angle', 'articular_angle', 'gonial_angle', 'gonial_upper',
            'gonial_lower', 'bjork_sum', 'ant_cranial_base', 'post_cranial_base',
            'ramus_height', 'mand_body', 'post_face_height', 'ant_face_height',
            'jarabak_ratio',
        ],
    },
    {
        id: 'wits',
        name: 'Wits',
        subtitle: 'Décalage des bases référencé au plan d’occlusion fonctionnel',
        citation: 'Jacobson A, 1975',
        measurements: ['wits', 'ANB', 'beta_angle', 'OP_FH'],
    },
    {
        id: 'soft-tissue',
        name: 'Tissus mous',
        subtitle: 'Plan E de Ricketts, Holdaway, Merrifield et Legan–Burstone',
        citation: 'Ricketts · Holdaway 1983 · Legan & Burstone 1980',
        measurements: [
            'upper_lip_E', 'lower_lip_E', 'nasolabial', 'H_angle', 'Z_angle',
            'soft_facial_angle', 'soft_convexity', 'upper_lip_prot', 'lower_lip_prot',
            'sup_sulcus', 'lower_lip_H', 'mentolabial', 'chin_thickness',
            'lower_face_throat', 'upper_lip_len', 'interlabial_gap',
        ],
    },
    {
        id: 'dental',
        name: 'Dentaire',
        subtitle: 'Position, inclinaison et recouvrement des incisives',
        measurements: [
            'overjet', 'overbite', 'U1_SN', 'U1_FH', 'U1_NA_ang', 'U1_NA_mm',
            'IMPA', 'L1_NB_ang', 'L1_NB_mm', 'interincisal', 'U1_APog', 'L1_APog', 'L1_OP',
        ],
    },
    {
        id: 'vertical',
        name: 'Vertical / croissance',
        subtitle: 'Divergence, hauteurs faciales et direction de croissance',
        measurements: [
            'FMA', 'SN_GoGn', 'gonial_angle', 'bjork_sum', 'y_axis', 'facial_axis',
            'lower_face_height', 'LAFH', 'ant_face_height', 'post_face_height',
            'jarabak_ratio', 'PP_FH',
        ],
    },
];

export const ANALYSIS_BY_ID = Object.fromEntries(ANALYSES.map((a) => [a.id, a]));

// ---------------------------------------------------------------------------
// Évaluation
// ---------------------------------------------------------------------------

function severityOf(z) {
    if (z === null || !isFinite(z)) return 'normal';
    const a = Math.abs(z);
    if (a <= 1) return 'normal';
    if (a <= 2) return 'mild';
    if (a <= 3) return 'moderate';
    return 'severe';
}

/**
 * Évalue les mesures `ids`. Renvoie, pour chacune : la valeur (ou null), la
 * norme retenue, l'écart en écarts-types, la sévérité, les points manquants et
 * l'interprétation en clair.
 */
export function evaluate(points, mmPerPx, subject, ids, analysisId) {
    const frame = buildFrame(points);
    const ctx = new Ctx(points, mmPerPx, frame, subject);
    const overrides = analysisId && ANALYSIS_BY_ID[analysisId] ? ANALYSIS_BY_ID[analysisId].norms : undefined;

    return ids.map((id) => {
        const def = MEASUREMENT_BY_ID[id];
        const normFn = (overrides && overrides[id]) || def.norm;
        const norm = normFn(subject);
        const missing = def.requires.filter((r) => !points[r]);
        const needsCalibration = (mmPerPx === null || mmPerPx === undefined) && def.unit === 'mm';

        const blank = (needsCal) => ({
            def, value: null, norm, z: null, severity: 'normal',
            missing, needsCalibration: needsCal, note: null,
        });

        if (missing.length) return blank(false);
        if (needsCalibration) return blank(true);

        let value;
        try {
            const v = def.compute(ctx);
            value = isFinite(v) ? v : null;
        } catch (e) {
            value = null;
        }

        const z = value === null || norm.sd === 0 ? null : (value - norm.mean) / norm.sd;
        const severity = severityOf(z);

        let note = null;
        if (value !== null && def.interpretation) {
            const lo = norm.low !== undefined ? norm.low : norm.mean - norm.sd;
            const hi = norm.high !== undefined ? norm.high : norm.mean + norm.sd;
            note = value < lo ? def.interpretation.below
                : value > hi ? def.interpretation.above
                    : def.interpretation.normal;
        }

        return { def, value, norm, z, severity, missing, needsCalibration: false, note };
    });
}

/** Tous les points exigés par une analyse (dans l'ordre de digitalisation). */
export function requiredLandmarks(analysisId) {
    const a = ANALYSIS_BY_ID[analysisId];
    if (!a) return [];
    const seen = new Set();
    for (const id of a.measurements) {
        const def = MEASUREMENT_BY_ID[id];
        if (!def) continue;
        for (const r of def.requires) seen.add(r);
        for (const o of def.optional || []) seen.add(o);
    }
    return [...seen];
}

/** Formate une valeur selon l'unité de la mesure (virgule décimale française). */
export function fmt(value, unit) {
    if (value === null || value === undefined || !isFinite(value)) return '—';
    const decimals = unit === 'ratio' ? 2 : 1;
    const s = value.toFixed(decimals).replace('.', ',');
    return unit === 'deg' ? `${s}°` : unit === 'mm' ? `${s} mm` : unit === '%' ? `${s} %` : s;
}

export function fmtNorm(norm, unit) {
    const suffix = unit === 'deg' ? '°' : unit === 'mm' ? ' mm' : unit === '%' ? ' %' : '';
    const d = unit === 'ratio' ? 2 : 1;
    const m = norm.mean.toFixed(d).replace('.', ',');
    const sd = norm.sd.toFixed(d).replace('.', ',');
    return `${m}${suffix} ± ${sd}`;
}
