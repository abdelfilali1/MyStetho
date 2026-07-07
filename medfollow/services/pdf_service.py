from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from xml.sax.saxutils import escape as _xml_escape
import io
import os
from typing import Optional
from datetime import date as _date


def _esc(s) -> str:
    """Échappe le texte pour l'insérer sans risque dans un Paragraph reportlab
    (le `&` d'une adresse ou d'un nom casserait sinon le mini-XML)."""
    return _xml_escape(str(s)) if s not in (None, "") else ""


# ─────────────────────────────────────────────────────────────
# Letterhead / template support — stamp generated content on top
# of a per-user PDF background ("le fond sur lequel on écrit").
# ─────────────────────────────────────────────────────────────

def _has_template(template_path: Optional[str]) -> bool:
    return bool(template_path and os.path.exists(template_path))


def _stamp_on_template(content_pdf: bytes, template_path: str) -> bytes:
    """Overlay each page of the reportlab-generated PDF on top of the first page
    of the user's template PDF (letterhead). Returns the merged PDF bytes.
    Falls back to the untouched content on any error so a PDF is always produced."""
    try:
        from pypdf import PdfReader, PdfWriter
        content_reader = PdfReader(io.BytesIO(content_pdf))
        writer = PdfWriter()
        for content_page in content_reader.pages:
            # Re-read the template per page so each output page gets a fresh
            # background (a pypdf page object can't be safely reused/merged twice).
            tpl_page = PdfReader(template_path).pages[0]
            tpl_page.merge_page(content_page)  # content drawn over the letterhead
            writer.add_page(tpl_page)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:
        return content_pdf

# ── Palette — noir & blanc, sobre et professionnel ───────────
# Tout le CONTENU généré est en niveaux de gris. Le papier à en-tête
# (template PDF du médecin) n'est jamais recoloré : il reste tel quel.
PRIMARY      = HexColor("#111111")   # titres, filets, en-têtes de tableau (noir)
PRIMARY_DARK = HexColor("#000000")   # accents (noir pur)
PRIMARY_BG   = HexColor("#f0f0f0")   # fonds d'encadrés (gris très clair)
DARK         = HexColor("#1a1a1a")   # texte principal (quasi noir)
GRAY         = HexColor("#555555")   # texte secondaire (gris neutre)
LIGHT        = HexColor("#f5f5f5")   # lignes alternées des tableaux
BORDER       = HexColor("#cccccc")   # bordures (gris clair)
SUCCESS      = HexColor("#1a1a1a")   # badge "renouvelable" : texte noir
SUCCESS_BG   = HexColor("#f0f0f0")   # badge : fond gris clair
SUCCESS_BDR  = HexColor("#bdbdbd")   # badge : bordure grise
WHITE        = white

_PW, _PH = A4  # 595.27 × 841.89 pts

# Marges de REPLI quand un papier à en-tête est fourni mais que la détection
# automatique de sa hauteur d'en-tête échoue (voir _detect_letterhead_margins).
# En fonctionnement normal les marges sont calculées par template.
TPL_TOP_MM    = 60   # repli : ~6 cm réservés en haut
TPL_BOTTOM_MM = 30   # repli : ~3 cm réservés en bas


# ─────────────────────────────────────────────────────────────
# Canvas callbacks — header band + footer on every page
# ─────────────────────────────────────────────────────────────

def _draw_footer(canvas, doc):
    """Pied de page sobre (séparateur + date de génération + n° de page).
    Utilisé uniquement SANS papier à en-tête — avec un en-tête, le fond
    pré-imprimé porte déjà son propre pied de page. L'EN-TÊTE (titre du
    document + identité du praticien) est désormais rendu dans le flux du
    contenu via `_masthead`, jamais sur le canvas, pour ne jamais chevaucher
    un éventuel papier à en-tête."""
    canvas.saveState()
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(22 * mm, 18 * mm, _PW - 22 * mm, 18 * mm)
    canvas.setFillColor(GRAY)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(22 * mm, 11 * mm, f"Généré le {_date.today().strftime('%d/%m/%Y')}")
    canvas.drawRightString(_PW - 22 * mm, 11 * mm, f"Page {doc.page}")
    canvas.restoreState()


# ─────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────

def _make_doc(buf, top=32, bottom=24):
    return SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm,
        topMargin=top * mm, bottomMargin=bottom * mm,
    )


def _doc_for(buf, template_path, top=32):
    """Build the document with margins adapted to the letterhead.

    Avec un papier à en-tête, on réserve une zone d'en-tête (et de pied)
    pour ne JAMAIS écrire par-dessus le fond pré-imprimé. Cette zone est
    DÉTECTÉE AUTOMATIQUEMENT à partir du template lui-même (chaque médecin a
    un en-tête différent → aucun réglage manuel). Si la détection est
    indisponible, on retombe sur une zone fixe généreuse."""
    if _has_template(template_path):
        m = _detect_letterhead_margins(template_path)
        t, b = m if m else (TPL_TOP_MM, TPL_BOTTOM_MM)
        return _make_doc(buf, top=t, bottom=b)
    return _make_doc(buf, top=top)


# ── Détection automatique de la zone imprimable d'un papier à en-tête ────
# On rastérise la 1re page du template et on repère l'encre la plus basse en
# haut (= bas de l'en-tête) et la plus haute en bas (= haut du pied de page),
# puis on réserve ces bandes + une petite marge. Résultat mis en cache par
# (chemin, mtime). Nécessite PyMuPDF (fitz) ; repli sur marges fixes sinon.
_TPL_MARGIN_CACHE: dict = {}


