/**
 * Calques dessinables : les plans de référence que le clinicien attend sur un
 * tracé, plus la synthèse diagnostique en langage clair.
 */

import { evaluate } from './analysis.js';
import { midpoint, perpendicularThrough } from './geometry.js';

export const PLANES = [
    { id: 'SN', label: 'S-N (base du crâne ant.)', from: ['S', 'N'], color: '#2563eb', extend: 0.15, group: 'skeletal' },
    { id: 'FH', label: 'Plan de Francfort', from: ['Po', 'Or'], color: '#0284c7', extend: 0.35, group: 'skeletal' },
    { id: 'BaN', label: 'Ba-N (base du crâne)', from: ['Ba', 'N'], color: '#4f46e5', extend: 0.1, dash: true, group: 'skeletal' },
    { id: 'PP', label: 'Plan palatin (ENA-ENP)', from: ['ANS', 'PNS'], color: '#059669', extend: 0.3, group: 'skeletal' },
    { id: 'MP', label: 'Plan mandibulaire (Go-Me)', from: ['Go', 'Me'], color: '#d97706', extend: 0.25, group: 'skeletal' },
    { id: 'GoGn', label: 'Go-Gn', from: ['Go', 'Gn'], color: '#b45309', dash: true, group: 'skeletal' },
    { id: 'facial', label: 'Plan facial (N-Pog)', from: ['N', 'Pog'], color: '#65a30d', extend: 0.12, group: 'skeletal' },
    { id: 'NA', label: 'N-A', from: ['N', 'A'], color: '#16a34a', extend: 0.6, dash: true, group: 'skeletal' },
    { id: 'NB', label: 'N-B', from: ['N', 'B'], color: '#0d9488', extend: 0.4, dash: true, group: 'skeletal' },
    { id: 'APog', label: 'A-Pog', from: ['A', 'Pog'], color: '#0891b2', extend: 0.25, dash: true, group: 'skeletal' },
    { id: 'Yaxis', label: 'Axe Y (S-Gn)', from: ['S', 'Gn'], color: '#7c3aed', dash: true, group: 'skeletal' },
    { id: 'ramus', label: 'Plan du ramus (Ar-Go)', from: ['Ar', 'Go'], color: '#ea580c', dash: true, group: 'skeletal' },
    { id: 'PtGn', label: 'Axe facial (Pt-Gn)', from: ['Pt', 'Gn'], color: '#c026d3', dash: true, group: 'skeletal' },

    {
        id: 'OP',
        label: 'Plan d’occlusion fonctionnel',
        from: null,
        build: (p) => {
            if (!p.U6O || !p.L6O) return null;
            const molar = midpoint(p.U6O, p.L6O);
            if (p.PmCusp) return [p.PmCusp, molar];
            if (!p.U1T || !p.L1T) return null;
            return [midpoint(p.U1T, p.L1T), molar];
        },
        color: '#db2777', extend: 0.4, group: 'dental',
    },
    { id: 'U1', label: 'Axe incisive supérieure', from: ['U1A', 'U1T'], color: '#e11d48', extend: 0.25, group: 'dental' },
    { id: 'L1', label: 'Axe incisive inférieure', from: ['L1A', 'L1T'], color: '#f43f5e', extend: 0.25, group: 'dental' },

    { id: 'Eline', label: 'Plan E (Prn-Pog′)', from: ['Prn', 'Pog_'], color: '#7c3aed', extend: 0.15, group: 'soft' },
    { id: 'Hline', label: 'Ligne H (Ls-Pog′)', from: ['Ls', 'Pog_'], color: '#9333ea', dash: true, group: 'soft' },
    { id: 'softFacial', label: 'Plan facial cutané (N′-Pog′)', from: ['N_', 'Pog_'], color: '#8b5cf6', dash: true, group: 'soft' },

    {
        id: 'Nperp',
        label: 'Perpendiculaire de Nasion',
        from: null,
        build: (p) => {
            if (!p.N || !p.Po || !p.Or) return null;
            const l = perpendicularThrough(p.N, { a: p.Po, b: p.Or });
            return [l.a, l.b];
        },
        color: '#475569', extend: 3, dash: true, group: 'constructed',
    },
    {
        id: 'PTV',
        label: 'Verticale ptérygoïdienne',
        from: null,
        build: (p) => {
            if (!p.Pt || !p.Po || !p.Or) return null;
            const l = perpendicularThrough(p.Pt, { a: p.Po, b: p.Or });
            return [l.a, l.b];
        },
        color: '#475569', extend: 3, dash: true, group: 'constructed',
    },
];

