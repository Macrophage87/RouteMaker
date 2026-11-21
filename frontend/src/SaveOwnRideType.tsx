/**
 * "Save as my own ride type", at the foot of the Ride settings popup (the owner, 2026-11-21: "Let people save and name
 * their own configuration dials"; the mockup, "Sounds good"). Shown once a slider is moved from where the ride type
 * starts it and the setup is not already one of the rider's own; pressed, one name box with Save and Cancel. A name
 * already used is replaced (lib/ownRideTypes.ts withSaved): no separate rename or edit.
 */
import { useEffect, useId, useRef, useState } from "react";
import { t } from "./lib/i18n.ts";
import { OWN_NAME_MAX, freeName, ownName, ownNow, ownPlan, readShareJson, saveOwn, shareJson, type OwnRideType } from "./lib/ownRideTypes.ts";
import { copyText, selectionCopy } from "./lib/sidebar.ts";
import { startDials, type Dials } from "./lib/dials.ts";
import { presetLabel, type PresetId } from "./lib/presets.ts";

/** Whether the sliders are anywhere but where the ride type starts them (the trip's own dials aside). */
export function differsFromStart(preset: PresetId, dials: Dials): boolean {
  return ownPlan(preset, dials) !== ownPlan(preset, startDials(preset, dials.carrying, dials.when, dials.assist, dials.bike ?? null));
}

export function SaveOwnRideType(props: { preset: PresetId; dials: Dials; matching: OwnRideType | null; onLoad: (preset: PresetId, dials: Dials) => void }) {
  return (
    <>
      <SaveButton {...props} />
      <ShareSettings {...props} />
    </>
  );
}

/**
 * Advanced (the owner, 2026-11-21: "In an advanced settings dropdown, have a share and load mechanism to send between
 * people, like via JSON"): Copy puts these settings on the clipboard as JSON (lib/ownRideTypes.ts shareJson); settings
 * pasted in and loaded are used at once and kept in My ride types under their name.
 */
function ShareSettings({ preset, dials, matching, onLoad }: { preset: PresetId; dials: Dials; matching: OwnRideType | null; onLoad: (preset: PresetId, dials: Dials) => void }) {
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
    setSaid(t("Loaded {name}. It is in My ride types.", { name: own?.name ?? read.name }));
  };
  return (
    <details className="fold own-ride-share">
      <summary>{t("Advanced")}</summary>
      <div className="fold-body">
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
    </details>
  );
}

function SaveButton({ preset, dials, matching }: { preset: PresetId; dials: Dials; matching: OwnRideType | null }) {
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [said, setSaid] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const openRef = useRef<HTMLButtonElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (naming) inputRef.current?.focus();
  }, [naming]);
  // A new change after a save: the line that said it was saved goes.
  const plan = ownPlan(preset, dials);
  useEffect(() => setSaid(""), [plan]);
  const offered = matching === null && differsFromStart(preset, dials);
  const save = () => {
    const kept = ownName(name);
    if (!kept) return;
    const own = saveOwn(kept, preset, dials);
    setNaming(false);
    setSaid(own ? t("Saved as {name}. It is first in the ride types.", { name: own.name }) : "");
    // The form goes: the focus to the popup's title, now the saved name (review of #1385), not lost to the page.
    const frame = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (run: () => void) => run();
    frame(() => rootRef.current?.closest("dialog")?.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true }));
  };
  return (
    <div ref={rootRef} className="own-ride-save-wrap">
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
                const frame = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (run: () => void) => run();
                frame(() => openRef.current?.focus());
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