def _detect_letterhead_margins(template_path):
    try:
        key = (template_path, os.path.getmtime(template_path))
    except OSError:
        return None
    if key not in _TPL_MARGIN_CACHE:
        _TPL_MARGIN_CACHE[key] = _compute_letterhead_margins(template_path)
    return _TPL_MARGIN_CACHE[key]


def _compute_letterhead_margins(template_path):
    """Retourne (top_mm, bottom_mm) réservant l'en-tête/pied du template, ou
    None si l'analyse échoue (PyMuPDF absent, erreur de rendu…)."""
    try:
        import fitz  # PyMuPDF
        dpi = 100
        ppm = dpi / 25.4
        with fitz.open(template_path) as doc:
            page = doc[0]
            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        W, H, s = pix.width, pix.height, pix.samples
        if W == 0 or H == 0 or len(s) < W * H:
            return None
        # Fond ≈ médiane d'un échantillon clairsemé ; encre = nettement plus sombre.
        sub = s[::1009]
        bg = sorted(sub)[len(sub) // 2] if sub else 255
        ink_thr = max(60, min(bg - 25, 235))
        x0, x1 = int(W * 0.18), int(W * 0.82)  # bande centrale → ignore bordures latérales

        def has_ink(y):
            return min(s[y * W + x0: y * W + x1]) < ink_thr

        GAP_MM = 7  # respiration entre le fond et le texte généré
        # En-tête : ligne d'encre la plus basse dans les 45 % supérieurs.
        hb = 0
        for y in range(int(H * 0.45), -1, -1):
            if has_ink(y):
                hb = y
                break
        top_mm = hb / ppm + GAP_MM
        # Pied : ligne d'encre la plus haute dans les 20 % inférieurs.
        ft = H
        for y in range(int(H * 0.80), H):
            if has_ink(y):
                ft = y
                break
        bottom_mm = (H - ft) / ppm + GAP_MM
        # Bornes raisonnables.
        top_mm = max(20.0, min(top_mm, 135.0))
        bottom_mm = max(18.0, min(bottom_mm, 60.0))
        return (top_mm, bottom_mm)
    except Exception:
        return None


def _styles():
    S = getSampleStyleSheet()
    defs = [
        ("_SecHead",   dict(fontName="Helvetica-Bold", fontSize=9,  textColor=PRIMARY,
                            spaceBefore=14, spaceAfter=2, leading=12)),
        ("_Body",      dict(fontName="Helvetica",      fontSize=10, textColor=DARK,
                            leading=14, spaceAfter=2)),
        ("_BodySm",    dict(fontName="Helvetica",      fontSize=9,  textColor=GRAY,
                            leading=13, spaceAfter=1)),
        ("_Italic",    dict(fontName="Helvetica-Oblique", fontSize=9.5, textColor=GRAY, leading=14)),
        ("_Bold",      dict(fontName="Helvetica-Bold", fontSize=10, textColor=DARK, leading=14)),
        ("_MedName",   dict(fontName="Helvetica-Bold", fontSize=11, textColor=DARK,
                            spaceBefore=8, spaceAfter=1, leading=14)),
        ("_MedDetail", dict(fontName="Helvetica", fontSize=9.5, textColor=GRAY,
                            leftIndent=14, leading=13, spaceAfter=1)),
        ("_PatName",   dict(fontName="Helvetica-Bold", fontSize=15, textColor=DARK,
                            spaceAfter=2, leading=18)),
        ("_PatSub",    dict(fontName="Helvetica", fontSize=10, textColor=GRAY, spaceAfter=0)),
    ]
    for name, kw in defs:
        if name not in S:
            S.add(ParagraphStyle(name, parent=S["Normal"], **kw))
    return S


def _section(title, S):
    return [
        Paragraph(title.upper(), S["_SecHead"]),
        HRFlowable(width="100%", thickness=1, color=PRIMARY, spaceAfter=5, spaceBefore=0),
    ]


def _practitioner_html(doctor_name=None, specialty=None, address=None, phone=None) -> str:
    """Bloc identité praticien (nom, spécialité, adresse, téléphone) en mini-HTML
    reportlab, une info par ligne. Sert d'en-tête de repli quand le médecin n'a
    pas de papier à en-tête : « à côté du nom, l'adresse et le téléphone »."""
    lines = []
    if doctor_name:
        lines.append(f"<b>{_esc(doctor_name)}</b>")
    if specialty:
        lines.append(_esc(specialty))
    if address:
        lines.append(_esc(address).replace("\n", "<br/>"))
    if phone:
        lines.append(f"Tél. {_esc(phone)}")
    return "<br/>".join(lines)


def _masthead(S, title, *, doctor_name=None, specialty=None, address=None,
              phone=None, use_tpl=False, subtitle=None):
    """En-tête standard commun à TOUS les PDF de l'application.

    - Le TITRE du document (ordonnance, devis, note…) est toujours affiché à
      gauche, y compris avec un papier à en-tête : comme c'est un flowable, il
      s'inscrit sous la zone d'en-tête réservée (marge haute détectée) et ne
      chevauche donc jamais le fond pré-imprimé.
    - À droite, l'identité du praticien (nom + spécialité + adresse + téléphone)
      n'est ajoutée QUE sans papier à en-tête (sinon le fond la porte déjà).
    Renvoie la liste de flowables [table titre/praticien, filet]."""
    title_st = ParagraphStyle("_mhTitle", parent=S["_Body"], fontName="Helvetica-Bold",
                              fontSize=16, textColor=DARK, leading=19, alignment=TA_LEFT)
    left = [Paragraph(_esc(title).upper(), title_st)]
    if subtitle:
        left.append(Paragraph(_esc(subtitle), ParagraphStyle(
            "_mhSub", parent=S["_BodySm"], textColor=GRAY, spaceBefore=2)))

    right_html = "" if use_tpl else _practitioner_html(doctor_name, specialty, address, phone)
    right_st = ParagraphStyle("_mhDoc", parent=S["_BodySm"], alignment=TA_RIGHT,
                              textColor=GRAY, leading=12.5, fontSize=9)
    right = [Paragraph(right_html or "", right_st)]

    t = Table([[left, right]], colWidths=[95 * mm, 76 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [t, HRFlowable(width="100%", thickness=1.1, color=PRIMARY, spaceBefore=6, spaceAfter=12)]


def _patient_box(S, name, sub=None):
    inner = [Paragraph(name, S["_PatName"])]
    if sub:
        inner.append(Paragraph(sub, S["_PatSub"]))
    t = Table([inner], colWidths=[171 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), PRIMARY_BG),
        ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
        ("TOPPADDING",    (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
        ("LINEBELOW",     (0, -1), (-1, -1), 3, PRIMARY),
    ]))
    return t


def _info_table(rows):
    t = Table(rows, colWidths=[58 * mm, 113 * mm])
    style = [
        ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",      (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR",     (0, 0), (0, -1), GRAY),
        ("TEXTCOLOR",     (1, 0), (1, -1), DARK),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
    ]
    for i in range(len(rows)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    style.append(("BOX", (0, 0), (-1, -1), 0.5, BORDER))
    t.setStyle(TableStyle(style))
    return t


def _sig_block(doctor_name):
    t = Table(
        [["", Paragraph("Signature et cachet du médecin",
                        ParagraphStyle("_sl", parent=getSampleStyleSheet()["Normal"],
                                       fontSize=8, textColor=GRAY, alignment=TA_CENTER))],
         ["", Paragraph(f"Dr. {doctor_name}",
                        ParagraphStyle("_sn", parent=getSampleStyleSheet()["Normal"],
                                       fontName="Helvetica-Bold", fontSize=10,
                                       textColor=DARK, alignment=TA_CENTER))]],
        colWidths=[86 * mm, 85 * mm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND",    (1, 0), (1, -1), LIGHT),
        ("BOX",           (1, 0), (1, -1), 0.5, BORDER),
        ("LINEBELOW",     (1, 1), (1, 1), 1.2, GRAY),
        ("TOPPADDING",    (1, 0), (1, -1), 8),
        ("BOTTOMPADDING", (1, 0), (1, -1), 16),
        ("LEFTPADDING",   (1, 0), (1, -1), 8),
        ("RIGHTPADDING",  (1, 0), (1, -1), 8),
    ]))
    return t


# ═════════════════════════════════════════════════════════════
# ORDONNANCE
# ═════════════════════════════════════════════════════════════

_FR_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
              "août", "septembre", "octobre", "novembre", "décembre"]


