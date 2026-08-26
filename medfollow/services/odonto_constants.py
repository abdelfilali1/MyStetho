"""Constantes de l'odontogramme (port de dentalpin `odontogram/constants.py`
et de la partie serveur de `odontogramConstants.ts`).

Numérotation FDI stricte : 11-48 permanentes, 51-85 temporaires.
"""
from __future__ import annotations

from typing import Any, Final

# --- Dents ------------------------------------------------------------------
PERMANENT_TEETH: Final[list[int]] = [
    18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28,
    38, 37, 36, 35, 34, 33, 32, 31, 41, 42, 43, 44, 45, 46, 47, 48,
]
DECIDUOUS_TEETH: Final[list[int]] = [
    55, 54, 53, 52, 51, 61, 62, 63, 64, 65,
    75, 74, 73, 72, 71, 81, 82, 83, 84, 85,
]
ALL_TEETH: Final[list[int]] = PERMANENT_TEETH + DECIDUOUS_TEETH

UPPER_ARCH_ORDER: Final[list[int]] = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
LOWER_ARCH_ORDER: Final[list[int]] = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]

SURFACES: Final[list[str]] = ["M", "D", "O", "V", "L"]

# --- État de la dent (ToothCondition) ---------------------------------------
TOOTH_CONDITIONS: Final[list[str]] = [
    "healthy", "caries", "filling", "crown", "missing", "root_canal",
    "implant", "extraction_indicated", "sealant", "fracture",
]

CONDITION_COLORS: Final[dict[str, str]] = {
    "healthy": "#FFFFFF",
    "caries": "#EF4444",
    "filling": "#3B82F6",
    "crown": "#F59E0B",
    "missing": "#9CA3AF",
    "root_canal": "#8B5CF6",
    "implant": "#10B981",
    "extraction_indicated": "#DC2626",
    "sealant": "#06B6D4",
    "fracture": "#BE185D",
}

# --- Traitements (TreatmentType) --------------------------------------------
TREATMENTS_BY_CATEGORY: Final[dict[str, list[str]]] = {
    "diagnostico": [
        "pulpitis", "caries", "incipient_caries", "pigmentation", "fracture", "missing",
        "periapical_small", "periapical_medium", "periapical_large", "rotated", "displaced", "unerupted",
    ],
    "restauradora": [
        "filling_composite", "filling_amalgam", "filling_temporary", "sealant", "veneer",
        "inlay", "overlay", "crown", "bridge", "splint",
    ],
    "cirugia": ["extraction", "implant", "apicoectomy"],
    "endodoncia": ["root_canal_full", "root_canal_two_thirds", "root_canal_half", "post", "root_canal_overfill"],
    "ortodoncia": ["bracket", "tube", "band", "attachment", "retainer"],
}

# Types acceptés en plus des catégories (couronnes sur implant : pas dans la barre).
_EXTRA_TYPES: Final[list[str]] = ["crown_on_implant", "provisional_crown_on_implant"]

TREATMENT_TYPES: Final[list[str]] = [
    t for cat in TREATMENTS_BY_CATEGORY.values() for t in cat
] + _EXTRA_TYPES

SURFACE_TREATMENTS: Final[set[str]] = {
    "caries", "incipient_caries", "pigmentation", "filling_composite", "filling_amalgam",
    "filling_temporary", "sealant", "veneer", "inlay",
}

ATOMIC_MULTI_TOOTH_TYPES: Final[set[str]] = {"bridge", "splint"}

SCOPES: Final[list[str]] = ["tooth", "multi_tooth", "global_mouth", "global_arch"]
STATUSES: Final[list[str]] = ["planned", "performed"]

# Libellés FR (repris de dentalpin fr.json, corrigés pour `post` et `periapical_*`).
TREATMENT_LABELS_FR: Final[dict[str, str]] = {
    "pulpitis": "Pulpite",
    "caries": "Carie",
    "incipient_caries": "Carie naissante",
    "pigmentation": "Pigmentation",
    "fracture": "Fracture",
    "missing": "Absente",
    "periapical_small": "Lésion périapicale <2 mm",
    "periapical_medium": "Lésion périapicale 2-4 mm",
    "periapical_large": "Lésion périapicale >4 mm",
    "rotated": "Tournée",
    "displaced": "Déplacée",
    "unerupted": "Non éruptée",
    "filling_composite": "Obturation en composite",
    "filling_amalgam": "Obturation en amalgame",
    "filling_temporary": "Obturation provisoire",
    "sealant": "Scellant",
    "veneer": "Facette",
    "inlay": "Inlay",
    "overlay": "Onlay",
    "crown": "Couronne",
    "crown_on_implant": "Couronne sur implant",
    "provisional_crown_on_implant": "Couronne provisoire sur implant",
    "bridge": "Bridge fixe",
    "splint": "Attelle",
    "extraction": "Extraction",
    "implant": "Implant",
    "apicoectomy": "Apicectomie",
    "root_canal_full": "Dépulpage complet",
    "root_canal_two_thirds": "Traitement canalaire 2/3",
    "root_canal_half": "Traitement canalaire 1/2",
    "post": "Tenon radiculaire",
    "root_canal_overfill": "Surcharge de traitement canalaire",
    "bracket": "Bracket",
    "tube": "Tube",
    "band": "Bague",
    "attachment": "Attachement",
    "retainer": "Contention",
}

