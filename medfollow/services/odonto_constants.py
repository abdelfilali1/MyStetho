"""Constantes de l'odontogramme (port de dentalpin `odontogram/constants.py`
et de la partie serveur de `odontogramConstants.ts`).

Numérotation FDI stricte : 11-48 permanentes, 51-85 temporaires.
"""
from __future__ import annotations

from typing import Final

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
