"""Exporte les poids DentalXrayAI (best.pt) en ONNX pour l'inférence NAVIGATEUR.

Le module Radio IA exécute désormais le modèle dans le navigateur via
onnxruntime-web (comme la Céphalométrie) : la VM de production n'a que ~956 Mo
de RAM et ne peut pas faire tourner PyTorch. Ce script est donc à lancer **en
local** (là où Ultralytics + torch sont installés) pour produire le fichier
statique servi au navigateur.

    py scripts/export_onnx.py

Sortie : `medfollow/static/js/radio/model/dentalxray.onnx` (YOLOv8n fp32, 640×640).
On garde le fp32 (pas de quantification) : tous les ops restent standards et donc
compatibles avec le backend WASM d'onnxruntime-web (la quantification dynamique
produit des ConvInteger non supportés en WASM).
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import RADIO_AI_WEIGHTS  # noqa: E402

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEST = os.path.join(BASE_DIR, "static", "js", "radio", "model", "dentalxray.onnx")
IMGSZ = 640


def main() -> int:
    if not os.path.exists(RADIO_AI_WEIGHTS):
        print(f"✗ Poids introuvables : {RADIO_AI_WEIGHTS}\n"
              "  Lancez d'abord `py scripts/download_dentalxray.py`.")
        return 1
    try:
        from ultralytics import YOLO
    except ImportError:
        print("✗ Ultralytics n'est pas installé.\n"
              "  Installez-le en local : py -m pip install -r requirements-radio-ai.txt")
        return 1

    print(f"Export ONNX du modèle {RADIO_AI_WEIGHTS} (imgsz={IMGSZ}, fp32)…")
    model = YOLO(RADIO_AI_WEIGHTS)
    print("Classes du modèle :", model.names)
    out_path = model.export(format="onnx", imgsz=IMGSZ, opset=12, simplify=True, dynamic=False)

    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    shutil.copyfile(out_path, DEST)
    size_mb = os.path.getsize(DEST) / (1024 * 1024)
    print(f"✓ ONNX écrit : {DEST} ({size_mb:.1f} Mo)")

    # Vérification de la forme de sortie (attendu [1, 4+nc, 8400]).
    try:
        import onnxruntime as ort
        sess = ort.InferenceSession(DEST, providers=["CPUExecutionProvider"])
        inp = sess.get_inputs()[0]
        out = sess.get_outputs()[0]
        print(f"  entrée : {inp.name} {inp.shape} | sortie : {out.name} {out.shape}")
    except Exception as e:
        print(f"  (vérification onnxruntime ignorée : {e})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
