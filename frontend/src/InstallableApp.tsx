/**
 * The installable app's parts of the page (WEB-NAV-plan.md section 8, phases P2-P4):
 *
 * - `useAppStatus`: the service worker's "new version ready" (lib/appWorker.ts) and the network's
 *   online and offline, with what each says. `AppStatusBar` shows them at the top of the panel;
 *   App's own live region (outside the panel, so it is heard with the sheet hidden) says them.
 * - `InstallOffer`: "Install RouteMaker" (Chrome, Edge, Android), the iOS line, or "installed"
 *   (lib/installOffer.ts), in Settings and in More tips. Never a pop-up.
 * - `KeptRoutes`: Settings' list of the routes kept for offline, each with Open and Remove
 *   (lib/offlineRoutes.ts, lib/offlineKeep.ts).
 *
 * Accessibility: every control is a real button with its words in text, 44 px high (the panel's own
 * rule); nothing takes the focus on its own; after a press that removes the control pressed, the
 * focus goes to the next sensible place (the next row's Remove, or the section's heading), never to the
 * page's top. What changes is said once, politely, through `onSay` (App's live region with its count).
 */
import { useCallback, useEffect, useId, useRef, useState, useSyncExternalStore, type RefObject } from "react";
import { AppWorker, OFFLINE_SAID, ONLINE_SAID, UPDATE_READY, UPDATE_RELOAD, browserWorkerEnv, updateOffered } from "./lib/appWorker.ts";
import {
  DISMISSED_SAID,
  INSTALLED_NOTE,
  INSTALLED_SAID,
  INSTALL_HEADING,
  INSTALL_LABEL,
  INSTALL_WHY,
  IOS_INSTALL,
  installOffer,
  installState,
  isStandalone,
  promptInstall,
  subscribeInstall,
} from "./lib/installOffer.ts";
import { removeKept } from "./lib/offlineKeep.ts";
import { KEPT_HEADING, KEPT_NONE, KEPT_PRIVATE, focusAfterRemove, keptDetail, removedSaid, sortKept, storageNote, type KeptRoute } from "./lib/offlineRoutes.ts";
import { listKept, persisted } from "./lib/offlineRouteStore.ts";

// ---- The new version and the network --------------------------------------------------------------

let worker: AppWorker | null = null;
let workerReady = false;
const readyListeners = new Set<() => void>();

/** One worker client for the page (React's strict mode runs effects twice; the registration is once). */
function startWorker(): AppWorker {
  if (!worker) {
    worker = new AppWorker(browserWorkerEnv(), (ready) => {
      workerReady = ready;
      readyListeners.forEach((listener) => listener());
    });
    void worker.start();
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") worker?.check();
    });
  }
  return worker;
}

const subscribeReady = (listener: () => void) => {
  readyListeners.add(listener);
  return () => readyListeners.delete(listener);
};

function useOnline(): boolean {
  return useSyncExternalStore(
    (listener) => {
      window.addEventListener("online", listener);
      window.addEventListener("offline", listener);
      return () => {
        window.removeEventListener("online", listener);
        window.removeEventListener("offline", listener);
      };
    },
    () => navigator.onLine !== false,
  );
}

export interface AppStatus {
  updateShown: boolean;
  offline: boolean;
  reload: () => void;
}

/**
 * The page's status as an installable app. `onSay` is told, once each: a new version ready (held
 * during a ride, said when it ends), offline, and back online (both shown, not said, during a ride:
 * Ride mode says what a lost signal means for the ride itself).
 */
export function useAppStatus(riding: boolean, onSay: (text: string) => void): AppStatus {
  useEffect(() => void startWorker(), []);
  const ready = useSyncExternalStore(subscribeReady, () => workerReady);
  const online = useOnline();
  const updateShown = updateOffered(ready, riding);
  const said = useRef({ update: false, offline: false });
  useEffect(() => {
    if (updateShown && !said.current.update) {
      said.current.update = true;
      onSay(`${UPDATE_READY} The ${UPDATE_RELOAD} button is at the top of the planner.`);
    }
  }, [updateShown, onSay]);
  useEffect(() => {
    if (!online && !said.current.offline) {
      said.current.offline = true;
      if (!riding) onSay(OFFLINE_SAID);
    } else if (online && said.current.offline) {
      said.current.offline = false;
      if (!riding) onSay(ONLINE_SAID);
    }
    // `riding` is read, not watched: a ride starting or ending says nothing about the network.
  }, [online, onSay]);
  const reload = useCallback(() => startWorker().apply(), []);
  return { updateShown, offline: !online, reload };
}

/** At the top of the panel: offline, and the new version with its Reload. Empty, it is not drawn. */
export function AppStatusBar({ status }: { status: AppStatus }) {
  if (!status.updateShown && !status.offline) return null;
  return (
    <div className="app-status">
      {status.offline && <p className="app-offline">{OFFLINE_SAID}</p>}
      {status.updateShown && (
        <div className="app-update">
          <p id="app-update-text">{UPDATE_READY}</p>
          <button type="button" aria-describedby="app-update-text" onClick={status.reload}>
            {UPDATE_RELOAD}
          </button>
        </div>
      )}
    </div>
  );
}

// ---- The install offer -----------------------------------------------------------------------------

function useInstall() {
  const [, setVersion] = useState(0);
  useEffect(() => subscribeInstall(() => setVersion((v) => v + 1)), []);
  return installOffer(installState());
}

