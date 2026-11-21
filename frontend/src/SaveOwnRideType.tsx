/**
 * "Save as my own ride type", at the foot of the Ride settings popup (the owner, 2026-11-21: "Let people save and name
 * their own configuration dials"; the mockup, "Sounds good"). Shown once a slider is moved from where the ride type
 * starts it and the setup is not already one of the rider's own; pressed, one name box with Save and Cancel. A name
 * already used is replaced (lib/ownRideTypes.ts withSaved): no separate rename or edit.
 */
import { useEffect, useId, useRef, useState } from "react";
import { t } from "./lib/i18n.ts";
import { OWN_MAX, OWN_NAME_MAX, freeName, ownFull, ownName, ownNow, ownPlan, readShareJson, saveOwn, shareJson, useCreateRequests, type OwnRideType } from "./lib/ownRideTypes.ts";
import { copyText, selectionCopy } from "./lib/sidebar.ts";
import { startDials, type Dials } from "./lib/dials.ts";
import { presetLabel, type PresetId } from "./lib/presets.ts";

/** Whether the sliders are anywhere but where the ride type starts them (the trip's own dials aside). */
export function differsFromStart(preset: PresetId, dials: Dials): boolean {
  return ownPlan(preset, dials) !== ownPlan(preset, startDials(preset, dials.carrying, dials.when, dials.assist, dials.bike ?? null));
}

/**
 * Save as my own ride type, at the foot of the Ride settings screen; Create custom's name box is a second one, at the
 * screen's top (`create`), so the name comes first and the four main settings are under it (intuitiveness review,
 * Stephen 2026-11-21). Sharing (ShareSettings) is at the foot of the Advanced fold.
 */
export function SaveOwnRideType(props: { preset: PresetId; dials: Dials; matching: OwnRideType | null; create?: boolean }) {
  return <SaveButton {...props} />;
}

/**
 * Advanced (the owner, 2026-11-21: "In an advanced settings dropdown, have a share and load mechanism to send between
 * people, like via JSON"): Copy puts these settings on the clipboard as JSON (lib/ownRideTypes.ts shareJson); settings
 * pasted in and loaded are used at once and kept in My ride types under their name.
 */
export function ShareSettings({ preset, dials, matching, onLoad }: { preset: PresetId; dials: Dials; matching: OwnRideType | null; onLoad: (preset: PresetId, dials: Dials) => void }) {
  const [pasted, setPasted] = useState("");
  const [said, setSaid] = useState("");
  const id = useId();
  const copy = async () => {
    const done = await copyText(shareJson(matching?.name ?? presetLabel(preset), preset, dials), navigator.clipboard, selectionCopy);
    setSaid(done ? t("Copied. Send it to anyone; they paste it here and press Load.") : t("Could not copy."));
  };
  const load = () => {
    const read = readShareJson(pasted);
    if (!read) {
      setSaid(t("These are not RouteMaker ride settings."));
      return;
    }
    onLoad(read.preset, read.dials);
    const own = saveOwn(freeName(ownNow().list, read.name, read.preset, read.dials), read.preset, read.dials);
    setPasted("");
    // A full list keeps what it has (release review of #1385): the settings still apply, and the rider is told.
    setSaid(own ? t("Loaded {name}. It is in My ride types.", { name: own.name }) : t("Loaded {name} for now. My ride types is full ({max}): remove one to keep it.", { name: read.name, max: OWN_MAX }));
  };
  return (
    // In the Advanced fold already (DialsPanel), so a group under its own small heading, not a second fold.
    <div className="own-ride-share" role="group" aria-labelledby={`${id}-share`}>
      <h3 id={`${id}-share`} className="own-ride-share-title">{t("Share ride settings")}</h3>
      <div>
        <button type="button" className="secondary" onClick={() => void copy()}>
          {t("Copy these settings")}
        </button>
        <label htmlFor={id}>{t("Paste settings to load")}</label>
        <textarea id={id} rows={3} value={pasted} spellCheck={false} autoComplete="off" onChange={(event) => setPasted(event.target.value)} />
        <button type="button" className="secondary" disabled={pasted.trim() === ""} onClick={load}>
          {t("Load")}
        </button>
        <p className="hint" role="status">
          {said}
        </p>
      </div>
    </div>
  );
}