def _fr_long_date(s) -> str:
    """'2026-03-09' -> 'Le 09 mars 2026'. Forme lisible en cas de doute."""
    try:
        y, m, d = str(s)[:10].split("-")
        return f"Le {int(d):02d} {_FR_MONTHS[int(m) - 1]} {y}"
    except Exception:
        return f"Le {s}" if s else ""


def _fr_short_date(s) -> str:
    """'1999-02-28' -> '28/02/1999'."""
    try:
        y, m, d = str(s)[:10].split("-")
        return f"{int(d):02d}/{int(m):02d}/{y}"
    except Exception:
        return str(s) if s else ""


def generate_prescription_pdf(prescription: dict, items: list,
                              template_path: Optional[str] = None,
                              allergies: Optional[str] = None) -> bytes:
    """Ordonnance épurée, facile à lire (style « ordonnance médicale ») :
    date en haut à droite, patient (nom / naissance / allergies) aligné à droite,
    médicaments à gauche (nom en gras + posologie en clair), signature en bas.
    Aucun encadré gris ; le papier à en-tête du médecin reste tel quel."""
    use_tpl = _has_template(template_path)
    buf = io.BytesIO()
    doc = _doc_for(buf, template_path)
    S = _styles()

    base = getSampleStyleSheet()["Normal"]
    name_st = ParagraphStyle("_oName", parent=base, fontName="Helvetica-Bold",
                             fontSize=11.5, textColor=DARK, alignment=TA_RIGHT, leading=15)
    sub_st  = ParagraphStyle("_oSub", parent=base, fontName="Helvetica",
                             fontSize=9.5, textColor=GRAY, alignment=TA_RIGHT, leading=13)
    alg_st  = ParagraphStyle("_oAlg", parent=base, fontName="Helvetica-Oblique",
                             fontSize=9.5, textColor=DARK, alignment=TA_RIGHT, leading=13)
    date_st = ParagraphStyle("_oDate", parent=base, fontName="Helvetica",
                             fontSize=10, textColor=DARK, alignment=TA_RIGHT, leading=13)
    drug_st = ParagraphStyle("_oDrug", parent=base, fontName="Helvetica-Bold",
                             fontSize=10.5, textColor=DARK, leading=14, spaceBefore=12, spaceAfter=1)
    poso_st = ParagraphStyle("_oPoso", parent=base, fontName="Helvetica",
                             fontSize=10, textColor=DARK, leading=14)
    note_st = ParagraphStyle("_oNote", parent=base, fontName="Helvetica-Oblique",
                             fontSize=9.5, textColor=GRAY, leading=13)
    sign_st = ParagraphStyle("_oSign", parent=base, fontName="Helvetica-Bold",
                             fontSize=10.5, textColor=DARK, alignment=TA_RIGHT, leading=14)
    sigl_st = ParagraphStyle("_oSigl", parent=base, fontName="Helvetica",
                             fontSize=8.5, textColor=GRAY, alignment=TA_RIGHT, leading=12)

    doctor_name = f"{prescription['d_first']} {prescription['d_last']}"

    def _page(canv, d):
        if use_tpl:
            return  # le papier à en-tête fournit l'en-tête / pied de page
        _draw_footer(canv, d)

    # En-tête standard : titre « ORDONNANCE » (toujours) + identité praticien
    # (nom / spécialité / adresse / téléphone) si pas de papier à en-tête.
    els = _masthead(
        S, "Ordonnance",
        doctor_name=f"Dr. {doctor_name}",
        specialty=prescription.get("specialty"),
        address=prescription.get("address"),
        phone=prescription.get("phone"),
        use_tpl=use_tpl,
    )

    # ── Date (en haut à droite) ──
    els.append(Paragraph(_fr_long_date(prescription.get("prescription_date")), date_st))
    els.append(Spacer(1, 16))

    # ── Patient (à droite : nom, naissance, allergies) ──
    els.append(Paragraph(f"{prescription['p_last'].upper()} {prescription['p_first']}", name_st))
    if prescription.get("date_of_birth"):
        els.append(Paragraph(f"Né(e) le {_fr_short_date(prescription['date_of_birth'])}", sub_st))
    alg_txt = (allergies or "").strip()
    els.append(Paragraph(f"Allergies : {alg_txt}" if alg_txt else "Allergies : aucune connue", alg_st))
    els.append(Spacer(1, 22))

    # ── Médicaments (à gauche : nom en gras + posologie) ──
    for item in items:
        block = [Paragraph(item.get("medication_name", ""), drug_st)]
        seg = []
        if item.get("dosage"):
            seg.append(str(item["dosage"]))
        if item.get("frequency"):
            seg.append(str(item["frequency"]))
        detail = ", ".join(seg)
        if item.get("duration"):
            detail += (", " if detail else "") + f"pendant {item['duration']}"
        if detail and not detail.endswith("."):
            detail += "."
        if item.get("instructions"):
            instr = str(item["instructions"]).strip()
            detail += (" " if detail else "") + instr + ("" if instr.endswith(".") else ".")
        if item.get("quantity"):
            detail += f" Quantité : {item['quantity']}."
        if detail:
            block.append(Paragraph(detail, poso_st))
        els.append(KeepTogether(block))

    # ── Notes / renouvelable (texte simple, sans encadré) ──
    if prescription.get("notes"):
        els.append(Spacer(1, 10))
        els.append(Paragraph(prescription["notes"], note_st))
    if prescription.get("is_renewable"):
        els.append(Spacer(1, 8))
        els.append(Paragraph("Ordonnance renouvelable.", note_st))

    # ── Signature (en bas à droite, sans encadré) ──
    els.append(Spacer(1, 34))
    els.append(Paragraph(f"Dr. {doctor_name}", sign_st))
    els.append(Paragraph("Signature et cachet", sigl_st))

    doc.build(els, onFirstPage=_page, onLaterPages=_page)
    out = buf.getvalue()
    return _stamp_on_template(out, template_path) if use_tpl else out