# --- Passerelle avec les anciennes tables dental_* --------------------------
# condition legacy -> (general_condition, clinical_type)
LEGACY_TO_CLINICAL: Final[dict[str, tuple[str | None, str | None]]] = {
    "sain": (None, None),
    "carie": ("caries", "caries"),
    "obturation": ("filling", "filling_composite"),
    "obturation_amalgame": ("filling", "filling_amalgam"),
    "couronne": ("crown", "crown"),
    "couronne_provisoire": ("crown", "crown"),
    "extraction": ("missing", "missing"),
    "implant": ("implant", "implant"),
    "devitalise": ("root_canal", "root_canal_full"),
    "bridge": ("crown", "bridge"),
    "fracture": ("fracture", "fracture"),
}

LEGACY_SURFACE_MAP: Final[dict[str, str]] = {
    "mesial": "M", "distal": "D", "occlusal": "O", "vestibulaire": "V", "lingual": "L",
}

# Condition legacy dominante d'après les traitements réalisés (ordre = priorité).
CLINICAL_TO_LEGACY_PRIORITY: Final[list[tuple[set[str], str]]] = [
    ({"missing", "extraction"}, "extraction"),
    ({"implant"}, "implant"),
    ({"bridge"}, "bridge"),
    ({"crown", "crown_on_implant"}, "couronne"),
    ({"provisional_crown_on_implant"}, "couronne_provisoire"),
    ({"root_canal_full", "root_canal_two_thirds", "root_canal_half", "root_canal_overfill", "post"}, "devitalise"),
    ({"fracture"}, "fracture"),
    ({"filling_amalgam"}, "obturation_amalgame"),
    ({"filling_composite", "filling_temporary", "inlay", "overlay", "veneer", "sealant"}, "obturation"),
    ({"caries", "incipient_caries", "pulpitis", "periapical_small", "periapical_medium", "periapical_large"}, "carie"),
]

# Anciens `dental_treatments.treatment_type` (texte libre normalisé) -> clinical_type.
# Ordre important : le premier fragment trouvé gagne.
LEGACY_TREATMENT_TYPE_MAP: Final[list[tuple[str, str]]] = [
    ("traitement endodontique", "root_canal_full"),
    ("endodont", "root_canal_full"),
    ("devital", "root_canal_full"),
    ("extraction", "extraction"),
    ("implant", "implant"),
    ("couronne", "crown"),
    ("bridge", "bridge"),
    ("amalgame", "filling_amalgam"),
    ("composite", "filling_composite"),
    ("obturation", "filling_composite"),
    ("facette", "veneer"),
    ("scellement", "sealant"),
    ("inlay", "inlay"),
    ("onlay", "overlay"),
    ("apicectomie", "apicoectomy"),
]


# --- Catalogue d'actes (port du seed dentalpin `catalog/seed.py`, items mappés sur
# l'odontogramme). Un bouton par acte dans la barre de traitements ; `clinical_type`
# pilote le rendu, `label` l'affichage. Ordre = ordre du seed dentalpin.
CATALOG_CATEGORIES: Final[list[dict[str, str]]] = [
    {"key": "diagnostico", "label": "Diagnostic"},
    {"key": "restauradora", "label": "Restauration"},
    {"key": "cirugia", "label": "Chirurgie"},
    {"key": "endodoncia", "label": "Endodontie"},
    {"key": "ortodoncia", "label": "Orthodontie"},
    {"key": "preventivo", "label": "Préventif"},
    {"key": "periodoncia", "label": "Parodontie"},
    {"key": "pediatrica", "label": "Odontologie pédiatrique"},
]

