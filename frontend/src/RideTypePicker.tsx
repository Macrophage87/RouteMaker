/**
 * The current ride type, shown compactly, and the modal dialog that changes it.
 *
 * The owner, 2026-09-27: "Have the ability to change route modes in a modal
 * dialog instead of a radio button. Selecting a preset will change the
 * sliders." The dialog is the platform's own `<dialog>` opened with
 * `showModal()`, which makes the rest of the page inert and closes on Escape;
 * Tab is also held inside it here (rideTypeDialog.ts), and on close the focus
 * goes back to the Change button. On a phone it is a full-height sheet
 * (styles.css, `.ride-types`).
 */
import { useEffect, useRef, type KeyboardEvent } from "react";
import { PRESETS, presetLabel, type PresetId } from "./lib/presets.ts";
import { CARRYINGS, carries, type Carrying, type Dials } from "./lib/dials.ts";
import { choose, closesDialog, initialCard, isCustom, nextFocus } from "./lib/rideTypeDialog.ts";

interface Props {
  preset: PresetId;
  dials: Dials;
  onChoose: (preset: PresetId, dials: Dials) => void;
}

const FOCUSABLE = "button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex='-1'])";

export function RideTypePicker({ preset, dials, onChoose }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const cardRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const current = PRESETS.find((p) => p.id === preset);
  const carrying = CARRYINGS.find((c) => c.id === dials.carrying);
  const custom = isCustom(preset, dials);

  const open = () => {
    dialogRef.current?.showModal();
    cardRefs.current[initialCard(preset)]?.focus();
  };
  const close = () => {
    dialogRef.current?.close();
  };
  // However it closes - a choice, Escape, the Close button - the focus goes
  // back to the button that opened it.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const onClose = () => openerRef.current?.focus();
    dialog.addEventListener("close", onClose);
    return () => dialog.removeEventListener("close", onClose);
  }, []);

  const pick = (id: PresetId, load: Carrying | null) => {
    onChoose(id, choose(id, load, dials));
    close();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (closesDialog(event.key)) {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;
    const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    const index = items.indexOf(document.activeElement as HTMLElement);
    const next = nextFocus(index, items.length, event.shiftKey);
    if (next >= 0) {
      event.preventDefault();
      items[next].focus();
    }
  };

  return (
    <section key="presets" className="ride-type" aria-labelledby="ride-type-heading">
      <h2 id="ride-type-heading">Ride type</h2>
      <div className="ride-type-current">
        <p>
          <strong>
            {custom ? `Custom (based on ${presetLabel(preset)})` : presetLabel(preset)}
            {carrying ? `, ${carrying.label.toLowerCase()}` : ""}
            {dials.assist ? ", electric assist" : ""}
          </strong>
          <span className="hint">{current?.description}</span>
        </p>
        <button type="button" ref={openerRef} onClick={open} aria-haspopup="dialog">
          Change
        </button>
      </div>
      <dialog
        ref={dialogRef}
        className="ride-types"
        aria-labelledby="ride-types-title"
        onKeyDown={onKeyDown}
        onClick={(event) => {
          // A click on the backdrop (the dialog element itself) closes it.
          if (event.target === dialogRef.current) close();
        }}
      >
        <div className="ride-types-body">
          <header>
            <h2 id="ride-types-title">Choose a ride type</h2>
            <button type="button" className="secondary" onClick={close}>
              Close
            </button>
          </header>
          <p className="hint">Choosing one moves the traffic and hills sliders to where it starts them.</p>
          <ul className="ride-type-cards">
            {PRESETS.map((option, index) => (
              <li key={option.id} className={option.id === preset ? "ride-type-card current" : "ride-type-card"}>
                <button
                  type="button"
                  ref={(el) => {
                    cardRefs.current[index] = el;
                  }}
                  aria-pressed={option.id === preset && (!carries(option.id) || dials.carrying === "cargo")}
                  onClick={() => pick(option.id, carries(option.id) ? "cargo" : null)}
                >
                  <strong>{option.label}</strong>
                  <span className="hint">{option.description}</span>
                </button>
                {carries(option.id) && (
                  <div className="ride-type-loads" role="group" aria-label={`${option.label}: cargo or passengers`}>
                    {CARRYINGS.map((load) => (
                      <button
                        key={load.id}
                        type="button"
                        className="secondary"
                        aria-pressed={option.id === preset && dials.carrying === load.id}
                        onClick={() => pick(option.id, load.id)}
                      >
                        {load.label}
                        <span className="hint">{load.hint}</span>
                      </button>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      </dialog>
    </section>
  );
}