# ═════════════════════════════════════════════════════════════
# FICHE PATIENT
# ═════════════════════════════════════════════════════════════

# Libellés lisibles des états dentaires (odontogramme). Repli : Capitalize.
_DENTAL_LABELS = {
    "sain": "Sain",
    "carie": "Carie",
    "obturation": "Obturation (plombage)",
    "plombage": "Obturation (plombage)",
    "couronne": "Couronne",
    "bridge": "Bridge",
    "implant": "Implant",
    "absente": "Absente / extraite",
    "manquante": "Absente / extraite",
    "extraction": "À extraire",
    "a_extraire": "À extraire",
    "fracture": "Fracture",
    "descellement": "Descellement",
    "endodontie": "Traitement radiculaire",
    "traitement_canal": "Traitement radiculaire",
    "prothese": "Prothèse",
    "facette": "Facette",
    "scellement": "Scellement de sillon",
    "fele": "Fêlure",
}


def generate_patient_brochure_pdf(
    patient: dict, history: list, appointments: list, prescriptions: list,
    template_path: Optional[str] = None,
    doctor_name: str = "", specialty: str = "",
    address: Optional[str] = None, phone: Optional[str] = None,
    dental: Optional[list] = None,
) -> bytes:
    use_tpl = _has_template(template_path)
    buf = io.BytesIO()
    doc = _doc_for(buf, template_path)
    S = _styles()

    full_name = f"{patient.get('last_name', '').upper()} {patient.get('first_name', '')}"

    def _page(canv, d):
        if use_tpl:
            return
        _draw_footer(canv, d)

    els = _masthead(
        S, "Fiche patient",
        doctor_name=doctor_name or None,
        specialty=specialty or None,
        address=address, phone=phone, use_tpl=use_tpl,
    )

    # Patient banner
    sub_parts = []
    if patient.get("date_of_birth"):
        sub_parts.append(f"Né(e) le {patient['date_of_birth']}")
    if patient.get("gender"):
        sub_parts.append(patient["gender"])
    if patient.get("blood_type"):
        sub_parts.append(f"Groupe {patient['blood_type']}")
    els.append(_patient_box(S, full_name, "  •  ".join(sub_parts) if sub_parts else None))
    els.append(Spacer(1, 12))

    # Personal info
    id_rows = []
    if patient.get("date_of_birth"):
        id_rows.append(["Date de naissance", patient["date_of_birth"]])
    if patient.get("gender"):
        id_rows.append(["Sexe", patient["gender"]])
    if patient.get("blood_type"):
        id_rows.append(["Groupe sanguin", patient["blood_type"]])
    if patient.get("phone"):
        id_rows.append(["Téléphone", patient["phone"]])
    if patient.get("email"):
        id_rows.append(["Email", patient["email"]])
    if patient.get("address"):
        addr = patient["address"]
        if patient.get("city"):
            addr += f", {patient['city']}"
        if patient.get("postal_code"):
            addr += f" {patient['postal_code']}"
        id_rows.append(["Adresse", addr])
    if patient.get("social_security_number"):
        id_rows.append(["N° CIN", patient["social_security_number"]])
    if patient.get("insurance_name"):
        ins = patient["insurance_name"]
        if patient.get("insurance_number"):
            ins += f" — N° {patient['insurance_number']}"
        if patient.get("insurance_serial"):
            ins += f" — Série {patient['insurance_serial']}"
        id_rows.append(["Mutuelle / Assurance", ins])

    if id_rows:
        els.extend(_section("Informations personnelles", S))
        els.append(_info_table(id_rows))
        els.append(Spacer(1, 10))

    # Medical history
    if history:
        els.extend(_section("Antécédents médicaux", S))
        type_labels = {
            "medical": "Médical", "surgical": "Chirurgical",
            "family": "Familial", "allergy": "Allergie",
        }
        hist_rows = [
            [type_labels.get(h.get("type", ""), "Autre"), h.get("description", "")]
            for h in history
        ]
        ht = Table(hist_rows, colWidths=[38 * mm, 133 * mm])
        style = [
            ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 9.5),
            ("TEXTCOLOR",     (0, 0), (0, -1), PRIMARY),
            ("TEXTCOLOR",     (1, 0), (1, -1), DARK),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ]
        for i in range(len(hist_rows)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
        ht.setStyle(TableStyle(style))
        els.append(ht)
        els.append(Spacer(1, 10))

    # Appointments
    if appointments:
        els.extend(_section("Prochains rendez-vous", S))
        appt_data = [["Date", "Motif", "Statut"]]
        for a in appointments[:5]:
            appt_data.append([
                str(a.get("start_datetime", ""))[:16].replace("T", " "),
                a.get("title", ""),
                a.get("status", ""),
            ])
        at = Table(appt_data, colWidths=[46 * mm, 96 * mm, 29 * mm])
        at.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
            ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE",      (0, 0), (-1, -1), 9.5),
            ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        els.append(at)
        els.append(Spacer(1, 10))

    # Current prescriptions
    if prescriptions:
        els.extend(_section("Traitements en cours", S))
        for rx in prescriptions[:3]:
            els.append(Paragraph(
                f"Ordonnance du <b>{str(rx.get('prescription_date', ''))[:10]}</b>",
                S["_Bold"],
            ))
            for item in rx.get("items", []):
                els.append(Paragraph(
                    f"•  {item.get('medication_name', '')}  —  "
                    f"{item.get('dosage', '')}  —  {item.get('frequency', '')}",
                    S["_MedDetail"],
                ))
            els.append(Spacer(1, 6))

    # État bucco-dentaire (odontogramme) — résumé imprimable : on ne liste que
    # les dents non saines (les seules cliniquement pertinentes à consigner).
    if dental:
        cell = ParagraphStyle("_dCell", parent=S["_BodySm"], textColor=DARK, fontSize=9.5, leading=12)
        head_st = ParagraphStyle("_dH", parent=cell, textColor=WHITE, fontName="Helvetica-Bold")
        drows = [[Paragraph("Dent", head_st), Paragraph("État", head_st), Paragraph("Observations", head_st)]]
        for tth in dental:
            cond = str(tth.get("condition") or "").strip()
            drows.append([
                Paragraph(_esc(tth.get("tooth_number") or "—"), cell),
                Paragraph(_esc(_DENTAL_LABELS.get(cond.lower(), cond.capitalize() or "—")), cell),
                Paragraph(_esc(tth.get("notes") or ""), cell),
            ])
        if len(drows) > 1:
            els.extend(_section("État bucco-dentaire (odontogramme)", S))
            dt = Table(drows, colWidths=[22 * mm, 47 * mm, 102 * mm])
            dstyle = [
                ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
            for i in range(1, len(drows)):
                if i % 2 == 0:
                    dstyle.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
            dt.setStyle(TableStyle(dstyle))
            els.append(dt)
            els.append(Spacer(1, 10))

    doc.build(els, onFirstPage=_page, onLaterPages=_page)
    out = buf.getvalue()
    return _stamp_on_template(out, template_path) if use_tpl else out


# ═════════════════════════════════════════════════════════════
# COMPTE RENDU DE CONSULTATION
# ═════════════════════════════════════════════════════════════

def generate_consultation_pdf(
    consultation: dict, vitals: dict | None = None, summary: str | None = None,
    template_path: Optional[str] = None,
) -> bytes:
    use_tpl = _has_template(template_path)
    buf = io.BytesIO()
    doc = _doc_for(buf, template_path)
    S = _styles()

    doc_date    = consultation.get("consultation_date", "")[:10]
    doctor_name = consultation.get("doctor_name", "")

    def _page(canv, d):
        if use_tpl:
            return
        _draw_footer(canv, d)

    els = _masthead(
        S, "Compte rendu de consultation",
        doctor_name=f"Dr. {doctor_name}" if doctor_name else None,
        specialty=consultation.get("specialty"),
        address=consultation.get("address"),
        phone=consultation.get("phone"),
        use_tpl=use_tpl,
        subtitle=f"Consultation du {_fr_short_date(doc_date)}" if doc_date else None,
    )

    # Patient box
    pname = consultation.get("patient_name", "Patient inconnu")
    pdetails = []
    if consultation.get("date_of_birth"):
        pdetails.append(f"Né(e) le {consultation['date_of_birth']}")
    if consultation.get("gender"):
        pdetails.append(f"Sexe : {consultation['gender']}")
    els.append(_patient_box(S, pname, "  •  ".join(pdetails) if pdetails else None))
    els.append(Spacer(1, 10))

    # Vitals — 2-column layout
    if vitals:
        vpairs = []
        if vitals.get("weight") is not None:
            vpairs.append(("Poids", f"{vitals['weight']} kg"))
        if vitals.get("height") is not None:
            vpairs.append(("Taille", f"{vitals['height']} cm"))
        if vitals.get("weight") and vitals.get("height"):
            bmi = vitals["weight"] / ((vitals["height"] / 100) ** 2)
            vpairs.append(("IMC", f"{bmi:.1f} kg/m²"))
        bp = vitals.get("blood_pressure_sys")
        if bp is not None:
            vpairs.append(("Tension artérielle",
                           f"{bp}/{vitals.get('blood_pressure_dia', '')} mmHg"))
        if vitals.get("heart_rate") is not None:
            vpairs.append(("Fréq. cardiaque", f"{vitals['heart_rate']} bpm"))
        if vitals.get("temperature") is not None:
            vpairs.append(("Température", f"{vitals['temperature']} °C"))
        if vitals.get("spo2") is not None:
            vpairs.append(("SpO2", f"{vitals['spo2']} %"))

        if vpairs:
            els.extend(_section("Constantes vitales", S))
            vdata = []
            for j in range(0, len(vpairs), 2):
                l = vpairs[j]
                r = vpairs[j + 1] if j + 1 < len(vpairs) else ("", "")
                vdata.append([l[0], l[1], r[0], r[1]])
            vt = Table(vdata, colWidths=[46 * mm, 39 * mm, 46 * mm, 40 * mm])
            vstyle = [
                ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME",      (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTNAME",      (1, 0), (1, -1), "Helvetica"),
                ("FONTNAME",      (3, 0), (3, -1), "Helvetica"),
                ("FONTSIZE",      (0, 0), (-1, -1), 9.5),
                ("TEXTCOLOR",     (0, 0), (0, -1), GRAY),
                ("TEXTCOLOR",     (2, 0), (2, -1), GRAY),
                ("TEXTCOLOR",     (1, 0), (1, -1), DARK),
                ("TEXTCOLOR",     (3, 0), (3, -1), DARK),
                ("TOPPADDING",    (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
            ]
            for i in range(len(vdata)):
                if i % 2 == 0:
                    vstyle.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
            vt.setStyle(TableStyle(vstyle))
            els.append(vt)
            els.append(Spacer(1, 10))

    # Clinical text sections (skip if empty)
    def add_text(title, value):
        if value:
            els.extend(_section(title, S))
            els.append(Paragraph(value, S["_Body"]))
            els.append(Spacer(1, 4))

    add_text("Motif de consultation", consultation.get("reason"))
    add_text("Symptômes", consultation.get("symptoms"))
    add_text("Examen clinique", consultation.get("clinical_exam"))

    # Diagnosis — highlighted box
    if consultation.get("diagnosis"):
        els.extend(_section("Diagnostic", S))
        diag = Table([[consultation["diagnosis"]]], colWidths=[171 * mm])
        diag.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), PRIMARY_BG),
            ("FONTNAME",      (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 10.5),
            ("TEXTCOLOR",     (0, 0), (-1, -1), DARK),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING",   (0, 0), (-1, -1), 12),
            ("LINEBELOW",     (0, 0), (-1, -1), 3, PRIMARY),
            ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ]))
        els.append(diag)
        els.append(Spacer(1, 6))

    add_text("Plan de traitement", consultation.get("treatment_plan"))

    if consultation.get("notes"):
        add_text("Notes", consultation.get("notes"))

    # Summary
    if summary:
        els.extend(_section("Résumé de la consultation", S))
        for block in summary.split("\n\n"):
            lines = block.split("\n")
            if not lines:
                continue
            if len(lines) == 1:
                els.append(Paragraph(lines[0], S["_BodySm"]))
            else:
                els.append(Paragraph(f"<b>{lines[0]}</b>", S["_Body"]))
                for item in lines[1:]:
                    els.append(Paragraph(item.strip(), S["_BodySm"]))
            els.append(Spacer(1, 3))

    # Signature
    els.append(Spacer(1, 36))
    els.append(_sig_block(doctor_name))

    doc.build(els, onFirstPage=_page, onLaterPages=_page)
    out = buf.getvalue()
    return _stamp_on_template(out, template_path) if use_tpl else out


