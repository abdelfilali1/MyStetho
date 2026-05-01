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


def generate_patient_brochure_pdf(patient: dict, history: list, appointments: list, prescriptions: list) -> bytes:
    """Generate a patient information brochure PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm)
    styles = _get_styles()
    elements = []

    elements.append(Paragraph("FICHE PATIENT", styles["DocTitle"]))
    full_name = f"{patient.get('last_name', '').upper()} {patient.get('first_name', '')}"
    elements.append(Paragraph(full_name, styles["DocSubtitle"]))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Informations personnelles", styles["SectionHead"]))
    identity_rows = []
    if patient.get("date_of_birth"):
        identity_rows.append(["Date de naissance", patient["date_of_birth"]])
    if patient.get("gender"):
        identity_rows.append(["Sexe", patient["gender"]])
    if patient.get("blood_type"):
        identity_rows.append(["Groupe sanguin", patient["blood_type"]])
    if patient.get("phone"):
        identity_rows.append(["Téléphone", patient["phone"]])
    if patient.get("email"):
        identity_rows.append(["Email", patient["email"]])
    if patient.get("address"):
        addr = patient["address"]
        if patient.get("city"):
            addr += f", {patient['city']}"
        if patient.get("postal_code"):
            addr += f" {patient['postal_code']}"
        identity_rows.append(["Adresse", addr])
    if patient.get("social_security_number"):
        identity_rows.append(["N° Sécu", patient["social_security_number"]])
    if patient.get("insurance_name"):
        ins = patient["insurance_name"]
        if patient.get("insurance_number"):
            ins += f" — N° {patient['insurance_number']}"
        if patient.get("insurance_serial"):
            ins += f" — Série {patient['insurance_serial']}"
        identity_rows.append(["Mutuelle / Assurance", ins])

    if identity_rows:
        t = Table(identity_rows, colWidths=[60 * mm, 110 * mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), GRAY),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25, HexColor("#e5e7eb")),
        ]))
        elements.append(t)

    if history:
        elements.append(Paragraph("Antécédents médicaux", styles["SectionHead"]))
        for h in history:
            type_labels = {"medical": "Médical", "surgical": "Chirurgical",
                           "family": "Familial", "allergy": "Allergie"}
            label = type_labels.get(h.get("type", ""), "Médical")
            elements.append(Paragraph(f"<b>{label}</b> — {h.get('description', '')}", styles["Normal"]))
        elements.append(Spacer(1, 4))

    if appointments:
        elements.append(Paragraph("Prochains rendez-vous", styles["SectionHead"]))
        appt_rows = [["Date", "Motif", "Statut"]]
        for a in appointments[:5]:
            appt_rows.append([
                str(a.get("start_datetime", ""))[:16].replace("T", " "),
                a.get("title", ""),
                a.get("status", ""),
            ])
        t = Table(appt_rows, colWidths=[45 * mm, 95 * mm, 30 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#eef5ff")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.3, HexColor("#d1d9e6")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 4))

    if prescriptions:
        elements.append(Paragraph("Traitements en cours", styles["SectionHead"]))
        for rx in prescriptions[:3]:
            elements.append(Paragraph(
                f"Ordonnance du {str(rx.get('prescription_date', ''))[:10]}", styles["MedName"]
            ))
            for item in rx.get("items", []):
                elements.append(Paragraph(
                    f"• {item.get('medication_name', '')} — {item.get('dosage', '')} — {item.get('frequency', '')}",
                    styles["MedDetail"]
                ))
            elements.append(Spacer(1, 4))

    elements.append(Spacer(1, 20))
    from datetime import date as _date
    elements.append(Paragraph(
        f"Document généré le {_date.today().strftime('%d/%m/%Y')}",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, textColor=GRAY, alignment=1),
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
