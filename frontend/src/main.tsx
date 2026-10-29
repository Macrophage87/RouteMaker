import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";
import "./fonts/fonts.css";
import { watchErrors } from "./lib/crashReport.ts";
import { watchInstall } from "./lib/installOffer.ts";
import { loadLanguage, markPageLanguage } from "./lib/i18n.ts";

// The page's uncaught errors, kept for the crash screen's error report (lib/crashReport.ts).
watchErrors(window);
// The browser's install prompt can come before the first render: held for the install offer (P4).
watchInstall(window);

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root");
// The language in force (lib/i18n.ts), for screen readers and the browser, and its direction.
markPageLanguage(document);
// The language's catalog first, then the app: its modules word many labels as they load (module constants), so
// they are imported only once the catalog is here.
void loadLanguage()
  .then(() => Promise.all([import("./App.tsx"), import("./CrashScreen.tsx"), import("./lib/accessibilitySwitch.ts")]))
  .then(([{ App }, { CrashBoundary }, { followAccessibility }]) => {
    // Before the first render, so the page never shows its plain borders and then the strong ones.
    followAccessibility(document.documentElement);
    createRoot(root).render(
      <StrictMode>
        <CrashBoundary>
          <App />
        </CrashBoundary>
      </StrictMode>,
    );
  })
  // A part of the app that did not arrive (offline before it was kept, or mid-update): a way back, never a blank page.
  .catch(() => {
    const note = document.createElement("p");
    note.setAttribute("role", "alert");
    note.style.cssText = "font: 18px system-ui, sans-serif; margin: 24px 16px";
    note.textContent = "RouteMaker did not finish loading. ";
    const again = document.createElement("button");
    again.textContent = "Reload";
    again.style.cssText = "font: inherit; min-height: 44px; padding: 0 16px";
    again.addEventListener("click", () => location.reload());
    note.append(again);
    root.replaceChildren(note);
  });
