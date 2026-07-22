/* Radio IA — poste de travail.
 *
 * L'inférence tourne DANS LE NAVIGATEUR (detect.js / onnxruntime-web), comme la
 * Céphalométrie : la VM ne sert que des fichiers statiques. Ce script :
 *  - lance l'analyse côté client et affiche les boîtes sur le cliché (placées en %
 *    depuis les coordonnées normalisées `nbox`, alignées quelle que soit la taille) ;
 *  - laisse le praticien écarter un faux positif, corriger le n° de dent, et
 *    AJOUTER une détection à la main (tracé d'un cadre sur l'image) ;
 *  - enregistre l'état (via /save) et édite le rapport PDF.
 */
import { detectPathologies, modelAvailable } from "./detect.js";

(function () {
    "use strict";

    var el = document.getElementById("radio-data");
    if (!el) return;
    var state;
    try { state = JSON.parse(el.textContent).case; } catch (e) { return; }
    state.detections = state.detections || [];

    var caseId = state.id;
    var stage = document.getElementById("radio-stage");
    var overlay = document.getElementById("radio-overlay");
    var list = document.getElementById("radio-findings-list");
    var empty = document.getElementById("radio-empty");
    var notesEl = document.getElementById("radio-notes");
    var analyseBtn = document.getElementById("radio-analyse-btn");
    var analyseLabel = document.getElementById("radio-analyse-label");
    var saveBtn = document.getElementById("radio-save-btn");
    var pdfBtn = document.getElementById("radio-pdf-btn");
    var showBoxes = document.getElementById("radio-show-boxes");
    var addBtn = document.getElementById("radio-add-btn");
    var addClass = document.getElementById("radio-add-class");

    // Classes DentalXrayAI (mêmes libellés/couleurs FR que le serveur).
    var CLASS_META = {
        "Caries": { label: "Carie", color: "#f59e0b" },
        "Deep Caries": { label: "Carie profonde", color: "#ef4444" },
        "Impacted": { label: "Dent incluse", color: "#6366f1" },
        "Periapical Lesion": { label: "Lésion périapicale", color: "#10b981" }
    };

    // Estimation géométrique du n° FDI (miroir de radio_ai.estimate_fdi).
    function estimateFdi(cx, cy) {
        var upper = cy < 0.5, pos, quadrant;
        if (cx < 0.5) { quadrant = upper ? 1 : 4; pos = (0.5 - cx) / 0.5; }
        else { quadrant = upper ? 2 : 3; pos = (cx - 0.5) / 0.5; }
        var t = Math.max(1, Math.min(8, Math.round(pos * 7) + 1));
        return quadrant * 10 + t;
    }

    function pct(v) { return (v * 100) + "%"; }
    function nextId() {
        return state.detections.reduce(function (m, d) { return Math.max(m, d.id + 1); }, 0);
    }

    // Rendu des boîtes sur le cliché (séparé de la liste pour ne pas perdre le
    // focus du champ « Dent » quand on corrige un numéro).
    function renderBoxes() {
        overlay.innerHTML = "";
        state.detections.forEach(function (d) {
            var nb = d.nbox || [0, 0, 0, 0];
            var box = document.createElement("div");
            box.className = "radio-box" + (d.dismissed ? " dismissed" : "") +
                (d.source === "manual" ? " manual" : "");
            box.style.setProperty("--box-color", d.color || "#0ea5e9");
            box.style.left = pct(nb[0]);
            box.style.top = pct(nb[1]);
            box.style.width = pct(nb[2] - nb[0]);
            box.style.height = pct(nb[3] - nb[1]);
            var tag = document.createElement("span");
            tag.className = "radio-box-tag";
            tag.textContent = (d.label || d.cls || "?") +
                (d.tooth ? " · " + d.tooth : "") +
                (typeof d.conf === "number" ? " " + Math.round(d.conf * 100) + "%" : "");
            box.appendChild(tag);
            overlay.appendChild(box);
        });
    }

    function render() {
        renderBoxes();

        // --- Liste latérale ---
        list.innerHTML = "";
        if (!state.detections.length) {
            empty.style.display = "";
            empty.textContent = state.status === "analyse"
                ? "Aucune détection. Lancez l'analyse ou ajoutez-en une à la main."
                : "Aucune analyse pour l'instant. Lancez la détection IA ou ajoutez une détection.";
            list.style.display = "none";
            return;
        }
        empty.style.display = "none";
        list.style.display = "";
        state.detections.forEach(function (d) {
            var li = document.createElement("li");
            li.className = "radio-finding" + (d.dismissed ? " is-dismissed" : "");

            var sw = document.createElement("span");
            sw.className = "radio-swatch";
            sw.style.background = d.color || "#0ea5e9";

            var main = document.createElement("div");
            main.className = "radio-finding-main";
            var lab = document.createElement("div");
            lab.className = "radio-finding-label";
            lab.textContent = d.label || d.cls || "Anomalie";
            if (d.source === "manual") {
                var badge = document.createElement("span");
                badge.className = "radio-manual-badge";
                badge.textContent = "manuel";
                lab.appendChild(document.createTextNode(" "));
                lab.appendChild(badge);
            }
            var conf = document.createElement("div");
            conf.className = "radio-finding-conf";
            conf.textContent = typeof d.conf === "number"
                ? "Confiance " + Math.round(d.conf * 100) + " %"
                : (d.source === "manual" ? "Ajout manuel" : "");
            main.appendChild(lab);
            main.appendChild(conf);

            // Numéro de dent (FDI) : estimé, corrigeable ici.
            var toothWrap = document.createElement("label");
            toothWrap.className = "radio-tooth";
            toothWrap.title = "Numéro de dent (FDI)" + (d.tooth_estimated ? " — estimé, à confirmer" : "");
            toothWrap.appendChild(document.createTextNode("Dent"));
            var toothIn = document.createElement("input");
            toothIn.type = "number";
            toothIn.min = "11"; toothIn.max = "48";
            toothIn.value = (d.tooth != null ? d.tooth : "");
            if (d.tooth_estimated) toothIn.classList.add("is-estimated");
            toothIn.addEventListener("input", function () {
                var v = parseInt(toothIn.value, 10);
                d.tooth = isNaN(v) ? null : v;
                d.tooth_estimated = false;
                toothIn.classList.remove("is-estimated");
                renderBoxes();
            });
            toothWrap.appendChild(toothIn);

            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "radio-dismiss";
            if (d.source === "manual") {
                // Une détection ajoutée à la main se supprime vraiment.
                btn.textContent = "Supprimer";
                btn.addEventListener("click", function () {
                    state.detections = state.detections.filter(function (x) { return x.id !== d.id; });
                    render();
                });
            } else {
                btn.textContent = d.dismissed ? "Rétablir" : "Écarter";
                btn.addEventListener("click", function () {
                    d.dismissed = !d.dismissed;
                    render();
                });
            }

            li.appendChild(sw);
            li.appendChild(main);
            li.appendChild(toothWrap);
            li.appendChild(btn);
            list.appendChild(li);
        });
    }

    function save() {
        return fetch("/radio-ia/" + caseId + "/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ detections: state.detections, notes: notesEl.value })
        }).then(function (r) {
            if (!r.ok) throw new Error("save");
            return r.json();
        }).then(function (res) {
            // Le serveur renvoie la liste validée (ids réattribués) : on s'aligne.
            if (res && res.detections) { state.detections = res.detections; render(); }
            return res;
        });
    }

    // --- Détection IA (dans le navigateur, via detect.js / onnxruntime-web) ---
    // Récupère un ImageBitmap du cliché same-origin déjà affiché.
    function imageBitmap() {
        var img = document.getElementById("radio-image");
        if (img && img.complete && img.naturalWidth) return createImageBitmap(img);
        return new Promise(function (resolve, reject) {
            img.addEventListener("load", function () { createImageBitmap(img).then(resolve, reject); }, { once: true });
            img.addEventListener("error", function () { reject(new Error("Cliché illisible.")); }, { once: true });
        });
    }

    if (analyseBtn) {
        var defaultAnalyseLabel = "Lancer la détection IA";
        analyseBtn.addEventListener("click", function () {
            analyseBtn.disabled = true;
            var setLbl = function (t) { analyseLabel.textContent = t; };
            setLbl("Préparation…");
            imageBitmap().then(function (bmp) {
                return detectPathologies(bmp, bmp.width, bmp.height, setLbl);
            }).then(function (res) {
                // On conserve les ajouts manuels, on remplace les détections IA.
                var manual = state.detections.filter(function (d) { return d.source === "manual"; });
                state.detections = (res.detections || []).concat(manual);
                state.detections.forEach(function (d, i) { d.id = i; });
                state.status = "analyse";
                render();
                var n = (res.detections || []).length;
                if (window.showToast) {
                    window.showToast(n ? (n + " détection" + (n > 1 ? "s" : "")) : "Aucune pathologie détectée", n ? "info" : "success");
                }
                return save();  // persiste tout de suite (parité avec l'ancien serveur)
            }).catch(function (e) {
                if (window.showToast) window.showToast((e && e.message) || "Analyse impossible", "error");
            }).finally(function () {
                analyseBtn.disabled = false;
                setLbl(defaultAnalyseLabel);
            });
        });

        // Le bouton n'a de sens que si le modèle est déployé (fichier .onnx servi).
        modelAvailable().then(function (ok) {
            if (!ok) {
                analyseBtn.disabled = true;
                analyseBtn.title = "Modèle IA non déployé sur ce serveur.";
                analyseLabel.textContent = "Modèle IA indisponible";
            }
        });
    }

    // --- Enregistrer ---
    if (saveBtn) {
        saveBtn.addEventListener("click", function () {
            saveBtn.disabled = true;
            save().then(function () {
                if (window.showToast) window.showToast("Analyse enregistrée", "success");
            }).catch(function () {
                if (window.showToast) window.showToast("Enregistrement impossible", "error");
            }).finally(function () { saveBtn.disabled = false; });
        });
    }

    // --- Rapport PDF (enregistre l'état courant, puis ouvre le PDF) ---
    if (pdfBtn) {
        pdfBtn.addEventListener("click", function () {
            pdfBtn.disabled = true;
            save().catch(function () { /* on édite quand même le rapport */ })
                .then(function () {
                    var url = "/radio-ia/" + caseId + "/rapport.pdf";
                    if (window.printPdf) window.printPdf(url);
                    else window.open(url, "_blank");
                }).finally(function () { pdfBtn.disabled = false; });
        });
    }

    // --- Afficher / masquer les repères ---
    if (showBoxes) {
        showBoxes.addEventListener("change", function () {
            overlay.classList.toggle("hidden", !showBoxes.checked);
        });
    }

    // --- Ajout d'une détection à la main (tracé d'un cadre) ---
    var addMode = false, drawing = null, liveBox = null;

    function setAddMode(on) {
        addMode = on;
        stage.classList.toggle("is-drawing", on);
        if (addBtn) {
            addBtn.classList.toggle("btn-primary", on);
            addBtn.classList.toggle("btn-outline", !on);
            addBtn.textContent = on ? "Tracer sur l'image…" : "+ Ajouter une détection";
        }
        if (!on && liveBox) { liveBox.remove(); liveBox = null; drawing = null; }
        // Les repères doivent être visibles pour tracer.
        if (on && showBoxes && !showBoxes.checked) { showBoxes.checked = true; overlay.classList.remove("hidden"); }
    }

    function relPoint(e) {
        var r = stage.getBoundingClientRect();
        return {
            x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
            y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height))
        };
    }

    if (addBtn) {
        addBtn.addEventListener("click", function () { setAddMode(!addMode); });
    }

    stage.addEventListener("mousedown", function (e) {
        if (!addMode || e.button !== 0) return;
        e.preventDefault();
        var p = relPoint(e);
        drawing = { x0: p.x, y0: p.y };
        liveBox = document.createElement("div");
        liveBox.className = "radio-draw-box";
        var meta = CLASS_META[addClass.value] || { color: "#0ea5e9" };
        liveBox.style.setProperty("--box-color", meta.color);
        overlay.appendChild(liveBox);
    });

    window.addEventListener("mousemove", function (e) {
        if (!drawing || !liveBox) return;
        var p = relPoint(e);
        var x1 = Math.min(drawing.x0, p.x), y1 = Math.min(drawing.y0, p.y);
        var x2 = Math.max(drawing.x0, p.x), y2 = Math.max(drawing.y0, p.y);
        liveBox.style.left = pct(x1); liveBox.style.top = pct(y1);
        liveBox.style.width = pct(x2 - x1); liveBox.style.height = pct(y2 - y1);
        drawing.cur = { x1: x1, y1: y1, x2: x2, y2: y2 };
    });

    window.addEventListener("mouseup", function () {
        if (!drawing) return;
        var box = drawing.cur;
        if (liveBox) { liveBox.remove(); liveBox = null; }
        drawing = null;
        if (!box || (box.x2 - box.x1) < 0.01 || (box.y2 - box.y1) < 0.01) return;  // trop petit
        var clsName = addClass.value;
        var meta = CLASS_META[clsName] || { label: clsName, color: "#0ea5e9" };
        var cx = (box.x1 + box.x2) / 2, cy = (box.y1 + box.y2) / 2;
        state.detections.push({
            id: nextId(),
            cls: clsName,
            label: meta.label,
            color: meta.color,
            conf: null,
            nbox: [box.x1, box.y1, box.x2, box.y2],
            tooth: estimateFdi(cx, cy),
            tooth_estimated: true,
            dismissed: false,
            source: "manual"
        });
        state.status = "analyse";
        setAddMode(false);
        render();
        if (window.showToast) window.showToast("Détection ajoutée — pensez à enregistrer", "info");
    });

    render();
})();
