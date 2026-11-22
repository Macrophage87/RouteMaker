/**
 * Save route (v0.7.0 plan, "Discord sign-in on, with saved settings and routes", item 3): beside Share, signed
 * in only. It asks for a name (offered as "Start to End") and says what happened politely. In Plan it asks for tags
 * too, optional (the owner, 2026-11-07): the account's tags are offered as they are typed. One box, Fixed route
 * (the owner, 2026-11-10), keeps the line as it is, never planned again; unticked (our default), by its via points.
 * Plan's alone, with an (i) with both kinds: Go's Save is a name alone (the owner: "Go shouldn't include it").
 */
import { useEffect, useId, useRef, useState, type MouseEvent } from "react";
import { DiscordLogo } from "./DiscordLogo.tsx";
import { signInLabel } from "./lib/signIn.ts";
import { signInHasChoice } from "./lib/stressEditor.ts";
import { Icon } from "./Icon.tsx";
import { InfoButton } from "./SettingRow.tsx";
import { LinkBox } from "./LinkBox.tsx";
import { SHARE_LABEL } from "./lib/share.ts";
import { firstWordAndRest, t } from "./lib/i18n.ts";
import { KEEPING_SAID } from "./lib/offlineRoutes.ts";
import { FIXED_ABOUT, FIXED_HINT, FIXED_ROUTE, NAME_MAX, SAVE_ROUTE, TAGS_MAX, listRoutes, parseTags, tagHints, tagsInUse, takeHint } from "./lib/savedRoutes.ts";

/** How long the bar's "Saved" line stays on the map. */
export const SAID_ON_MAP_MS = 6000;
/** How long a keep's line (signed out, with Sign in to sync on it) stays on the map. */
export const KEPT_ON_MAP_MS = 20000;

export interface SaveRouteProps {
  label: string;
  /** The name offered: "Start to End" from the plan's place names. */
  defaultName: () => string;
  /** Saves under the name (and the tags, where asked); resolves to the line to say. Null signed out (the map bar's
   * form only). */
  onSave: ((name: string, tags?: string[], fixed?: boolean) => Promise<string>) | null;
  /** The Fixed route box, ticked as this says (the route's own, saved again); absent, no box and by its via points. */
  defaultFixed?: () => boolean;
  /** Plan's: asks for tags too, offering these first (the route's own, saved again). Absent (Go), no tags field. */
  defaultTags?: () => string[];
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
  /**
   * Signed out (onSave null), Plan's bar: a press keeps the route on this device (Keep for offline) and says so, with
   * Sign in to sync beside it, in place of a sign-in form (intuitiveness review, 2026-11-21: the biggest button after
   * planning was a sign-in wall). Resolves to the line to say ("" says nothing) and whether the route was kept.
   */
  keepHere?: (() => Promise<{ said: string; kept: boolean }>) | null;
  /**
   * Share route on the line that says it saved (Stephen 2026-11-22: "After saving, you should also be able to
   * copy/share a link"): the share sheet, else the link copied. Resolves to the line to say ("" keeps the saved line)
   * and the link to show in a box where it could neither be shared nor copied ("" for none).
   */
  onShare?: (() => Promise<{ said: string; box: string }>) | null;
}