ODONTO_CATALOG: Final[list[dict[str, Any]]] = [
    # Préventif
    {"code": "PREV-SEAL", "category": "preventivo", "label": "Scellement de sillons et fissures", "clinical_type": "sealant", "scope": "tooth", "requires_surfaces": True},
    # Restauration
    {"code": "REST-COMP", "category": "restauradora", "label": "Obturation composite", "clinical_type": "filling_composite", "scope": "tooth", "requires_surfaces": True},
    {"code": "REST-AMAL", "category": "restauradora", "label": "Obturation amalgame", "clinical_type": "filling_amalgam", "scope": "tooth", "requires_surfaces": True},
    {"code": "REST-TEMP", "category": "restauradora", "label": "Obturation temporaire", "clinical_type": "filling_temporary", "scope": "tooth", "requires_surfaces": True},
    {"code": "REST-INLAY-COMP", "category": "restauradora", "label": "Inlay composite", "clinical_type": "inlay", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-INLAY-CER", "category": "restauradora", "label": "Inlay céramique", "clinical_type": "inlay", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-OVER-COMP", "category": "restauradora", "label": "Overlay composite", "clinical_type": "overlay", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-OVER-CER", "category": "restauradora", "label": "Overlay céramique", "clinical_type": "overlay", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-VEN-COMP", "category": "restauradora", "label": "Facette composite", "clinical_type": "veneer", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-VEN-PORC", "category": "restauradora", "label": "Facette céramique", "clinical_type": "veneer", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-VEN-ZIR", "category": "restauradora", "label": "Facette zircone", "clinical_type": "veneer", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-CROWN-MC", "category": "restauradora", "label": "Couronne métal-céramique", "clinical_type": "crown", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-CROWN-ZIR", "category": "restauradora", "label": "Couronne zircone", "clinical_type": "crown", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-CROWN-DISI", "category": "restauradora", "label": "Couronne disilicate de lithium", "clinical_type": "crown", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-CROWN-METAL", "category": "restauradora", "label": "Couronne métallique", "clinical_type": "crown", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-CROWN-PROV", "category": "restauradora", "label": "Couronne provisoire", "clinical_type": "crown", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-CROWN-IMPL-MC", "category": "restauradora", "label": "Couronne sur implant métal-céramique", "clinical_type": "crown_on_implant", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-CROWN-IMPL-ZIR", "category": "restauradora", "label": "Couronne sur implant zircone", "clinical_type": "crown_on_implant", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-CROWN-IMPL-PROV", "category": "restauradora", "label": "Couronne provisoire sur implant", "clinical_type": "provisional_crown_on_implant", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-BRIDGE-MC", "category": "restauradora", "label": "Pont métal-céramique", "clinical_type": "bridge", "scope": "multi_tooth", "requires_surfaces": False},
    {"code": "REST-BRIDGE-ZIR", "category": "restauradora", "label": "Pont zircone", "clinical_type": "bridge", "scope": "multi_tooth", "requires_surfaces": False},
    {"code": "REST-BRIDGE-MARY", "category": "restauradora", "label": "Pont du Maryland", "clinical_type": "bridge", "scope": "multi_tooth", "requires_surfaces": False},
    {"code": "REST-SPLINT-OCC", "category": "restauradora", "label": "Gouttière d'occlusion", "clinical_type": "splint", "scope": "global_arch", "requires_surfaces": False},
    {"code": "REST-SPLINT-PERIO", "category": "restauradora", "label": "Gouttière de contention parodontale", "clinical_type": "splint", "scope": "multi_tooth", "requires_surfaces": False},
    {"code": "REST-RECONSTR", "category": "restauradora", "label": "Reconstruction extensive en composite", "clinical_type": "filling_composite", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-FILL-REPAIR", "category": "restauradora", "label": "Réparation d'obturation", "clinical_type": "filling_composite", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-CROWN-RECEMENT", "category": "restauradora", "label": "Recimentation de couronne", "clinical_type": "crown", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-CROWN-POST-ENDO", "category": "restauradora", "label": "Couronne sur dent dévitalisée", "clinical_type": "crown", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-HEAL-ABUT", "category": "restauradora", "label": "Pilier de cicatrisation", "clinical_type": "implant", "scope": "tooth", "requires_surfaces": False},
    {"code": "REST-DEF-ABUT", "category": "restauradora", "label": "Pilier définitif", "clinical_type": "implant", "scope": "tooth", "requires_surfaces": False},
    # Endodontie
    {"code": "ENDO-UNI", "category": "endodoncia", "label": "Endodontie uniradiculaire", "clinical_type": "root_canal_full", "scope": "tooth", "requires_surfaces": False},
    {"code": "ENDO-BI", "category": "endodoncia", "label": "Endodontie biradiculaire", "clinical_type": "root_canal_full", "scope": "tooth", "requires_surfaces": False},
    {"code": "ENDO-MULTI", "category": "endodoncia", "label": "Endodontie molaire", "clinical_type": "root_canal_full", "scope": "tooth", "requires_surfaces": False},
    {"code": "ENDO-RETREAT", "category": "endodoncia", "label": "Retraitement endodontique", "clinical_type": "root_canal_full", "scope": "tooth", "requires_surfaces": False},
    {"code": "ENDO-POST-FIBER", "category": "endodoncia", "label": "Pivot en fibre", "clinical_type": "post", "scope": "tooth", "requires_surfaces": False},
    {"code": "ENDO-POST-METAL", "category": "endodoncia", "label": "Pivot coulé", "clinical_type": "post", "scope": "tooth", "requires_surfaces": False},
    {"code": "ENDO-URGENT", "category": "endodoncia", "label": "Ouverture d'urgence de la chambre pulpaire", "clinical_type": "root_canal_half", "scope": "tooth", "requires_surfaces": False},
    {"code": "ENDO-MED-REFRESH", "category": "endodoncia", "label": "Renouvellement de médicament intraradiculaire", "clinical_type": "root_canal_two_thirds", "scope": "tooth", "requires_surfaces": False},
    {"code": "ENDO-APICOFORM", "category": "endodoncia", "label": "Apexification", "clinical_type": "root_canal_full", "scope": "tooth", "requires_surfaces": False},
    {"code": "ENDO-PED", "category": "endodoncia", "label": "Endodontie sur dent temporaire", "clinical_type": "root_canal_full", "scope": "tooth", "requires_surfaces": False},
    # Parodontie
    {"code": "PERIO-SPLINT-RAR", "category": "periodoncia", "label": "Gouttière de contention post-DDR", "clinical_type": "splint", "scope": "multi_tooth", "requires_surfaces": False},
    # Chirurgie
    {"code": "SURG-EXT-SIMPLE", "category": "cirugia", "label": "Extraction simple", "clinical_type": "extraction", "scope": "tooth", "requires_surfaces": False},
    {"code": "SURG-EXT-COMPLEX", "category": "cirugia", "label": "Extraction compliquée", "clinical_type": "extraction", "scope": "tooth", "requires_surfaces": False},
    {"code": "SURG-EXT-3MOLAR", "category": "cirugia", "label": "Extraction de la dent de sagesse", "clinical_type": "extraction", "scope": "tooth", "requires_surfaces": False},
    {"code": "SURG-EXT-OST", "category": "cirugia", "label": "Extraction chirurgicale avec ostéotomie", "clinical_type": "extraction", "scope": "tooth", "requires_surfaces": False},
    {"code": "SURG-IMP-TI", "category": "cirugia", "label": "Implant en titane", "clinical_type": "implant", "scope": "tooth", "requires_surfaces": False},
    {"code": "SURG-IMP-ZIR", "category": "cirugia", "label": "Implant en zircone", "clinical_type": "implant", "scope": "tooth", "requires_surfaces": False},
    {"code": "SURG-APEC", "category": "cirugia", "label": "Apicectomie", "clinical_type": "apicoectomy", "scope": "tooth", "requires_surfaces": False},
    {"code": "SURG-CYST", "category": "cirugia", "label": "Exérèse de kyste", "clinical_type": "apicoectomy", "scope": "tooth", "requires_surfaces": False},
    {"code": "SURG-EXT-INCLUIDO", "category": "cirugia", "label": "Extraction de dent incluse", "clinical_type": "extraction", "scope": "tooth", "requires_surfaces": False},
    # Orthodontie
    {"code": "ORTO-BRACK", "category": "ortodoncia", "label": "Bracket individuel (remplacement)", "clinical_type": "bracket", "scope": "tooth", "requires_surfaces": False},
    {"code": "ORTO-RET-FIX", "category": "ortodoncia", "label": "Contention fixe", "clinical_type": "retainer", "scope": "tooth", "requires_surfaces": False},
    {"code": "ORTO-ATTACH", "category": "ortodoncia", "label": "Attachements Invisalign", "clinical_type": "attachment", "scope": "tooth", "requires_surfaces": False},
    {"code": "ORTO-BRACK-CEMENT", "category": "ortodoncia", "label": "Collage de bracket", "clinical_type": "bracket", "scope": "tooth", "requires_surfaces": False},
    # Odontologie pédiatrique
    {"code": "PED-SEAL", "category": "pediatrica", "label": "Scellement de sillons pédiatrique", "clinical_type": "sealant", "scope": "tooth", "requires_surfaces": True},
    {"code": "PED-PULPOTOMY", "category": "pediatrica", "label": "Pulpotomie", "clinical_type": "root_canal_half", "scope": "tooth", "requires_surfaces": False},
    {"code": "PED-CROWN-SS", "category": "pediatrica", "label": "Couronne préformée pédiatrique", "clinical_type": "crown", "scope": "tooth", "requires_surfaces": False},
    {"code": "PED-EXT-TEMP", "category": "pediatrica", "label": "Extraction de dent temporaire", "clinical_type": "extraction", "scope": "tooth", "requires_surfaces": False},
    {"code": "PED-FILL-TEMP", "category": "pediatrica", "label": "Obturation sur dent temporaire", "clinical_type": "filling_composite", "scope": "tooth", "requires_surfaces": True},
    {"code": "PED-PULPECTOMY", "category": "pediatrica", "label": "Pulpectomie pédiatrique", "clinical_type": "root_canal_full", "scope": "tooth", "requires_surfaces": False},
]

# Descriptions cliniques (infobulle au survol des boutons de la barre de traitements).
TREATMENT_DESCRIPTIONS_FR: Final[dict[str, str]] = {
    "pulpitis": "Inflammation de la pulpe dentaire, réversible (douleur provoquée, brève) ou irréversible (douleur spontanée, prolongée, nocturne). Tests de vitalité exacerbés ; indique un coiffage ou un traitement endodontique.",
    "caries": "Lésion carieuse cavitaire : déminéralisation bactérienne de l'émail et de la dentine avec perte de substance (ICDAS 3 à 6). Localisée par face(s) atteinte(s) ; nécessite un curetage et une restauration.",
    "incipient_caries": "Carie initiale non cavitaire limitée à l'émail (tache blanche, ICDAS 1-2), sans perte de substance. Potentiellement reminéralisable par fluoration, hygiène et contrôle du risque carieux.",
    "pigmentation": "Coloration d'une face dentaire, extrinsèque (tabac, thé, chlorhexidine, chromogènes) ou intrinsèque (fluorose, tétracyclines), sans perte de substance.",
    "fracture": "Fracture coronaire et/ou radiculaire : fêlure amélaire, fracture amélo-dentinaire avec ou sans exposition pulpaire, fracture corono-radiculaire ou verticale (pronostic réservé).",
    "missing": "Dent absente de l'arcade : agénésie, avulsion antérieure ou perte spontanée. Édentement à prendre en compte dans le plan de réhabilitation prothétique ou implantaire.",
    "periapical_small": "Lésion périapicale radioclaire < 2 mm : parodontite apicale débutante (élargissement desmodontal, LIPOE) d'origine endodontique, généralement asymptomatique.",
    "periapical_medium": "Lésion périapicale de 2 à 4 mm : granulome apical d'origine endodontique (nécrose pulpaire). Indication de traitement ou de retraitement canalaire.",
    "periapical_large": "Lésion périapicale > 4 mm : granulome volumineux ou kyste radiculaire. Traitement endodontique, éventuellement chirurgie apicale ou énucléation.",
    "rotated": "Dent en rotation autour de son grand axe (giroversion) : malposition à documenter pour le diagnostic orthodontique et l'analyse occlusale.",
    "displaced": "Dent déplacée hors de l'alignement de l'arcade : vestibulo- ou linguo-position, égression, ingression ou migration secondaire à un édentement.",
    "unerupted": "Dent non éruptée : incluse, enclavée ou en retard d'éruption (à confirmer radiologiquement : panoramique ou CBCT).",
    "filling_composite": "Restauration directe en résine composite collée (mordançage, adhésif, stratification photopolymérisée) sur une ou plusieurs faces.",
    "filling_amalgam": "Restauration directe à l'amalgame d'argent, à rétention mécanique, sur les faces occlusales et proximales des dents postérieures.",
    "filling_temporary": "Obturation provisoire (CVI, oxyde de zinc-eugénol, IRM) en attente de la restauration définitive ou entre deux séances d'endodontie.",
    "sealant": "Scellement prophylactique des sillons et fissures par résine fluide ou ciment verre ionomère, sans préparation, pour prévenir la carie occlusale.",
    "veneer": "Facette : restauration partielle collée sur la face vestibulaire (céramique ou composite), à visée esthétique et fonctionnelle, après préparation minimale.",
    "inlay": "Inlay : restauration indirecte intra-coronaire (composite ou céramique) collée dans une cavité, sans recouvrement cuspidien.",
    "overlay": "Overlay / onlay : restauration indirecte partielle collée avec recouvrement d'une ou plusieurs cuspides fragilisées.",
    "crown": "Couronne périphérique : restauration prothétique recouvrant l'intégralité de la couronne clinique après préparation, scellée ou collée.",
    "crown_on_implant": "Couronne unitaire scellée ou transvissée sur un pilier implantaire, après ostéo-intégration de l'implant.",
    "provisional_crown_on_implant": "Couronne provisoire en résine sur implant, pour la mise en esthétique et le façonnage du profil d'émergence gingival.",
    "bridge": "Bridge (pont fixe) : prothèse plurale scellée ou collée sur des dents piliers, remplaçant une ou plusieurs dents absentes par des intermédiaires (pontiques).",
    "splint": "Contention / attelle : solidarisation de plusieurs dents (fil ou fibre collés, gouttière) pour stabiliser une mobilité ou une position.",
    "extraction": "Avulsion dentaire sous anesthésie locale : syndesmotomie, luxation et extraction, simple ou chirurgicale (lambeau, ostéotomie, odontosection).",
    "implant": "Implant endo-osseux (titane ou zircone) placé chirurgicalement dans l'os alvéolaire pour supporter une couronne, un bridge ou une prothèse amovible.",
    "apicoectomy": "Apicectomie : résection chirurgicale de l'apex radiculaire (≈ 3 mm) avec curetage de la lésion et obturation a retro (MTA), en cas d'échec du retraitement endodontique.",
    "root_canal_full": "Traitement endodontique complet : cathétérisme, mise en forme, désinfection (NaOCl) et obturation tridimensionnelle de la totalité du réseau canalaire à la longueur de travail.",
    "root_canal_two_thirds": "Obturation canalaire aux deux tiers de la longueur radiculaire : traitement incomplet ou court, à compléter ou à retraiter selon la clinique.",
    "root_canal_half": "Obturation ou parage canalaire atteignant la moitié de la longueur radiculaire (pulpotomie, traitement d'urgence, obturation très courte).",
    "post": "Tenon radiculaire (fibre de verre ou métallique) scellé ou collé dans le canal d'une dent dépulpée pour ancrer une reconstitution corono-radiculaire.",
    "root_canal_overfill": "Dépassement d'obturation canalaire : extrusion de gutta-percha ou de ciment au-delà de l'apex, à surveiller (douleur, lésion persistante, proximité nerveuse).",
    "bracket": "Bracket (attache) orthodontique collé sur la face vestibulaire ou linguale, recevant l'arc qui guide le déplacement dentaire.",
    "tube": "Tube orthodontique collé sur molaire, dans lequel s'engage l'extrémité distale de l'arc.",
    "band": "Bague orthodontique scellée autour d'une molaire, servant d'ancrage à l'appareil multi-attaches ou à un dispositif auxiliaire.",
    "attachment": "Taquet (attachement) en composite collé sur la dent pour améliorer la rétention et le contrôle des mouvements par aligneurs.",
    "retainer": "Contention orthodontique, fixe (fil collé) ou amovible, maintenant le résultat du traitement et prévenant la récidive.",
    "pontic": "Élément intermédiaire (pontique) d'un bridge, remplaçant une dent absente, solidaire des ancrages sur dents piliers.",
    "bridge_abutment": "Dent pilier d'un bridge, préparée pour recevoir l'ancrage (couronne d'ancrage ou ailette collée).",
}

CATALOG_DESCRIPTIONS_FR: Final[dict[str, str]] = {
    "PREV-SEAL": "Scellement prophylactique des sillons et fissures (résine fluide ou CVI) sur dents saines à risque carieux, sans préparation : isolation, mordançage, application et photopolymérisation.",
    "REST-COMP": "Restauration directe en composite : curetage carieux, mordançage, adhésif, stratification photopolymérisée puis réglage de l'occlusion et polissage.",
    "REST-AMAL": "Restauration à l'amalgame d'argent dans une cavité à rétention mécanique ; indiquée en secteur postérieur sous fortes contraintes occlusales.",
    "REST-TEMP": "Obturation provisoire (CVI, oxyde de zinc-eugénol) pour temporiser entre deux séances (endodontie) ou avant la restauration définitive.",
    "REST-INLAY-COMP": "Inlay en composite de laboratoire : pièce indirecte intra-coronaire collée, sans recouvrement cuspidien, pour cavité de moyenne étendue.",
    "REST-INLAY-CER": "Inlay en céramique (vitrocéramique, disilicate de lithium) collé dans une cavité intra-coronaire : haute résistance à l'usure et esthétique.",
    "REST-OVER-COMP": "Overlay en composite recouvrant une ou plusieurs cuspides fragilisées, collé par technique adhésive après préparation périphérique partielle.",
    "REST-OVER-CER": "Overlay en céramique avec recouvrement cuspidien : alternative conservatrice à la couronne sur dent postérieure délabrée ou dépulpée.",
    "REST-VEN-COMP": "Facette en composite (directe ou indirecte) sur la face vestibulaire : correction de teinte, de forme, de diastème ou de petite fracture.",
    "REST-VEN-PORC": "Facette céramique (feldspathique ou disilicate de lithium) collée après préparation vestibulaire a minima (0,3 à 0,7 mm).",
    "REST-VEN-ZIR": "Facette en zircone : indiquée lorsqu'une résistance mécanique accrue est nécessaire (bruxisme, dyschromie sévère à masquer).",
    "REST-CROWN-MC": "Couronne céramo-métallique : chape métallique (Co-Cr, Ni-Cr ou alliage précieux) recouverte de céramique cosmétique ; préparation périphérique de 1,2 à 1,5 mm avec épaulement.",
    "REST-CROWN-ZIR": "Couronne en zircone (oxyde de zirconium), monolithique ou stratifiée : sans métal, biocompatible, très haute résistance en flexion ; préparation à congé.",
    "REST-CROWN-DISI": "Couronne en disilicate de lithium (e.max) : vitrocéramique translucide collée, indiquée en secteur antérieur et prémolaire pour son esthétique.",
    "REST-CROWN-METAL": "Couronne coulée tout métal (alliage précieux ou Co-Cr) : préparation économe en tissu, indiquée en secteur molaire non visible.",
    "REST-CROWN-PROV": "Couronne provisoire en résine (PMMA ou bis-acryl) protégeant la dent préparée, maintenant l'espace et l'occlusion en attendant la prothèse d'usage.",
    "REST-CROWN-IMPL-MC": "Couronne céramo-métallique sur implant, scellée ou transvissée sur pilier, réalisée après ostéo-intégration et validation du profil d'émergence.",
    "REST-CROWN-IMPL-ZIR": "Couronne en zircone sur implant, transvissée sur embase titane ou scellée sur pilier : solution sans métal apparent, esthétique.",
    "REST-CROWN-IMPL-PROV": "Couronne provisoire en résine sur implant : mise en esthétique immédiate ou différée et modelage des tissus mous péri-implantaires.",
    "REST-BRIDGE-MC": "Bridge céramo-métallique : armature métallique coulée recouverte de céramique, scellée sur les dents piliers préparées ; pontique(s) remplaçant les dents absentes.",
    "REST-BRIDGE-ZIR": "Bridge en zircone (armature stratifiée ou monolithique) : prothèse plurale sans métal, haute résistance, scellée ou collée sur piliers.",
    "REST-BRIDGE-MARY": "Bridge collé type Maryland : ailette(s) métallique(s) ou céramique(s) collée(s) sur la face palatine/linguale des dents adjacentes, avec préparation minimale ; remplace le plus souvent une incisive.",
    "REST-SPLINT-OCC": "Gouttière occlusale de relaxation (type Michigan) en résine dure, portée la nuit : protège les dents du bruxisme et décharge les ATM et les muscles masticateurs.",
    "REST-SPLINT-PERIO": "Contention parodontale : solidarisation des dents mobiles par fil métallique ou fibre collée au composite sur les faces linguales/palatines.",
    "REST-RECONSTR": "Reconstitution étendue en composite d'une dent très délabrée (avec ou sans tenon fibré), restaurant le volume coronaire, souvent avant une couronne.",
    "REST-FILL-REPAIR": "Réparation d'une obturation existante fracturée, usée ou infiltrée, sans dépose complète, par sablage/mordançage et ajout adhésif de composite.",
    "REST-CROWN-RECEMENT": "Rescellement d'une couronne ou d'un bridge descellé : nettoyage de l'intrados, contrôle de l'intégrité de la dent support et scellement définitif.",
    "REST-CROWN-POST-ENDO": "Couronne sur dent dépulpée, après reconstitution corono-radiculaire (inlay-core ou tenon fibré) pour protéger la dent fragilisée des fractures.",
    "REST-HEAL-ABUT": "Pilier de cicatrisation (vis de cicatrisation) vissé sur l'implant lors de la mise en fonction : guide la cicatrisation gingivale et forme le profil d'émergence.",
    "REST-DEF-ABUT": "Pilier prothétique définitif (titane, zircone ou personnalisé par CFAO) vissé sur l'implant au couple recommandé, destiné à recevoir la couronne.",
    "ENDO-UNI": "Traitement endodontique d'une dent monoradiculée (incisive, canine, certaines prémolaires) : cathétérisme, mise en forme, irrigation NaOCl et obturation à la gutta-percha.",
    "ENDO-BI": "Traitement endodontique d'une dent biradiculée (prémolaire à deux canaux) : localisation, mise en forme, désinfection et obturation des deux canaux.",
    "ENDO-MULTI": "Traitement endodontique d'une molaire (3 à 4 canaux, dont le MV2) : mise en forme mécanisée, désinfection et obturation tridimensionnelle sous digue.",
    "ENDO-RETREAT": "Retraitement endodontique : dépose de l'obturation existante (gutta, tenon), désinfection et nouvelle obturation en cas de lésion persistante ou de symptômes.",
    "ENDO-POST-FIBER": "Tenon en fibre de verre collé dans le canal pour ancrer une reconstitution corono-radiculaire foulée (module d'élasticité proche de la dentine).",
    "ENDO-POST-METAL": "Inlay-core / tenon coulé métallique (Co-Cr ou alliage précieux) scellé dans le canal, reconstituant le moignon d'une dent dépulpée très délabrée.",
    "ENDO-URGENT": "Trépanation d'urgence : ouverture de la chambre pulpaire, pulpotomie ou parage canalaire pour soulager une pulpite ou un abcès, puis médication et pansement.",
    "ENDO-MED-REFRESH": "Renouvellement de la médication intracanalaire (hydroxyde de calcium) entre deux séances d'endodontie, avec réfection du pansement provisoire étanche.",
    "ENDO-APICOFORM": "Apexification : induction d'une barrière apicale (MTA, Biodentine ou hydroxyde de calcium) sur une dent immature nécrosée à apex ouvert, avant obturation.",
    "ENDO-PED": "Traitement endodontique d'une dent temporaire (pulpotomie ou pulpectomie) avec matériau résorbable (oxyde de zinc-eugénol, pâte iodoformée).",
    "PERIO-SPLINT-RAR": "Contention post-surfaçage : solidarisation des dents mobiles après détartrage-surfaçage radiculaire pour stabiliser le parodonte pendant la cicatrisation.",
    "SURG-EXT-SIMPLE": "Extraction simple sous anesthésie locale : syndesmotomie, luxation à l'élévateur et avulsion au davier, sans lambeau ni ostéotomie ; compression et hémostase.",
    "SURG-EXT-COMPLEX": "Extraction compliquée : séparation des racines et/ou lambeau nécessaires (racines divergentes ou courbes, dent délabrée, ankylose), sutures.",
    "SURG-EXT-3MOLAR": "Avulsion d'une dent de sagesse (troisième molaire) éruptée ou semi-incluse, avec éventuels lambeau, ostéotomie et odontosection ; conseils post-opératoires.",
    "SURG-EXT-OST": "Extraction chirurgicale avec lambeau muco-périosté, ostéotomie vestibulaire et odontosection éventuelle, suivie de régularisation osseuse et de sutures.",
    "SURG-IMP-TI": "Pose d'un implant en titane (grade 4 ou Ti-6Al-4V) : lambeau, forage séquentiel sous irrigation, insertion au couple contrôlé, vis de couverture ou de cicatrisation.",
    "SURG-IMP-ZIR": "Pose d'un implant en zircone (céramique), monobloc ou deux pièces : alternative sans métal pour indication esthétique, allergie ou parodonte fin.",
    "SURG-APEC": "Apicectomie : lambeau, ostéotomie, résection apicale de 3 mm, curetage de la lésion, préparation ultrasonore et obturation a retro au MTA, sutures.",
    "SURG-CYST": "Exérèse d'un kyste des maxillaires (radiculaire, résiduel, folliculaire) par énucléation chirurgicale complète, avec envoi de la pièce en anatomopathologie.",
    "SURG-EXT-INCLUIDO": "Avulsion d'une dent incluse (canine, prémolaire, surnuméraire) : lambeau d'accès, ostéotomie, odontosection, extraction et sutures.",
    "ORTO-BRACK": "Remplacement d'un bracket décollé : élimination de la colle résiduelle, mordançage de l'émail et recollage de l'attache en position.",
    "ORTO-RET-FIX": "Contention fixe : fil torsadé collé au composite sur la face linguale/palatine des dents antérieures (canine à canine) en fin de traitement orthodontique.",
    "ORTO-ATTACH": "Taquets en composite collés selon le plan de traitement numérique, servant de points d'appui aux aligneurs transparents pour les mouvements complexes.",
    "ORTO-BRACK-CEMENT": "Collage d'un bracket sur une dent : nettoyage, mordançage, adhésif, positionnement précis de l'attache et photopolymérisation.",
    "PED-SEAL": "Scellement des sillons des molaires temporaires ou des premières molaires permanentes en cours d'éruption chez l'enfant, sous isolation relative.",
    "PED-PULPOTOMY": "Pulpotomie sur dent temporaire : ablation de la pulpe camérale inflammée et coiffage des pulpes radiculaires (MTA, Biodentine ou formocrésol), puis restauration étanche.",
    "PED-CROWN-SS": "Couronne pédiatrique préformée (acier inoxydable ou zircone) sur molaire temporaire très délabrée, après pulpotomie ou en cas de défaut de structure.",
    "PED-EXT-TEMP": "Avulsion d'une dent temporaire (carie non restaurable, abcès, mobilité ou persistance gênant l'éruption de la dent permanente successionnelle).",
    "PED-FILL-TEMP": "Obturation d'une dent temporaire (CVI ou composite) après curetage carieux, avec technique et durée de séance adaptées à l'enfant.",
    "PED-PULPECTOMY": "Pulpectomie sur dent temporaire : ablation complète de la pulpe camérale et radiculaire, puis obturation des canaux avec un matériau résorbable.",
}

for _item in ODONTO_CATALOG:
    _item["description"] = CATALOG_DESCRIPTIONS_FR.get(_item["code"]) or TREATMENT_DESCRIPTIONS_FR.get(_item["clinical_type"], "")

CATALOG_BY_CODE: Final[dict[str, dict[str, Any]]] = {item["code"]: item for item in ODONTO_CATALOG}


def catalog_label(catalog_code: str | None, clinical_type: str) -> str:
    """Libellé FR d'un traitement : nom de l'acte du catalogue, sinon libellé du type clinique."""
    item = CATALOG_BY_CODE.get(catalog_code or "")
    if item:
        return item["label"]
    return TREATMENT_LABELS_FR.get(clinical_type, clinical_type)

def get_tooth_type(tooth_number: int) -> str:
    if tooth_number in PERMANENT_TEETH:
        return "permanent"
    if tooth_number in DECIDUOUS_TEETH:
        return "deciduous"
    raise ValueError(f"Numéro de dent invalide : {tooth_number}")


def is_valid_tooth_number(tooth_number: int) -> bool:
    return tooth_number in ALL_TEETH


def is_valid_treatment_type(t: str) -> bool:
    return t in TREATMENT_TYPES


def arch_order_for(tooth_number: int) -> list[int] | None:
    if tooth_number in UPPER_ARCH_ORDER:
        return UPPER_ARCH_ORDER
    if tooth_number in LOWER_ARCH_ORDER:
        return LOWER_ARCH_ORDER
    return None


def contiguous_runs(teeth: list[int]) -> list[list[int]]:
    """Regroupe des dents en séquences contiguës sur une même arcade (ordre d'arcade)."""
    runs: list[list[int]] = []
    for order in (UPPER_ARCH_ORDER, LOWER_ARCH_ORDER):
        idx = sorted(order.index(t) for t in teeth if t in order)
        cur: list[int] = []
        prev = None
        for i in idx:
            if prev is not None and i != prev + 1:
                runs.append(cur)
                cur = []
            cur.append(order[i])
            prev = i
        if cur:
            runs.append(cur)
    return runs