# ═════════════════════════════════════════════════════════════
# NOTE D'HONORAIRES (sur papier à en-tête si disponible)
# ═════════════════════════════════════════════════════════════

def generate_note_honoraires_pdf(
    note: dict, actes: list, doctor_name: str = "", specialty: str = "",
    template_path: Optional[str] = None,
    address: Optional[str] = None, phone: Optional[str] = None,
    inpe: Optional[str] = None, ice: Optional[str] = None,
    if_number: Optional[str] = None, cnss: Optional[str] = None,
) -> bytes:
    use_tpl = _has_template(template_path)
    buf = io.BytesIO()
    doc = _doc_for(buf, template_path)
    S = _styles()

    def _page(canv, d):
        if use_tpl:
            return
        _draw_footer(canv, d)

    els = _masthead(
        S, "Note d'honoraires",
        doctor_name=doctor_name or None, specialty=specialty or None,
        address=address, phone=phone, use_tpl=use_tpl,
        subtitle="CNOPS / CNSS",
    )

    # Identifiants fiscaux du praticien (n'inclure que les valeurs fournies =
    # cases « Afficher sur la note » cochées). Toujours affichés sur la note,
    # même sur papier à en-tête (obligations fiscales de la note d'honoraires).
    ident_bits = []
    if inpe:
        ident_bits.append(f"INPE : {_esc(inpe)}")
    if ice:
        ident_bits.append(f"ICE : {_esc(ice)}")
    if if_number:
        ident_bits.append(f"IF : {_esc(if_number)}")
    if cnss:
        ident_bits.append(f"CNSS : {_esc(cnss)}")
    if ident_bits:
        ident_st = ParagraphStyle("_nIdent", parent=S["_BodySm"], textColor=GRAY,
                                  fontSize=9, leading=12)
        els.append(Paragraph("&nbsp;&nbsp;·&nbsp;&nbsp;".join(ident_bits), ident_st))
        els.append(Spacer(1, 8))

    # N° + date
    num = note.get("numero_note") or "—"
    date_str = note.get("date_soin") or ""
    meta = Table([[f"N° {num}", f"Date : {date_str}"]], colWidths=[85 * mm, 86 * mm])
    meta.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), GRAY),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    els.append(meta)
    els.append(Spacer(1, 8))

    # Patient
    els.append(_patient_box(S, f"Patient : {note.get('nom_beneficiaire') or '—'}"))
    els.append(Spacer(1, 12))

    # Tableau des actes
    cell = ParagraphStyle("_nCell", parent=S["_BodySm"], textColor=DARK, fontSize=9.5, leading=12)
    head = [Paragraph(f"<b>{h}</b>", ParagraphStyle("_nH", parent=cell, textColor=WHITE))
            for h in ("Code", "Désignation", "Dent(s)", "Date", "Montant")]
    data = [head]
    total = 0.0
    for a in actes:
        try:
            m = float(a.get("montant") or 0)
        except (TypeError, ValueError):
            m = 0.0
        total += m
        data.append([
            Paragraph(str(a.get("code") or ""), cell),
            Paragraph(str(a.get("libelle") or ""), cell),
            Paragraph(str(a.get("toothNumber") or "—"), cell),
            Paragraph(str(a.get("date") or ""), cell),
            Paragraph(f"{m:.2f} DH", ParagraphStyle("_nAmt", parent=cell, alignment=TA_RIGHT)),
        ])
    try:
        grand_total = float(note.get("total_montant"))
    except (TypeError, ValueError):
        grand_total = total
    data.append([
        "", "", "", Paragraph("<b>TOTAL</b>", cell),
        Paragraph(f"<b>{grand_total:.2f} DH</b>", ParagraphStyle("_nTot", parent=cell, alignment=TA_RIGHT)),
    ])
    tbl = Table(data, colWidths=[20 * mm, 83 * mm, 18 * mm, 24 * mm, 26 * mm])
    tstyle = [
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -2), 0.3, BORDER),
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, DARK),
        ("SPAN", (0, -1), (2, -1)),
    ]
    for i in range(1, len(data) - 1):
        if i % 2 == 0:
            tstyle.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    tbl.setStyle(TableStyle(tstyle))
    els.append(tbl)

    # Signatures
    els.append(Spacer(1, 30))
    sig = Table([[
        Paragraph("Signature du patient", ParagraphStyle("_sp", parent=S["_BodySm"], alignment=TA_CENTER)),
        Paragraph("Cachet et signature du praticien", ParagraphStyle("_sd", parent=S["_BodySm"], alignment=TA_CENTER)),
    ]], colWidths=[85 * mm, 86 * mm])
    sig.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (0, 0), 0.7, GRAY),
        ("LINEABOVE", (1, 0), (1, 0), 0.7, GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    els.append(sig)

    doc.build(els, onFirstPage=_page, onLaterPages=_page)
    out = buf.getvalue()
    return _stamp_on_template(out, template_path) if use_tpl else out


def _amount_items_table(S, items):
    """Tableau Désignation / Qté / Prix unit. / Total, avec ligne TOTAL. Renvoie (table, total)."""
    cell = ParagraphStyle("_iCell", parent=S["_BodySm"], textColor=DARK, fontSize=9.5, leading=12)
    head = [Paragraph(f"<b>{h}</b>", ParagraphStyle("_iH", parent=cell, textColor=WHITE))
            for h in ("Désignation", "Qté", "Prix unit.", "Total")]
    data = [head]
    total = 0.0
    for it in items:
        try:
            qty = float(it.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        try:
            unit = float(it.get("unit_price") or 0)
        except (TypeError, ValueError):
            unit = 0.0
        line_total = float(it.get("total_price") or (qty * unit))
        total += line_total
        desc = str(it.get("description") or "")
        code = it.get("code")
        if code:
            desc = f"<b>{code}</b> — {desc}"
        teeth = it.get("tooth_numbers")
        if teeth:
            desc += f" <font color='#777777'>(dents {teeth})</font>"
        data.append([
            Paragraph(desc, cell),
            Paragraph(f"{int(qty) if qty == int(qty) else qty}", ParagraphStyle("_iQ", parent=cell, alignment=TA_CENTER)),
            Paragraph(f"{unit:.2f} DH", ParagraphStyle("_iU", parent=cell, alignment=TA_RIGHT)),
            Paragraph(f"{line_total:.2f} DH", ParagraphStyle("_iT", parent=cell, alignment=TA_RIGHT)),
        ])
    data.append([
        "", "", Paragraph("<b>TOTAL</b>", ParagraphStyle("_iTL", parent=cell, alignment=TA_RIGHT)),
        Paragraph(f"<b>{total:.2f} DH</b>", ParagraphStyle("_iTV", parent=cell, alignment=TA_RIGHT)),
    ])
    tbl = Table(data, colWidths=[97 * mm, 18 * mm, 28 * mm, 28 * mm])
    tstyle = [
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -2), 0.3, BORDER),
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, DARK),
        ("SPAN", (0, -1), (1, -1)),
    ]
    for i in range(1, len(data) - 1):
        if i % 2 == 0:
            tstyle.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    tbl.setStyle(TableStyle(tstyle))
    return tbl, total