export function SaveRoute({ label, defaultName, onSave, chip = false, shown, bar = false, onGpx, signIn, defaultTags, defaultFixed, keepHere = null, onShare = null }: SaveRouteProps) {
  const [asking, setAsking] = useState(false);
  const [name, setName] = useState("");
  const [fixed, setFixed] = useState(false);
  const [fixedInfo, setFixedInfo] = useState(false);
  const fixedId = useId();
  const [tagText, setTagText] = useState("");
  const [offered, setOffered] = useState<string[]>([]);
  const tagsId = useId();
  // The account's tags, read once as the form opens (Plan's alone; the props are made anew each render).
  const wantsTags = Boolean(defaultTags && onSave);
  useEffect(() => {
    if (!asking || !wantsTags) return;
    let live = true;
    void listRoutes(window.location.origin).then((all) => live && all && setOffered(tagsInUse(all)));
    return () => {
      live = false;
    };
  }, [asking, wantsTags]);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState({ text: "", count: 0 });
  // The said line is a keep's (signed out): Sign in to sync shows beside it.
  const [keptHere, setKeptHere] = useState(false);
  const keepsHere = !onSave && keepHere !== null;
  // A save answered: Share route shows on its line; `box`, the link to copy by hand.
  const [saved, setSaved] = useState(false);
  const [box, setBox] = useState("");
  const openerRef = useRef<HTMLButtonElement>(null);
  // React's autoFocus skips a link: the sign-in link takes the focus as the form opens, as the name field does.
  const signInRef = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    if (asking) signInRef.current?.focus();
  }, [asking]);
  const formId = useId();
  // On the map, the line that says it saved goes after a while: it would cover the map chips under the bar.
  useEffect(() => {
    // Not while a keep is still under way: "Keeping…" stays until it ends (the PR review's 8).
    // Nor while the link waits in its box to be copied.
    if (!bar || !said.text || busy || box) return;
    // A keep's line, with Sign in to sync on it, stays longer: there is a link on it to reach.
    // So does one with Share route on it.
    const timer = setTimeout(() => setSaid((s) => ({ ...s, text: "" })), keptHere || (saved && onShare) ? KEPT_ON_MAP_MS : SAID_ON_MAP_MS);
    return () => clearTimeout(timer);
  }, [bar, said, keptHere, busy, box, saved, onShare]);
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
        aria-expanded={keepsHere ? undefined : asking}
        aria-controls={keepsHere ? undefined : formId}
        aria-disabled={keepsHere && busy ? true : undefined}
        aria-label={shown || bar ? label : undefined}
        onClick={() => {
          if (keepsHere) {
            if (busy) return;
            setBusy(true);
            // Keeping the map along it takes a while: said at once (the Keep for offline button's words).
            setKeptHere(false);
            setSaid((s) => ({ text: KEEPING_SAID, count: s.count + 1 }));
            void keepHere().then(({ said: text, kept }) => {
              setBusy(false);
              setKeptHere(kept);
              setSaid((s) => ({ text, count: s.count + 1 }));
            });
            return;
          }
          if (!asking) {
            setSaved(false);
            setBox("");
            setName(defaultName());
            setFixed(defaultFixed?.() ?? false);
            setFixedInfo(false);
            const first = defaultTags?.() ?? [];
            setTagText(first.length ? `${first.join(", ")}, ` : "");
          }
          setAsking(!asking);
        }}
      >
        {/* Go's chip row is words only but the ride type's (review F15); a chip without shorter words keeps its icon. */}
        {chip && !shown && <Icon name="download" size={18} />}
        {bar && <Icon name="save" size={20} />}
        {/* On the map bar, "Save" on a phone, where the bar holds Start ride beside it too; the name is the label. */}
        {bar ? (
          <>
            {firstWordAndRest(SAVE_ROUTE)[0]}
            <span className="plan-bar-wide">{firstWordAndRest(SAVE_ROUTE)[1]}</span>
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
            void onSave(chosen, defaultTags ? parseTags(tagText) : undefined, defaultFixed ? fixed : undefined).then((text) => {
              setBusy(false);
              setSaid((s) => ({ text, count: s.count + 1 }));
              setSaved(true);
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
                {t("Name")}
                <input type="text" value={name} maxLength={NAME_MAX} onChange={(e) => setName(e.target.value)} autoFocus />
              </label>
              {defaultTags && (
                <>
                  <label>
                    {t("Tags (optional)")}
                    <input type="text" value={tagText} onChange={(e) => setTagText(e.target.value)} aria-describedby={`${tagsId}-hint`} autoComplete="off" />
                  </label>
                  {tagHints(offered, tagText).length > 0 && parseTags(tagText).length < TAGS_MAX && (
                    <div className="load-route-tags save-route-tag-hints" role="group" aria-label={t("Your tags")}>
                      {tagHints(offered, tagText).map((x) => (
                        <button key={x} type="button" className="load-route-tag" onClick={() => setTagText(takeHint(tagText, x))}>
                          {x}
                        </button>
                      ))}
                    </div>
                  )}
                  <p className="hint" id={`${tagsId}-hint`}>
                    {t("Commas between tags. Change them later in Save & load.")}
                    {tagText.split(",").filter((x) => x.trim()).length > TAGS_MAX && ` ${t("A route keeps the first {n} tags.", { n: String(TAGS_MAX) })}`}
                  </p>
                </>
              )}
              {defaultFixed && (
                <>
                  <div className="setting-line save-route-fixed">
                    <label className="check-row">
                      <input type="checkbox" checked={fixed} onChange={(e) => setFixed(e.target.checked)} />
                      <span>
                        <strong>{FIXED_ROUTE}</strong>
                        <span className="hint">
                          {FIXED_HINT}
                        </span>
                      </span>
                    </label>
                    {/* Plan's alone (the owner, 2026-10-14: Plan holds the detail, in (i) popups). */}
                    {defaultTags && <InfoButton open={fixedInfo} onToggle={() => setFixedInfo((was) => !was)} controls={`${fixedId}-about`} about={FIXED_ROUTE} />}
                  </div>
                  {defaultTags && (
                    <ul className="hint setting-info info-bullets" id={`${fixedId}-about`} hidden={!fixedInfo}>
                      {FIXED_ABOUT.map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                  )}
                </>
              )}
              <button type="submit" aria-disabled={busy}>
                {t("Save")}
              </button>
            </>
          ) : signIn ? (
            <a className="button save-route-sign-in" href="/auth/login" onClick={signIn} ref={signInRef}>
              {!signInHasChoice() && <DiscordLogo />}
              {signInLabel()}
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
              {t("Download GPX")}
            </button>
          )}
          <button type="button" className="secondary" onClick={close}>
            {t("Cancel")}
          </button>
        </form>
      )}
      <p className="hint save-route-said" role="status">
        {said.text}
        {said.count % 2 === 1 ? " " : ""}
        {/* On the line's card under the bar, while it shows. */}
        {saved && onShare && said.text && (
          <>
            {" "}
            <button
              type="button"
              className="link save-route-share"
              onClick={() => {
                setBox("");
                void onShare().then(({ said: text, box: link }) => {
                  if (text) setSaid((s) => ({ text, count: s.count + 1 }));
                  setBox(link);
                });
              }}
            >
              {SHARE_LABEL}
            </button>
          </>
        )}
        {keepsHere && keptHere && said.text && signIn && (
          <>
            {" "}
            <a className="save-route-sync" href="/auth/login" onClick={signIn}>
              {t("Sign in to sync")}
            </a>
          </>
        )}
      </p>
      {saved && said.text && <LinkBox link={box} />}
    </div>
  );
}
