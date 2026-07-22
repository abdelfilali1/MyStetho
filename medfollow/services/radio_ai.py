"""Aides serveur du module Radio IA (détection de pathologies).

L'inférence du modèle **DentalXrayAI** (YOLOv8 DENTEX) tourne désormais DANS LE
NAVIGATEUR via onnxruntime-web (voir static/js/radio/detect.js) — comme la
Céphalométrie — car la VM de production n'a pas assez de RAM pour PyTorch. Le
serveur ne fait donc plus d'inférence : il n'a AUCUNE dépendance lourde.

Ce module ne garde que des utilitaires sans torch, utilisés par les routes qui
persistent l'état (`/save`) et produisent les livrables (`/annotated`, PDF) :
traduction des classes en français, couleur par pathologie, estimation du n° de
dent (FDI) et rendu de l'image annotée (Pillow, déjà dans les dépendances de base).
"""
import os

from config import RADIO_AI_ONNX

# Traduction des noms de classes du modèle (quelle que soit leur casse) en
# libellés français ; toute classe inconnue retombe sur son nom d'origine.
_CLASS_FR = {
    "caries": "Carie",
    "cavity": "Carie",
    "deep caries": "Carie profonde",
    "deep-caries": "Carie profonde",
    "impacted": "Dent incluse",
    "impacted tooth": "Dent incluse",
    "periapical lesion": "Lésion périapicale",
    "periapical": "Lésion périapicale",
    "lesion": "Lésion périapicale",
}

# Une couleur par pathologie (cadre + étiquette), reprise à l'identique côté
# navigateur (workstation.js) et dans le PDF pour que le praticien retrouve le
# même code couleur partout.
_CLASS_COLOR = {
    "caries": "#f59e0b",            # ambre
    "deep caries": "#ef4444",       # rouge
    "impacted": "#6366f1",          # indigo
    "periapical lesion": "#10b981", # émeraude
}
_DEFAULT_COLOR = "#0ea5e9"


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def label_fr(name: str) -> str:
    """Libellé français d'une classe (nom d'origine en repli)."""
    return _CLASS_FR.get(_norm(name), (name or "").strip() or "Anomalie")


def color_for(name: str) -> str:
    return _CLASS_COLOR.get(_norm(name), _DEFAULT_COLOR)


def estimate_fdi(cx: float, cy: float, w: int, h: int):
    """Estime le numéro de dent (notation FDI) à partir de la position de la boîte.

    Le modèle DentalXrayAI ne prédit PAS le numéro de dent : on l'ESTIME
    géométriquement sur un panoramique. Sur ce type de cliché, la droite du
    patient est à gauche de l'image, et les maxillaires sont en haut. On situe
    donc le quadrant (11-48) puis la position 1→8 depuis la ligne médiane vers le
    fond. C'est une aide indicative, à corriger par le praticien — jamais une
    identification certaine (les panoramiques déforment, les dents manquantes
    décalent le comptage).
    """
    if not w or not h:
        return None
    x = cx / w
    upper = (cy / h) < 0.5
    if x < 0.5:                       # moitié gauche de l'image = côté droit du patient
        quadrant = 1 if upper else 4
        pos = (0.5 - x) / 0.5
    else:                            # moitié droite = côté gauche du patient
        quadrant = 2 if upper else 3
        pos = (x - 0.5) / 0.5
    tooth = max(1, min(8, int(round(pos * 7)) + 1))
    return quadrant * 10 + tooth


def model_available() -> bool:
    """Vrai si le fichier ONNX servi au navigateur est présent sur le serveur."""
    return bool(RADIO_AI_ONNX and os.path.exists(RADIO_AI_ONNX))


def availability() -> dict:
    """État renvoyé aux gabarits : le modèle (fichier ONNX) est-il déployé ?

    L'inférence est navigateur ; `ready` indique seulement que le fichier modèle
    est servi (sinon le bouton « Lancer la détection IA » est masqué / la bannière
    d'aide s'affiche). `model_url` est le chemin statique fetché par detect.js.
    """
    return {
        "ready": model_available(),
        "model_url": "/static/js/radio/model/dentalxray.onnx",
    }


def render_annotated_png(image_path: str, detections: list, *, only_kept: bool = True) -> bytes:
    """Dessine les boîtes retenues sur le cliché et renvoie un PNG (Pillow).

    Utilisé pour l'aperçu serveur (`/annotated`) et le rapport PDF, afin que le
    document montre exactement les détections validées par le praticien.
    """
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    W, H = img.size
    # Épaisseur/police proportionnelles à la taille du cliché.
    lw = max(2, round(min(W, H) / 300))
    # Police proportionnelle. Windows a « arial.ttf » ; sous Linux (la VM) on
    # retombe sur DejaVuSans, livré avec Pillow, puis sur la police par défaut.
    font_size = max(12, round(min(W, H) / 45))
    font = None
    for _name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(_name, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    for d in detections:
        if only_kept and d.get("dismissed"):
            continue
        box = d.get("box") or []
        if len(box) != 4:
            continue
        x1, y1, x2, y2 = box
        color = d.get("color") or _DEFAULT_COLOR
        draw.rectangle([x1, y1, x2, y2], outline=color, width=lw)
        conf = d.get("conf")
        tag = d.get("label") or d.get("cls") or "?"
        tooth = d.get("tooth")
        if tooth:
            tag = f"{tag} · {tooth}"
        if isinstance(conf, (int, float)):
            tag = f"{tag} {round(conf * 100)}%"
        # Bandeau d'étiquette au-dessus (ou en dessous si trop haut) de la boîte.
        try:
            tb = draw.textbbox((0, 0), tag, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        except Exception:
            tw, th = len(tag) * 7, 12
        ty = y1 - th - 4
        if ty < 0:
            ty = y1 + 2
        draw.rectangle([x1, ty, x1 + tw + 8, ty + th + 4], fill=color)
        draw.text((x1 + 4, ty + 2), tag, fill="#ffffff", font=font)

    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