def generate_invoice_pdf(
    invoice: dict, items: list, payments: list,
    doctor_name: str = "", specialty: str = "", template_path: Optional[str] = None,
    address: Optional[str] = None, phone: Optional[str] = None,
) -> bytes:
    """Facture imprimable / téléchargeable (item 14)."""
    use_tpl = _has_template(template_path)
    buf = io.BytesIO()
    doc = _doc_for(buf, template_path)
    S = _styles()

    def _page(canv, d):
        if use_tpl:
            return
        _draw_footer(canv, d)

    els = _masthead(
        S, "Facture",
        doctor_name=doctor_name or None, specialty=specialty or None,
        address=address, phone=phone, use_tpl=use_tpl,
        subtitle=f"N° {invoice.get('invoice_number') or '—'}",
    )

    date_str = invoice.get("invoice_date") or ""
    meta = Table([[f"Patient : {invoice.get('patient_name') or '—'}", f"Date : {date_str}"]], colWidths=[105 * mm, 66 * mm])
    meta.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10), ("TEXTCOLOR", (0, 0), (-1, -1), GRAY),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    els.append(meta)
    els.append(Spacer(1, 10))

    tbl, total = _amount_items_table(S, items)
    els.append(tbl)

    try:
        paid = float(invoice.get("paid_amount") or 0)
    except (TypeError, ValueError):
        paid = 0.0
    due = max(0.0, total - paid)
    els.append(Spacer(1, 10))
    recap = Table([
        [Paragraph("Payé", S["_BodySm"]), Paragraph(f"{paid:.2f} DH", ParagraphStyle("_rP", parent=S["_BodySm"], alignment=TA_RIGHT))],
        [Paragraph("<b>Reste dû</b>", S["_BodySm"]), Paragraph(f"<b>{due:.2f} DH</b>", ParagraphStyle("_rD", parent=S["_BodySm"], alignment=TA_RIGHT))],
    ], colWidths=[143 * mm, 28 * mm])
    recap.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    els.append(recap)

    if invoice.get("notes"):
        els.append(Spacer(1, 10))
        els.append(Paragraph(f"<b>Notes :</b> {invoice.get('notes')}", S["_BodySm"]))

    els.append(Spacer(1, 30))
    sig = Table([[
        Paragraph("Date", ParagraphStyle("_s1", parent=S["_BodySm"], alignment=TA_CENTER)),
        Paragraph("Cachet et signature du praticien", ParagraphStyle("_s2", parent=S["_BodySm"], alignment=TA_CENTER)),
    ]], colWidths=[85 * mm, 86 * mm])
    sig.setStyle(TableStyle([("LINEABOVE", (0, 0), (0, 0), 0.7, GRAY), ("LINEABOVE", (1, 0), (1, 0), 0.7, GRAY), ("TOPPADDING", (0, 0), (-1, -1), 6)]))
    els.append(sig)

    doc.build(els, onFirstPage=_page, onLaterPages=_page)
    out = buf.getvalue()
    return _stamp_on_template(out, template_path) if use_tpl else out


