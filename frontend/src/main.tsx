import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";
import "./fonts/fonts.css";
import { App } from "./App.tsx";
import { followAccessibility } from "./lib/accessibilitySwitch.ts";
import { watchInstall } from "./lib/installOffer.ts";

// The browser's install prompt can come before the first render: held for the install offer (P4).
watchInstall(window);

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root");
// Before the first render, so the page never shows its plain borders and then the strong ones.
followAccessibility(document.documentElement);
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