function SaveButton({ preset, dials, matching, create = false }: { preset: PresetId; dials: Dials; matching: OwnRideType | null; create?: boolean }) {
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [said, setSaid] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const openRef = useRef<HTMLButtonElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const id = useId();
  // The name ready to type over (the tap-count review: "My Default" was not selected).
  useEffect(() => {
    if (!naming) return;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [naming]);
  // A new change after a save: the line that said it was saved goes.
  const plan = ownPlan(preset, dials);
  useEffect(() => setSaid(""), [plan]);
  // The top one is Create custom's alone; the foot one is Save as my own ride type's alone.
  const offered = !create && matching === null && differsFromStart(preset, dials);
  // Create custom from the ride type list: the name box at once, whatever the sliders say.
  const creates = useCreateRequests();
  const createsAtMount = useRef(creates);
  useEffect(() => {
    if (creates === createsAtMount.current) return;
    createsAtMount.current = creates;
    if (!create) return;
    setName(t("My {ride}", { ride: presetLabel(preset) }));
    setNaming(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a new press opens it
  }, [creates]);
  const save = () => {
    const kept = ownName(name);
    if (!kept) return;
    if (ownFull(ownNow().list, kept)) {
      // Never a silent loss of the oldest (release review of #1385): the form stays, and says why.
      setSaid(t("My ride types is full ({max}). Remove one to save another.", { max: OWN_MAX }));
      return;
    }
    const own = saveOwn(kept, preset, dials);
    setNaming(false);
    setSaid(own ? t("Saved as {name}. It is first in the ride types.", { name: own.name }) : "");
    // Create custom's save is done (the tap-count review: Save, then Done, then Close): the screen closes as Done closes
    // it, back to the route (in Go, the Ride sheet with it), and the focus goes where Done sends it.
    const frame = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (run: () => void) => run();
    frame(() => {
      const dialog = rootRef.current?.closest("dialog");
      if (create) dialog?.querySelector<HTMLButtonElement>(".ride-settings-done")?.click();
      // The form goes: the focus to the popup's title, now the saved name (review of #1385), not lost to the page.
      else dialog?.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
    });
  };
  return (
    <div ref={rootRef} className={`own-ride-save-wrap${create ? " own-ride-create-wrap" : ""}${create && naming ? " naming" : ""}`}>
      {naming ? (
        <form
          className="own-ride-save"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <label htmlFor={id}>{t("Name")}</label>
          <input id={id} ref={inputRef} type="text" value={name} maxLength={OWN_NAME_MAX} autoComplete="off" onChange={(event) => setName(event.target.value)} />
          <div className="closure-choices">
            <button type="submit" className="primary" disabled={!ownName(name)}>
              {t("Save")}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setNaming(false);
                setSaid("");
                const frame = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (run: () => void) => run();
                // Back to Save as my own ride type, else (opened by Create custom with nothing moved) the popup's
                // title (release review of #1385), not lost to the page.
                frame(() => (openRef.current ?? rootRef.current?.closest("dialog")?.querySelector<HTMLElement>("h2"))?.focus({ preventScroll: true }));
              }}
            >
              {t("Cancel")}
            </button>
          </div>
        </form>
      ) : (
        offered && (
          <div className="own-ride-save">
            <button
              type="button"
              ref={openRef}
              className="secondary"
              onClick={() => {
                setName(t("My {ride}", { ride: presetLabel(preset) }));
                setNaming(true);
              }}
            >
              {t("Save as my own ride type")}
            </button>
          </div>
        )
      )}
      {/* Always in the page, so what it says is heard when it changes. */}
      <p className="hint own-ride-said" role="status">
        {said}
      </p>
    </div>
  );
}