export const PLANE_GROUP_LABEL = {
    skeletal: 'Squelettiques',
    dental: 'Dentaires',
    soft: 'Tissus mous',
    constructed: 'Construits',
};

/** Résout tous les plans traçables à partir des points posés jusqu'ici. */
export function drawablePlanes(points) {
    const out = [];
    for (const def of PLANES) {
        let seg = null;
        if (def.from) {
            const [a, b] = def.from;
            if (points[a] && points[b]) seg = [points[a], points[b]];
        } else if (def.build) {
            seg = def.build(points);
        }
        if (!seg) continue;
        const [a, b] = seg;
        const e = def.extend || 0;
        const dx = (b.x - a.x) * e;
        const dy = (b.y - a.y) * e;
        out.push({
            ...def,
            a: { x: a.x - dx, y: a.y - dy },
            b: { x: b.x + dx, y: b.y + dy },
        });
    }
    return out;
}

/**
 * Structures anatomiques que le praticien peut tracer à main levée par-dessus la
 * radio. Ce sont celles d'un tracé manuel sur calque.
 */
export const TRACE_STRUCTURES = [
    { id: 'soft-profile', label: 'Profil cutané', color: '#7c3aed' },
    { id: 'cranial-base', label: 'Base du crâne', color: '#2563eb' },
    { id: 'orbit', label: 'Rebord orbitaire', color: '#0284c7' },
    { id: 'maxilla', label: 'Maxillaire', color: '#059669' },
    { id: 'mandible', label: 'Mandibule', color: '#d97706' },
    { id: 'symphysis', label: 'Symphyse', color: '#b45309' },
    { id: 'u1', label: 'Incisive supérieure', color: '#e11d48' },
    { id: 'l1', label: 'Incisive inférieure', color: '#f43f5e' },
    { id: 'u6', label: 'Molaire supérieure', color: '#db2777' },
    { id: 'l6', label: 'Molaire inférieure', color: '#ec4899' },
    { id: 'vertebrae', label: 'Vertèbres cervicales', color: '#475569' },
];

export const TRACE_COLOR = Object.fromEntries(TRACE_STRUCTURES.map((s) => [s.id, s.color]));

// ---------------------------------------------------------------------------
// Synthèse diagnostique
// ---------------------------------------------------------------------------

const band = (z) => {
    const a = Math.abs(z);
    return a <= 1 ? 'normal' : a <= 2 ? 'mild' : a <= 3 ? 'moderate' : 'severe';
};

const f1 = (v) => v.toFixed(1).replace('.', ',');
const f0 = (v) => v.toFixed(0);

/**
 * Transforme les chiffres bruts en phrases : classe squelettique, schéma
 * vertical, position des incisives, équilibre des tissus mous — ce que le
 * praticien écrit réellement dans le dossier.
 */