def generate_devis_pdf(
    devis: dict, items: list,
    doctor_name: str = "", specialty: str = "", template_path: Optional[str] = None,
    address: Optional[str] = None, phone: Optional[str] = None,
) -> bytes:
    """Devis / plan de traitement chiffré imprimable (item 21)."""
    use_tpl = _has_template(template_path)
    buf = io.BytesIO()
    doc = _doc_for(buf, template_path)
    S = _styles()

    def _page(canv, d):
        if use_tpl:
            return
        _draw_footer(canv, d)

    els = _masthead(
        S, "Devis — plan de traitement",
        doctor_name=doctor_name or None, specialty=specialty or None,
        address=address, phone=phone, use_tpl=use_tpl,
        subtitle=f"N° {devis.get('devis_number') or '—'}",
    )

    date_str = devis.get("devis_date") or ""
    meta = Table([[f"Patient : {devis.get('patient_name') or '—'}", f"Date : {date_str}"]], colWidths=[105 * mm, 66 * mm])
    meta.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10), ("TEXTCOLOR", (0, 0), (-1, -1), GRAY),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    els.append(meta)
    if devis.get("valid_until"):
        els.append(Paragraph(f"Valable jusqu'au {devis.get('valid_until')}", ParagraphStyle("_dVal", parent=S["_BodySm"], textColor=GRAY, spaceBefore=2)))
    els.append(Spacer(1, 10))

    tbl, total = _amount_items_table(S, items)
    els.append(tbl)

    if devis.get("notes"):
        els.append(Spacer(1, 10))
        els.append(Paragraph(f"<b>Notes :</b> {devis.get('notes')}", S["_BodySm"]))

    els.append(Spacer(1, 26))
    els.append(Paragraph("Bon pour accord (le patient)", ParagraphStyle("_dBon", parent=S["_BodySm"], fontName="Helvetica-Bold")))
    els.append(Spacer(1, 24))
    sig = Table([[
        Paragraph("Date et signature du patient", ParagraphStyle("_ds1", parent=S["_BodySm"], alignment=TA_CENTER)),
        Paragraph("Cachet et signature du praticien", ParagraphStyle("_ds2", parent=S["_BodySm"], alignment=TA_CENTER)),
    ]], colWidths=[85 * mm, 86 * mm])
    sig.setStyle(TableStyle([("LINEABOVE", (0, 0), (0, 0), 0.7, GRAY), ("LINEABOVE", (1, 0), (1, 0), 0.7, GRAY), ("TOPPADDING", (0, 0), (-1, -1), 6)]))
    els.append(sig)

    doc.build(els, onFirstPage=_page, onLaterPages=_page)
    out = buf.getvalue()
    return _stamp_on_template(out, template_path) if use_tpl else out
