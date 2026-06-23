from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
import io
import os
from typing import Optional
from datetime import date as _date


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

def _draw_page(canvas, doc, title, subtitle):
    """En-tête sobre N&B (utilisé uniquement SANS papier à en-tête).
    Pas de bande de couleur : titre noir + filet fin, style document officiel."""
    canvas.saveState()

    # Title (black bold, left)
    canvas.setFillColor(PRIMARY)
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(22 * mm, _PH - 16 * mm, title)

    # Subtitle (gray, right)
    canvas.setFillColor(GRAY)
    canvas.setFont("Helvetica", 9)
    canvas.drawRightString(_PW - 22 * mm, _PH - 16 * mm, subtitle)

    # Thin rule under the header
    canvas.setStrokeColor(PRIMARY)
    canvas.setLineWidth(1)
    canvas.line(22 * mm, _PH - 20 * mm, _PW - 22 * mm, _PH - 20 * mm)

    # Footer separator
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(22 * mm, 18 * mm, _PW - 22 * mm, 18 * mm)

    # Footer text
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

def generate_prescription_pdf(prescription: dict, items: list, template_path: Optional[str] = None) -> bytes:
    use_tpl = _has_template(template_path)
    buf = io.BytesIO()
    doc = _doc_for(buf, template_path)
    S = _styles()

    doctor_hdr = f"Dr. {prescription['d_first']} {prescription['d_last']}"
    if prescription.get("specialty"):
        doctor_hdr += f"  •  {prescription['specialty']}"

    def _page(canv, d):
        if use_tpl:
            return  # le papier à en-tête fournit l'en-tête / pied de page
        _draw_page(canv, d, "ORDONNANCE MÉDICALE", doctor_hdr)

    els = []

    # Patient box
    pname = f"{prescription['p_last'].upper()} {prescription['p_first']}"
    pdetails = []
    if prescription.get("date_of_birth"):
        pdetails.append(f"Né(e) le {prescription['date_of_birth']}")
    if prescription.get("social_security_number"):
        pdetails.append(f"N° CIN : {prescription['social_security_number']}")
    els.append(_patient_box(S, pname, "  •  ".join(pdetails) if pdetails else None))
    els.append(Spacer(1, 8))

    # Date + doctor line
    meta = Table(
        [[f"Date : {prescription['prescription_date']}", doctor_hdr]],
        colWidths=[90 * mm, 81 * mm],
    )
    meta.setStyle(TableStyle([
        ("FONTNAME",   (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR",  (0, 0), (-1, -1), GRAY),
        ("ALIGN",      (1, 0), (1, 0),   "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
    ]))
    els.append(meta)
    els.append(Spacer(1, 10))

    # Section: Prescription
    els.extend(_section("Prescription", S))
    els.append(Paragraph("<i>Rp/</i>", S["_Italic"]))
    els.append(Spacer(1, 6))

    for i, item in enumerate(items, 1):
        parts = [
            f"Posologie : <b>{item['dosage']}</b>",
            f"Fréquence : <b>{item['frequency']}</b>",
        ]
        if item.get("duration"):
            parts.append(f"Durée : <b>{item['duration']}</b>")
        if item.get("quantity"):
            parts.append(f"Qté : <b>{item['quantity']}</b>")

        block = [
            Paragraph(f"{i}.  {item['medication_name']}", S["_MedName"]),
            Paragraph("  •  ".join(parts), S["_MedDetail"]),
        ]
        if item.get("instructions"):
            block.append(Paragraph(f"→  {item['instructions']}", S["_MedDetail"]))
        block.append(Spacer(1, 6))
        els.append(KeepTogether(block))

    # Notes
    if prescription.get("notes"):
        els.append(Spacer(1, 4))
        els.extend(_section("Notes", S))
        els.append(Paragraph(prescription["notes"], S["_Italic"]))

    # Renewable badge
    if prescription.get("is_renewable"):
        els.append(Spacer(1, 10))
        badge = Table([["✓   Ordonnance renouvelable"]], colWidths=[171 * mm])
        badge.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), SUCCESS_BG),
            ("TEXTCOLOR",     (0, 0), (-1, -1), SUCCESS),
            ("FONTNAME",      (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 10),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
            ("BOX",           (0, 0), (-1, -1), 1, SUCCESS_BDR),
        ]))
        els.append(badge)

    # Signature
    els.append(Spacer(1, 36))
    els.append(_sig_block(f"{prescription['d_first']} {prescription['d_last']}"))

    doc.build(els, onFirstPage=_page, onLaterPages=_page)
    out = buf.getvalue()
    return _stamp_on_template(out, template_path) if use_tpl else out


# ═════════════════════════════════════════════════════════════
# FICHE PATIENT
# ═════════════════════════════════════════════════════════════

def generate_patient_brochure_pdf(
    patient: dict, history: list, appointments: list, prescriptions: list,
    template_path: Optional[str] = None,
) -> bytes:
    use_tpl = _has_template(template_path)
    buf = io.BytesIO()
    doc = _doc_for(buf, template_path)
    S = _styles()

    full_name = f"{patient.get('last_name', '').upper()} {patient.get('first_name', '')}"

    def _page(canv, d):
        if use_tpl:
            return
        _draw_page(canv, d, "FICHE PATIENT", full_name)

    els = []

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
        _draw_page(canv, d, "COMPTE RENDU DE CONSULTATION",
                   f"Dr. {doctor_name}  •  {doc_date}")

    els = []

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
) -> bytes:
    use_tpl = _has_template(template_path)
    buf = io.BytesIO()
    doc = _doc_for(buf, template_path)
    S = _styles()

    def _page(canv, d):
        # Titre rendu dans le contenu → pas de bande d'en-tête de l'app.
        return

    els = []

    # En-tête praticien (uniquement sans papier à en-tête — sinon fourni par le fond)
    if not use_tpl and doctor_name:
        els.append(Paragraph(doctor_name, ParagraphStyle(
            "_nDoc", parent=S["_Body"], alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=13)))
        if specialty:
            els.append(Paragraph(specialty, ParagraphStyle(
                "_nSpec", parent=S["_BodySm"], alignment=TA_CENTER)))
        els.append(Spacer(1, 12))

    # Titre + sous-titre (toujours visibles, y compris sur l'en-tête)
    els.append(Paragraph("NOTE D'HONORAIRES", ParagraphStyle(
        "_nTitle", parent=S["_Body"], alignment=TA_CENTER, fontName="Helvetica-Bold",
        fontSize=16, textColor=DARK, leading=20)))
    els.append(Paragraph("CNOPS / CNSS — Note d'honoraires", ParagraphStyle(
        "_nSub", parent=S["_BodySm"], alignment=TA_CENTER, spaceAfter=4)))
    els.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceBefore=4, spaceAfter=10))

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
