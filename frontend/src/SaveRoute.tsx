/**
 * Save route (v0.7.0 plan, "Discord sign-in on, with saved settings and routes", item 3): beside Share, signed
 * in only. It asks for a name only (offered as "Start to End") and says what happened politely.
 */
import { useEffect, useId, useRef, useState, type MouseEvent } from "react";
import { Icon } from "./Icon.tsx";
import { NAME_MAX } from "./lib/savedRoutes.ts";

/** How long the bar's "Saved" line stays on the map. */
export const SAID_ON_MAP_MS = 6000;

export interface SaveRouteProps {
  label: string;
  /** The name offered: "Start to End" from the plan's place names. */
  defaultName: () => string;
  /** Saves under the name; resolves to the line to say. Null signed out (the map bar's form only). */
  onSave: ((name: string) => Promise<string>) | null;
  /** Go's chip, or Plan's plain button in More. */
  chip?: boolean;
  /** Shorter words shown in place of the label, which stays the button's name. */
  shown?: string;
  /** Plan's big button at the top of the map, in Update route's place once a route is chosen. */
  bar?: boolean;
  /** Download GPX beside Save in the name form (the owner, 2026-10-21: "Save should save, but also allow a GPX
   * export too"); it is given the line to say once the file is saved. */
  onGpx?: (said: (line: string) => void) => void;
  /** Signed out, on the map bar: Discord sign-in in the name's place, where the server signs riders in
   * (the owner, 2026-10-21: "If someone isn't signed in allow them to sign in there via discord, or just export as
   * GPX"). The handler keeps the plan across the round trip. */
  signIn?: ((event: MouseEvent<HTMLAnchorElement>) => void) | null;
}

export function SaveRoute({ label, defaultName, onSave, chip = false, shown, bar = false, onGpx, signIn }: SaveRouteProps) {
  const [asking, setAsking] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState({ text: "", count: 0 });
  const openerRef = useRef<HTMLButtonElement>(null);
  const formId = useId();
  // On the map, the line that says it saved goes after a while: it would cover the map chips under the bar.
  useEffect(() => {
    if (!bar || !said.text) return;
    const timer = setTimeout(() => setSaid((s) => ({ ...s, text: "" })), SAID_ON_MAP_MS);
    return () => clearTimeout(timer);
  }, [bar, said]);
  const close = () => {
    setAsking(false);
    openerRef.current?.focus();
  };
  return (
    <div className={bar ? "save-route save-route-bar" : "save-route"}>
      <button
        type="button"
        ref={openerRef}
        className={bar ? "plan-bar-route save-route-open" : chip ? "chip save-route-chip" : "secondary save-route-open"}
        aria-expanded={asking}
        aria-controls={formId}
        aria-label={shown || bar ? label : undefined}
        onClick={() => {
          if (!asking) setName(defaultName());
          setAsking(!asking);
        }}
      >
        {/* Go's chip row is words only but the ride type's (review F15); a chip without shorter words keeps its icon. */}
        {chip && !shown && <Icon name="download" size={18} />}
        {bar && <Icon name="save" size={20} />}
        {/* On the map bar, "Save" on a phone, where the bar holds Start ride beside it too; the name is the label. */}
        {bar ? (
          <>
            Save<span className="plan-bar-wide"> route</span>
          </>
        ) : (
          (shown ?? label)
        )}
      </button>
      {asking && (
        <form
          id={formId}
          className="save-route-form"
          onSubmit={(event) => {
            event.preventDefault();
            const chosen = name.trim() || defaultName();
            if (busy || !onSave) return;
            setBusy(true);
            void onSave(chosen).then((text) => {
              setBusy(false);
              setSaid((s) => ({ text, count: s.count + 1 }));
              close();
            });
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              close();
            }
          }}
        >
          {onSave ? (
            <>
              <label>
                Name
                <input type="text" value={name} maxLength={NAME_MAX} onChange={(e) => setName(e.target.value)} autoFocus />
              </label>
              <button type="submit" aria-disabled={busy}>
                Save
              </button>
            </>
          ) : signIn ? (
            <a className="button save-route-sign-in" href="/auth/login" onClick={signIn} autoFocus>
              Sign in with Discord
            </a>
          ) : null}
          {onGpx && (
            <button
              type="button"
              className="secondary"
              autoFocus={!onSave && !signIn}
              onClick={() =>
                onGpx((text) => {
                  setSaid((s) => ({ text, count: s.count + 1 }));
                  close();
                })
              }
            >
              Download GPX
            </button>
          )}
          <button type="button" className="secondary" onClick={close}>
            Cancel
          </button>
        </form>
      )}
      <p className="hint save-route-said" role="status">
        {said.text}
        {said.count % 2 === 1 ? " " : ""}
      </p>
    </div>
  );
}
