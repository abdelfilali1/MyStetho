"""Télécharge les poids du modèle DentalXrayAI (best.pt) pour le module Radio IA.

Le fichier est enregistré à l'emplacement attendu par la configuration
(`config.RADIO_AI_WEIGHTS`, par défaut `medfollow/models/dentalxray/best.pt`).

    py scripts/download_dentalxray.py

Source par défaut : SubGlitch1/DentalXrayAI sur Hugging Face
(surchargeable via la variable d'environnement MEDFOLLOW_RADIO_AI_MODEL_URL).
Si le téléchargement automatique échoue (réseau, URL du dépôt modifiée), déposez
manuellement le fichier best.pt à l'emplacement indiqué à la fin du message
d'erreur : le modèle YOLOv8 DentalXrayAI se récupère sur la page Hugging Face
ou GitHub du projet.
"""
import os
import sys
import urllib.request

# La console Windows (cp1252) ne sait pas encoder ✓/✗ : on force un flux tolérant.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Permet d'exécuter le script depuis n'importe quel dossier.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import RADIO_AI_MODEL_URL, RADIO_AI_WEIGHTS  # noqa: E402


def main() -> int:
    dest = RADIO_AI_WEIGHTS
    url = RADIO_AI_MODEL_URL
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"✓ Les poids sont déjà présents : {dest}")
        return 0

    print(f"Téléchargement du modèle DentalXrayAI…\n  depuis : {url}\n  vers   : {dest}")
    tmp = dest + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Doctivo-RadioIA/1.0"})
        with urllib.request.urlopen(req) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            read = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                read += len(chunk)
                if total:
                    pct = read * 100 // total
                    print(f"\r  {pct:3d} %  ({read // 1024} Ko / {total // 1024} Ko)", end="", flush=True)
        print()
        # Garde-fou : une page d'erreur HTML renvoyée à la place du binaire.
        if os.path.getsize(tmp) < 1024:
            raise RuntimeError("fichier reçu trop petit — l'URL ne pointe probablement pas vers best.pt")
        os.replace(tmp, dest)
        print(f"✓ Modèle enregistré : {dest}")
        return 0
    except Exception as e:  # noqa: BLE001
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        print(f"\n✗ Échec du téléchargement automatique : {e}\n")
        print("Récupérez best.pt manuellement (page Hugging Face / GitHub de "
              "SubGlitch1/DentalXrayAI), puis placez-le ici :")
        print(f"  {dest}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