export function diagnosticSummary(points, mmPerPx, subject) {
    const ids = [
        'ANB', 'wits', 'beta_angle', 'SNA', 'SNB', 'FMA', 'SN_GoGn', 'jarabak_ratio',
        'bjork_sum', 'IMPA', 'U1_NA_ang', 'interincisal', 'upper_lip_E', 'lower_lip_E',
        'nasolabial', 'overjet', 'overbite',
    ];
    const r = Object.fromEntries(
        evaluate(points, mmPerPx, subject, ids).map((x) => [x.def.id, x]),
    );
    const out = [];

    // --- Squelettique sagittal ---
    const anb = r.ANB ? r.ANB.value : null;
    const wits = r.wits ? r.wits.value : null;
    if (anb !== null && anb !== undefined) {
        const cls = anb < 0 ? 'Classe III' : anb > 4 ? 'Classe II' : 'Classe I';
        const parts = [`ANB ${f1(anb)}°`];
        if (wits !== null && wits !== undefined) parts.push(`Wits ${f1(wits)} mm`);

        // Attribuer le décalage à la mâchoire réellement en cause.
        const sna = r.SNA;
        const snb = r.SNB;
        let cause = '';
        if (sna && sna.value != null && snb && snb.value != null) {
            const maxOff = Math.abs(sna.z || 0) > 1.5;
            const mandOff = Math.abs(snb.z || 0) > 1.5;
            if (maxOff && mandOff) cause = ' Les deux mâchoires s’écartent de la norme.';
            else if (maxOff) cause = ` Décalage porté par le maxillaire (SNA ${f1(sna.value)}°, ${sna.value > 82 ? 'protrusif' : 'rétrusif'}).`;
            else if (mandOff) cause = ` Décalage porté par la mandibule (SNB ${f1(snb.value)}°, ${snb.value > 80 ? 'protrusive' : 'rétrusive'}).`;
            else cause = ' Chaque mâchoire, prise isolément, reste dans les normes.';
        }
        out.push({
            label: 'Squelettique sagittal',
            finding: `${cls} squelettique`,
            detail: parts.join(', ') + '.' + cause,
            severity: band(r.ANB.z || 0),
        });

        if (wits != null && anb != null) {
            const anbCls = anb < 0 ? -1 : anb > 4 ? 1 : 0;
            const witsCls = wits < -2 ? -1 : wits > 3 ? 1 : 0;
            if (anbCls !== witsCls) {
                out.push({
                    label: 'Contrôle de cohérence',
                    finding: 'ANB et Wits divergent',
                    detail: 'La référence « base du crâne » et la référence « plan d’occlusion » ne donnent pas la même classe squelettique. Vérifiez Nasion et le plan d’occlusion : un plan d’occlusion pivoté ou une base du crâne atypique en est la cause habituelle.',
                    severity: 'mild',
                });
            }
        }
    }

    // --- Vertical ---
    const fma = r.FMA;
    const jr = r.jarabak_ratio;
    if (fma && fma.value != null) {
        const pattern = (fma.z || 0) > 1 ? 'Hyperdivergent (vertical)'
            : (fma.z || 0) < -1 ? 'Hypodivergent (horizontal)'
                : 'Normodivergent';
        const parts = [`FMA ${f1(fma.value)}°`];
        if (r.SN_GoGn && r.SN_GoGn.value != null) parts.push(`SN-GoGn ${f1(r.SN_GoGn.value)}°`);
        if (jr && jr.value != null) parts.push(`rapport de Jarabak ${f1(jr.value)} %`);
        if (r.bjork_sum && r.bjork_sum.value != null) parts.push(`somme de Björk ${f0(r.bjork_sum.value)}°`);
        out.push({
            label: 'Schéma vertical',
            finding: pattern,
            detail: parts.join(', ') + '.',
            severity: band(fma.z || 0),
        });
    }

    // --- Dentaire ---
    const impa = r.IMPA;
    if (impa && impa.value != null) {
        const state = (impa.z || 0) > 1 ? 'Incisives inférieures vestibulo-versées'
            : (impa.z || 0) < -1 ? 'Incisives inférieures rétro-inclinées'
                : 'Inclinaison des incisives inférieures normale';
        const parts = [`IMPA ${f1(impa.value)}°`];
        if (r.U1_NA_ang && r.U1_NA_ang.value != null) parts.push(`IS-NA ${f1(r.U1_NA_ang.value)}°`);
        if (r.interincisal && r.interincisal.value != null) parts.push(`inter-incisif ${f1(r.interincisal.value)}°`);
        out.push({
            label: 'Position des incisives',
            finding: state,
            detail: parts.join(', ') + '.',
            severity: band(impa.z || 0),
        });
    }

    const oj = r.overjet;
    const ob = r.overbite;
    if ((oj && oj.value != null) || (ob && ob.value != null)) {
        const bits = [];
        let sev = 'normal';
        if (oj && oj.value != null) {
            bits.push(`Surplomb ${f1(oj.value)} mm`);
            sev = band(oj.z || 0);
        }
        if (ob && ob.value != null) {
            bits.push(`recouvrement ${f1(ob.value)} mm${ob.value < 0 ? ' (béance)' : ''}`);
            if (band(ob.z || 0) !== 'normal') sev = band(ob.z || 0);
        }
        out.push({
            label: 'Rapport incisif',
            finding: bits.join(', '),
            detail: ob && ob.value != null && ob.value < 0
                ? 'Béance antérieure présente.'
                : ob && ob.value != null && (ob.z || 0) > 2
                    ? 'Supraclusie présente.'
                    : 'Dans les normes.',
            severity: sev,
        });
    }

    // --- Tissus mous ---
    const ll = r.lower_lip_E;
    if (ll && ll.value != null) {
        const state = (ll.z || 0) > 1 ? 'Lèvres protrusives'
            : (ll.z || 0) < -1 ? 'Lèvres rétrusives'
                : 'Position labiale équilibrée';
        const parts = [];
        if (r.upper_lip_E && r.upper_lip_E.value != null) parts.push(`lèvre supérieure à ${f1(r.upper_lip_E.value)} mm du plan E`);
        parts.push(`lèvre inférieure à ${f1(ll.value)} mm du plan E`);
        if (r.nasolabial && r.nasolabial.value != null) parts.push(`angle naso-labial ${f0(r.nasolabial.value)}°`);
        out.push({
            label: 'Tissus mous',
            finding: state,
            detail: parts.join(', ') + '.',
            severity: band(ll.z || 0),
        });
    }

    return out;
}
