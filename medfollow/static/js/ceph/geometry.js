/**
 * Primitives géométriques de la céphalométrie.
 *
 * Les coordonnées image ont l'axe y vers le BAS ; les conventions cliniques
 * supposent l'axe y vers le HAUT. Tous les vecteurs construits ici inversent y.
 * L'orientation du patient (profil regardant à gauche ou à droite) n'est jamais
 * supposée : elle est déduite de l'anatomie elle-même (voir buildFrame).
 */

export const DEG = 180 / Math.PI;

/** Vecteur de a vers b, dans l'espace y-haut. */
export function vec(a, b) {
    return { x: b.x - a.x, y: -(b.y - a.y) };
}

export function norm(v) {
    return Math.hypot(v.x, v.y);
}

export function unit(v) {
    const n = norm(v);
    return n === 0 ? { x: 0, y: 0 } : { x: v.x / n, y: v.y / n };
}

export function dot(u, v) {
    return u.x * v.x + u.y * v.y;
}

/** Produit vectoriel 2D (composante z). Positif = v tourne dans le sens anti-horaire depuis u. */
export function cross(u, v) {
    return u.x * v.y - u.y * v.x;
}

/** Distance euclidienne, en pixels. */
export function dist(a, b) {
    return Math.hypot(b.x - a.x, b.y - a.y);
}

/** Angle non signé au sommet `vertex`, sous-tendu par a et b : 0..180°. */
export function angleAt(vertex, a, b) {
    return angleOfVectors(vec(vertex, a), vec(vertex, b));
}

/**
 * Angle non signé entre deux directions (espace y-haut), 0..180°.
 *
 * C'est la brique de tous les angles céphalométriques nommés. Nommer les deux
 * demi-droites anatomiquement (ex. « plan mandibulaire vers l'arrière » contre
 * « axe de l'incisive inférieure vers la couronne ») lève l'ambiguïté entre les
 * deux angles supplémentaires d'un croisement de droites. Choisir entre `a` et
 * `180 − a` selon la proximité de la norme serait faux : la norme de l'IMPA vaut
 * 90°, et les deux candidats en sont toujours équidistants.
 */
export function angleOfVectors(u, v) {
    const a = unit(u);
    const b = unit(v);
    const c = Math.min(1, Math.max(-1, dot(a, b)));
    return Math.acos(c) * DEG;
}

/**
 * Angle signé de la droite l1 vers la droite l2, −180..180 (espace y-haut).
 * Positif = la direction de l2 est anti-horaire par rapport à celle de l1.
 */
export function signedAngleBetween(l1, l2) {
    const u = vec(l1.a, l1.b);
    const v = vec(l2.a, l2.b);
    return Math.atan2(cross(u, v), dot(u, v)) * DEG;
}

/** Plus petit angle entre deux droites (entités non orientées) : 0..90°. */
export function acuteAngleBetween(l1, l2) {
    const a = Math.abs(signedAngleBetween(l1, l2));
    return a > 90 ? 180 - a : a;
}

/**
 * Angle entre deux droites ramené dans l'intervalle 0..180° attendu par le
 * clinicien ; le supplément est choisi pour rester proche de `expect` si fourni.
 */
export function angleBetween(l1, l2, expect) {
    const a = Math.abs(signedAngleBetween(l1, l2));
    if (expect === undefined) return a;
    const alt = 180 - a;
    return Math.abs(a - expect) <= Math.abs(alt - expect) ? a : alt;
}

/**
 * Inclinaison du vecteur `v` par rapport au vecteur `base`, signée de sorte que
 * « positif » signifie toujours « l'extrémité de v est relevée », quel que soit
 * le sens du profil.
 */
export function signedTilt(base, v, facing) {
    return Math.atan2(cross(base, v), dot(base, v)) * DEG * facing;
}

/** Pied de la perpendiculaire abaissée de p sur la droite (infinie) l. */
export function projectOnLine(p, l) {
    const dx = l.b.x - l.a.x;
    const dy = l.b.y - l.a.y;
    const len2 = dx * dx + dy * dy;
    if (len2 === 0) return { ...l.a };
    const t = ((p.x - l.a.x) * dx + (p.y - l.a.y) * dy) / len2;
    return { x: l.a.x + t * dx, y: l.a.y + t * dy };
}

/** Distance perpendiculaire de p à la droite l. Toujours ≥ 0. */
export function distToLine(p, l) {
    return dist(p, projectOnLine(p, l));
}

/**
 * Distance perpendiculaire de p à la droite l, signée par `positive` : le
 * résultat est positif quand p se trouve du côté vers lequel pointe `positive`
 * (vecteur y-haut, typiquement l'axe antérieur du repère facial).
 */
export function signedDistToLine(p, l, positive) {
    const foot = projectOnLine(p, l);
    const d = vec(foot, p);
    return dot(d, unit(positive));
}

/** Intersection de deux droites infinies, ou null si elles sont parallèles. */
export function intersect(l1, l2) {
    const x1 = l1.a.x, y1 = l1.a.y, x2 = l1.b.x, y2 = l1.b.y;
    const x3 = l2.a.x, y3 = l2.a.y, x4 = l2.b.x, y4 = l2.b.y;
    const den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
    if (Math.abs(den) < 1e-9) return null;
    const t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den;
    return { x: x1 + t * (x2 - x1), y: y1 + t * (y2 - y1) };
}

export function midpoint(a, b) {
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/** Droite passant par p, perpendiculaire à l (coordonnées image). */
export function perpendicularThrough(p, l) {
    const dx = l.b.x - l.a.x;
    const dy = l.b.y - l.a.y;
    return { a: p, b: { x: p.x - dy, y: p.y + dx } };
}

/**
 * Repère facial déduit de l'anatomie. Permet d'exprimer toute mesure signée en
 * « antérieur = positif » / « inférieur = positif » sans se soucier du sens du
 * profil sur le cliché.
 *
 * anterior : vecteur unitaire vers la face (y-haut)
 * inferior : vecteur unitaire vers le menton (y-haut)
 * facing   : +1 si le patient regarde à droite sur l'image, −1 s'il regarde à gauche
 */
export function buildFrame(pts) {
    // Nasion est antérieur à Sella : leur écart en x révèle le sens du profil.
    let facing = 1;
    if (pts.S && pts.N && Math.abs(pts.N.x - pts.S.x) > 1e-6) {
        facing = pts.N.x > pts.S.x ? 1 : -1;
    } else if (pts.Or && pts.Po && Math.abs(pts.Or.x - pts.Po.x) > 1e-6) {
        facing = pts.Or.x > pts.Po.x ? 1 : -1;
    }
    return {
        anterior: { x: facing, y: 0 },
        inferior: { x: 0, y: -1 }, // espace y-haut : l'inférieur est en y négatif
        facing,
    };
}
