import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Odontogram } from "react-odontogram";
import "react-odontogram/style.css";

const TOOTH_TYPE_FR = {
  "Central Incisor": "Incisive centrale",
  "Lateral Incisor": "Incisive laterale",
  Canine: "Canine",
  "First Premolar": "1ere premolaire",
  "Second Premolar": "2eme premolaire",
  "First Molar": "1ere molaire",
  "Second Molar": "2eme molaire",
  "Third Molar": "3eme molaire (sagesse)",
};

function toDefaultSelected(toothNumber) {
  if (!toothNumber) return [];
  return [`teeth-${toothNumber}`];
}

function toFrenchToothType(type) {
  if (!type) return "Dent";
  return TOOTH_TYPE_FR[type] || type;
}

export function mountOdontogram(rootElement, options = {}) {
  const {
    initialConditions = [],
    initialSelectedTooth = null,
    onSelect = () => {},
    layout = "circle",
  } = options;

  const root = createRoot(rootElement);
  const bridge = {
    updateConditions: () => {},
    updateSelectedTooth: () => {},
    updateLayout: () => {},
    unmount: () => root.unmount(),
  };

  function App() {
    const [conditions, setConditions] = useState(
      Array.isArray(initialConditions) ? initialConditions : [],
    );
    const [selectedTooth, setSelectedTooth] = useState(initialSelectedTooth);
    const [currentLayout, setCurrentLayout] = useState(
      layout === "square" ? "square" : "circle",
    );
    const [selectionVersion, setSelectionVersion] = useState(0);
    const onSelectRef = useRef(onSelect);

    useEffect(() => {
      onSelectRef.current = onSelect;
    }, [onSelect]);

    useEffect(() => {
      bridge.updateConditions = (nextConditions) => {
        setConditions(Array.isArray(nextConditions) ? nextConditions : []);
      };
      bridge.updateSelectedTooth = (toothNumber) => {
        setSelectedTooth(toothNumber || null);
        // Remount Odontogram to re-apply defaultSelected when selection comes from outside React.
        setSelectionVersion((v) => v + 1);
      };
      bridge.updateLayout = (nextLayout) => {
        setCurrentLayout(nextLayout === "square" ? "square" : "circle");
      };

      return () => {
        bridge.updateConditions = () => {};
        bridge.updateSelectedTooth = () => {};
        bridge.updateLayout = () => {};
      };
    }, []);

    const handleChange = useCallback((teeth) => {
      if (!Array.isArray(teeth) || teeth.length === 0) return;
      const lastTooth = teeth[teeth.length - 1];
      const fdiRaw =
        lastTooth?.notations?.fdi ||
        String(lastTooth?.id || "").replace("teeth-", "");
      const fdiTooth = Number.parseInt(fdiRaw, 10);

      if (Number.isFinite(fdiTooth)) {
        setSelectedTooth(fdiTooth);
        onSelectRef.current(fdiTooth);
      }
    }, []);

    return (
      <Odontogram
        key={`odontogram-${selectionVersion}`}
        onChange={handleChange}
        teethConditions={conditions}
        notation="FDI"
        theme="light"
        layout={currentLayout}
        singleSelect={true}
        showTooltip={true}
        tooltip={{
          placement: "top",
          content: (payload) => {
            if (!payload) return null;
            return (
              <div style={{ minWidth: 180 }}>
                <div>
                  <strong>Dent (FDI): {payload?.notations?.fdi || "-"}</strong>
                </div>
                <div>Type: {toFrenchToothType(payload?.type)}</div>
                <div>
                  Notation universelle: {payload?.notations?.universal || "-"}
                </div>
                <div>Notation Palmer: {payload?.notations?.palmer || "-"}</div>
              </div>
            );
          },
        }}
        defaultSelected={toDefaultSelected(selectedTooth)}
      />
    );
  }

  root.render(<App />);
  return bridge;
}
