from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import io


PRIMARY = HexColor("#2563eb")
GRAY = HexColor("#6b7280")
DARK = HexColor("#1f2937")


def _get_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "DocTitle", parent=styles["Heading1"], fontSize=18, textColor=PRIMARY, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "DocSubtitle", parent=styles["Normal"], fontSize=10, textColor=GRAY, spaceAfter=12,
    ))
    styles.add(ParagraphStyle(
        "SectionHead", parent=styles["Heading2"], fontSize=12, textColor=DARK,
        spaceBefore=14, spaceAfter=6, borderWidth=0,
    ))
    styles.add(ParagraphStyle(
        "MedName", parent=styles["Normal"], fontSize=11, textColor=DARK, fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        "MedDetail", parent=styles["Normal"], fontSize=10, textColor=GRAY, leftIndent=12,
    ))
    return styles


def generate_prescription_pdf(prescription: dict, items: list) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=25 * mm, rightMargin=25 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm)
    styles = _get_styles()
    elements = []

    # Header
    elements.append(Paragraph("ORDONNANCE MÉDICALE", styles["DocTitle"]))
    elements.append(Paragraph(
        f"Dr. {prescription['d_first']} {prescription['d_last']}"
        f"{' — ' + prescription['specialty'] if prescription.get('specialty') else ''}",
        styles["DocSubtitle"],
    ))
    elements.append(Spacer(1, 6))

    # Patient info
    elements.append(Paragraph("Patient", styles["SectionHead"]))
    patient_info = f"{prescription['p_first']} {prescription['p_last']}"
    if prescription.get("date_of_birth"):
        patient_info += f"  —  Né(e) le {prescription['date_of_birth']}"
    if prescription.get("social_security_number"):
        patient_info += f"  —  N° {prescription['social_security_number']}"
    elements.append(Paragraph(patient_info, styles["Normal"]))
    elements.append(Spacer(1, 6))

    # Date
    elements.append(Paragraph(f"Date : {prescription['prescription_date']}", styles["Normal"]))
    elements.append(Spacer(1, 10))

    # Medications
    elements.append(Paragraph("Prescription", styles["SectionHead"]))
    for i, item in enumerate(items, 1):
        elements.append(Paragraph(f"{i}. {item['medication_name']}", styles["MedName"]))
        details = f"Posologie : {item['dosage']}  |  Fréquence : {item['frequency']}"
        if item.get("duration"):
            details += f"  |  Durée : {item['duration']}"
        if item.get("quantity"):
            details += f"  |  Qté : {item['quantity']}"
        elements.append(Paragraph(details, styles["MedDetail"]))
        if item.get("instructions"):
            elements.append(Paragraph(f"→ {item['instructions']}", styles["MedDetail"]))
        elements.append(Spacer(1, 6))

    # Notes
    if prescription.get("notes"):
        elements.append(Spacer(1, 6))
        elements.append(Paragraph("Notes", styles["SectionHead"]))
        elements.append(Paragraph(prescription["notes"], styles["Normal"]))

    # Renewable
    if prescription.get("is_renewable"):
        elements.append(Spacer(1, 10))
        elements.append(Paragraph("✓ Ordonnance renouvelable", styles["Normal"]))

    # Signature area
    elements.append(Spacer(1, 30))
    elements.append(Paragraph(
        f"Signature : Dr. {prescription['d_first']} {prescription['d_last']}",
        ParagraphStyle("Sig", parent=styles["Normal"], alignment=2, fontSize=10, textColor=GRAY),
    ))

    doc.build(elements)
    return buf.getvalue()


def generate_consultation_pdf(consultation: dict, vitals: dict | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    styles = _get_styles()
    elements = []

    elements.append(Paragraph("COMPTE RENDU DE CONSULTATION", styles["DocTitle"]))
    elements.append(
        Paragraph(
            f"Date : {consultation.get('consultation_date', '')[:10]}  —  "
            f"Dr. {consultation.get('doctor_name', '')}",
            styles["DocSubtitle"],
        )
    )

    elements.append(Paragraph("Patient", styles["SectionHead"]))
    patient_line = consultation.get("patient_name", "Patient inconnu")
    if consultation.get("date_of_birth"):
        patient_line += f"  —  Né(e) le {consultation['date_of_birth']}"
    if consultation.get("gender"):
        patient_line += f"  —  Sexe : {consultation['gender']}"
    elements.append(Paragraph(patient_line, styles["Normal"]))

    if vitals:
        elements.append(Paragraph("Constantes vitales", styles["SectionHead"]))
        rows = [["Mesure", "Valeur"]]
        if vitals.get("weight") is not None:
            rows.append(["Poids", f"{vitals['weight']} kg"])
        if vitals.get("height") is not None:
            rows.append(["Taille", f"{vitals['height']} cm"])
        if vitals.get("blood_pressure_sys") is not None:
            bp = f"{vitals['blood_pressure_sys']}/{vitals.get('blood_pressure_dia', '')}".strip("/")
            rows.append(["Tension", f"{bp} mmHg"])
        if vitals.get("heart_rate") is not None:
            rows.append(["Fréquence cardiaque", f"{vitals['heart_rate']} bpm"])
        if vitals.get("temperature") is not None:
            rows.append(["Température", f"{vitals['temperature']} °C"])
        if vitals.get("spo2") is not None:
            rows.append(["SpO2", f"{vitals['spo2']} %"])

        if len(rows) > 1:
            table = Table(rows, colWidths=[65 * mm, 95 * mm])
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#eef5ff")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), DARK),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#d1d9e6")),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            elements.append(table)

    def add_text_section(title: str, value: str | None):
        elements.append(Paragraph(title, styles["SectionHead"]))
        elements.append(Paragraph(value or "Non renseigné", styles["Normal"]))

    add_text_section("Motif", consultation.get("reason"))
    add_text_section("Symptômes", consultation.get("symptoms"))
    add_text_section("Examen clinique", consultation.get("clinical_exam"))
    add_text_section("Diagnostic", consultation.get("diagnosis"))
    add_text_section("Plan de traitement", consultation.get("treatment_plan"))

    if consultation.get("notes"):
        add_text_section("Notes", consultation.get("notes"))

    elements.append(Spacer(1, 24))
    elements.append(
        Paragraph(
            f"Signature : Dr. {consultation.get('doctor_name', '')}",
            ParagraphStyle("SigC", parent=styles["Normal"], alignment=2, fontSize=10, textColor=GRAY),
        )
    )

    doc.build(elements)
    return buf.getvalue()