/**
 * The offer, under its own heading (Settings) or as a short block (More tips, `compact`). `onSay`
 * hears the outcome of the browser's dialog; the focus then goes to the heading (the button it was on
 * is gone) in Settings, or stays in the tips' block on its note.
 */
export function InstallOffer({ idBase, compact = false, onSay }: { idBase: string; compact?: boolean; onSay: (text: string) => void }) {
  const offer = useInstall();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const noteRef = useRef<HTMLParagraphElement>(null);
  // What the browser's dialog ended with, kept on screen where the button was (it is gone after a press).
  const [said, setSaid] = useState("");
  if (offer === "none" && !said) return null;
  if (compact && offer === "installed" && !said) return null;
  const press = async () => {
    const outcome = await promptInstall();
    const text = outcome === "accepted" ? INSTALLED_SAID : outcome === "dismissed" ? DISMISSED_SAID : "";
    if (!text) return;
    setSaid(text);
    onSay(text);
    window.setTimeout(() => (compact ? noteRef : headingRef).current?.focus(), 0);
  };
  // Installed (here or by the browser's own menu), the press's outcome gives way to the plain note.
  const note = offer === "installed" ? (said === INSTALLED_SAID ? said : INSTALLED_NOTE) : offer === "none" ? said : "";
  const body = (
    <>
      {offer === "button" && (
        <>
          {!compact && <p className="hint">{INSTALL_WHY}</p>}
          <button type="button" className="install-app" onClick={() => void press()}>
            {INSTALL_LABEL}
          </button>
        </>
      )}
      {offer === "ios" && (
        <p className="hint install-ios">
          {compact ? "To install RouteMaker: " : `${INSTALL_WHY} `}
          {IOS_INSTALL}
        </p>
      )}
      {note && (
        <p className="hint install-note" ref={noteRef} tabIndex={-1}>
          {note}
        </p>
      )}
    </>
  );
  if (compact) return <div className="install-offer install-offer-tips">{body}</div>;
  return (
    <section aria-labelledby={`${idBase}-heading`} className="install-offer">
      <h3 id={`${idBase}-heading`} ref={headingRef} tabIndex={-1}>
        {INSTALL_HEADING}
      </h3>
      {body}
    </section>
  );
}

// ---- The routes kept for offline -------------------------------------------------------------------

/**
 * Settings' list. `version` is bumped by App when a route is kept, so the list reads the store again;
 * `onOpen` opens a kept route's plan (with no signal, the planner shows the kept answer).
 */
export function KeptRoutes({ version, onOpen, onSay, headingRef }: { version: number; onOpen: (route: KeptRoute) => void; onSay: (text: string) => void; headingRef?: RefObject<HTMLHeadingElement | null> }) {
  const [routes, setRoutes] = useState<KeptRoute[] | null>(null);
  const [kept, setKept] = useState<boolean | null>(null);
  const [removed, setRemoved] = useState(0);
  const ownHeading = useRef<HTMLHeadingElement>(null);
  const heading = headingRef ?? ownHeading;
  const removeRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const focusNext = useRef<ReturnType<typeof focusAfterRemove> | null>(null);
  const id = useId();
  useEffect(() => {
    let current = true;
    void listKept().then((all) => current && setRoutes(sortKept(all)));
    void persisted().then((p) => current && setKept(p));
    return () => {
      current = false;
    };
  }, [version, removed]);
  useEffect(() => {
    const target = focusNext.current;
    if (target === null || routes === null) return;
    focusNext.current = null;
    if (target === "heading") heading.current?.focus();
    else removeRefs.current[target.row]?.focus();
  }, [routes, heading]);
  const remove = async (route: KeptRoute, index: number) => {
    await removeKept(route.id).catch(() => undefined);
    const left = (routes?.length ?? 1) - 1;
    focusNext.current = focusAfterRemove(index, left);
    onSay(removedSaid(route.title, left));
    setRemoved((n) => n + 1);
  };
  return (
    <section aria-labelledby={`${id}-heading`} className="kept-routes">
      <h3 id={`${id}-heading`} ref={heading} tabIndex={-1}>
        {KEPT_HEADING}
      </h3>
      {routes === null ? (
        <p className="hint">Reading the routes kept on this device…</p>
      ) : routes.length === 0 ? (
        <p className="hint">{KEPT_NONE}</p>
      ) : (
        <ul className="kept-list">
          {routes.map((route, index) => (
            <li key={route.id} className="kept-route">
              <p className="kept-title" id={`${id}-title-${index}`}>
                {route.title}
              </p>
              <p className="hint kept-detail" id={`${id}-detail-${index}`}>
                {keptDetail(route)}
              </p>
              <div className="kept-actions">
                <button type="button" className="secondary" aria-describedby={`${id}-detail-${index}`} onClick={() => onOpen(route)}>
                  Open<span className="visually-hidden"> {route.title}</span>
                </button>
                <button
                  type="button"
                  className="secondary"
                  ref={(button) => {
                    removeRefs.current[index] = button;
                  }}
                  onClick={() => void remove(route, index)}
                >
                  Remove<span className="visually-hidden"> {route.title}</span>
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="hint">
        {KEPT_PRIVATE} {storageNote(kept, isStandalone())}
      </p>
    </section>
  );
}
