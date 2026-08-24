"""Envoi d'e-mails sortants (SMTP).

Usage actuel : le lien magique de modification du mot de passe demandé depuis
« Mon compte ». Le module est volontairement générique pour servir aux prochains
besoins (notifications, envoi d'un document au patient…).

Règles importantes :
- Si le SMTP n'est pas configuré (`config.email_configured()` faux), le service
  tourne en **dry-run** : il journalise le message et ne se connecte à rien.
  L'application fonctionne donc en local et sur la VM AVANT d'avoir un compte
  SMTP, sans jamais casser la fonctionnalité appelante.
- `smtplib` est **bloquant** : l'envoi part dans un thread (`asyncio.to_thread`)
  pour ne pas figer la boucle d'événements pendant la poignée de main TLS.
- Aucune exception ne remonte : l'appelant reçoit un dictionnaire de résultat.
  Un serveur de messagerie indisponible ne doit pas produire une erreur 500.
"""
import asyncio
import smtplib
import traceback
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import config


def _send_sync(msg: EmailMessage) -> None:
    """Connexion SMTP bloquante. Lève en cas d'échec (rattrapé par send_email)."""
    if config.SMTP_SECURITY == "ssl":
        server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT)
    else:
        server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT)
    try:
        server.ehlo()
        if config.SMTP_SECURITY == "starttls":
            server.starttls()
            server.ehlo()
        # Beaucoup de serveurs n'acceptent l'authentification qu'après TLS :
        # elle vient donc toujours après la négociation ci-dessus.
        if config.SMTP_USER:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass


async def send_email(to: str, subject: str, text_body: str, html_body: str = None) -> dict:
    """Envoie un e-mail. Ne lève jamais.

    Renvoie {'sent': bool, 'dry_run': bool, 'error': str | None}.
    - dry_run=True  : SMTP non configuré, rien n'a été envoyé (message journalisé).
    - sent=False et dry_run=False : tentative réelle échouée, `error` explique.
    """
    to = (to or "").strip()
    if not to:
        return {"sent": False, "dry_run": False, "error": "Adresse destinataire vide"}

    if not config.email_configured():
        print(
            "[email:dry-run] SMTP non configuré — message NON envoyé.\n"
            f"  À       : {to}\n"
            f"  Objet   : {subject}\n"
            f"  Corps   :\n{text_body}"
        )
        return {"sent": False, "dry_run": True, "error": None}

    msg = EmailMessage()
    msg["From"] = formataddr((config.SMTP_FROM_NAME, config.SMTP_FROM))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    # Un lien de sécurité ne doit pas être suivi par les robots anti-hameçonnage
    # de certains fournisseurs, qui consommeraient le jeton à usage unique.
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Auto-Response-Suppress"] = "All"
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        await asyncio.to_thread(_send_sync, msg)
        print(f"[email] envoyé à {to} — « {subject} »")
        return {"sent": True, "dry_run": False, "error": None}
    except Exception as exc:
        traceback.print_exc()
        return {"sent": False, "dry_run": False, "error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------- #
# Lien magique : modification du mot de passe
# --------------------------------------------------------------------------- #
def _escape(value: str) -> str:
    return (
        (value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


async def send_password_link(to: str, first_name: str, link: str, hours: int = 1) -> dict:
    """E-mail contenant le lien à usage unique de changement de mot de passe."""
    hello = f"Bonjour {first_name}," if first_name else "Bonjour,"
    validite = "1 heure" if hours == 1 else f"{hours} heures"
    text = (
        f"{hello}\n\n"
        "Vous avez demandé à modifier le mot de passe de votre compte Doctivo.\n"
        "Ouvrez le lien ci-dessous pour choisir un nouveau mot de passe :\n\n"
        f"{link}\n\n"
        f"Ce lien est valable {validite} et ne peut servir qu'une seule fois.\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message : "
        "votre mot de passe actuel reste inchangé.\n\n"
        "— Doctivo"
    )
    safe_link = _escape(link)
    html = f"""<!DOCTYPE html>
<html lang="fr"><body style="margin:0;padding:24px;background:#f1f5f9;font-family:Segoe UI,Arial,sans-serif;color:#0f172a;">
  <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:14px;padding:28px;">
    <h1 style="margin:0 0 6px;font-size:19px;">Modification de votre mot de passe</h1>
    <p style="margin:0 0 18px;font-size:14px;color:#475569;">{_escape(hello)}</p>
    <p style="margin:0 0 22px;font-size:14px;line-height:1.55;">
      Vous avez demandé à modifier le mot de passe de votre compte Doctivo.
      Cliquez sur le bouton ci-dessous pour en choisir un nouveau.
    </p>
    <p style="margin:0 0 22px;">
      <a href="{safe_link}" style="display:inline-block;background:#1b7ceb;color:#fff;text-decoration:none;
         padding:12px 22px;border-radius:10px;font-weight:600;font-size:14px;">Choisir un nouveau mot de passe</a>
    </p>
    <p style="margin:0 0 18px;font-size:13px;color:#475569;">
      Ce lien est valable <strong>{validite}</strong> et ne peut servir qu'une seule fois.
      S'il ne fonctionne pas, copiez cette adresse dans votre navigateur :<br>
      <span style="word-break:break-all;color:#1b7ceb;">{safe_link}</span>
    </p>
    <p style="margin:0;font-size:12px;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:14px;">
      Si vous n'êtes pas à l'origine de cette demande, ignorez ce message :
      votre mot de passe actuel reste inchangé.
    </p>
  </div>
</body></html>"""
    return await send_email(to, "Doctivo — modification de votre mot de passe", text, html)
