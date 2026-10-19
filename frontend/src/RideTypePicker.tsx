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
 *
 * The current ride type is one button with its name, gist and Change on it, which opens the dialog
 * (edit-route redesign, Stephen 2026-10-18).
 *
 * RIDE-TYPE-ORGANISE (Stephen, 2026-10-12): a search box over the cards, and the
 * cards under their group's heading (lib/rideTypeGroups.ts).
 */
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { PRESETS, presetSaid, type PresetId } from "./lib/presets.ts";
import { PresetName } from "./lib/presetName.ts";
import { CARRYINGS, carries, type Carrying, type Dials } from "./lib/dials.ts";
import { bikeLabel } from "./lib/bikeshare.ts";
import { choose, closesDialog, initialCard, isCustom, nextFocus } from "./lib/rideTypeDialog.ts";
import { mtbChosen } from "./lib/mtbMode.ts";
import { filterRideGroups, rideTypeCount, RideTypeSearch, withFavorites } from "./lib/rideTypeGroups.ts";
import { FavoriteStar, toggleFromPicker, useFavoriteRides } from "./lib/favoriteRides.ts";

interface Props {
  preset: PresetId;
  dials: Dials;
  onChoose: (preset: PresetId, dials: Dials) => void;
}

const FOCUSABLE = "button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex='-1'])";

export function RideTypePicker({ preset, dials, onChoose }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const cardRefs = useRef(new Map<PresetId, HTMLButtonElement>());
  const [query, setQuery] = useState("");
  // Plan streamline (Stephen 2026-10-17): each card shows its one-line gist; "What each does" shows the full words.
  // A screen reader hears the full words either way.
  const [full, setFull] = useState(false);
  const [favSaid, setFavSaid] = useState("");
  // Favorites (Stephen 2026-10-19): starred ride types first, under their own heading (lib/favoriteRides.ts).
  const favorites = useFavoriteRides();
  const groups = withFavorites(filterRideGroups(query), favorites);
  const current = PRESETS.find((p) => p.id === preset);
  const carrying = CARRYINGS.find((c) => c.id === dials.carrying);
  const custom = isCustom(preset, dials);

  const open = () => {
    dialogRef.current?.showModal();
    cardRefs.current.get(PRESETS[initialCard(preset)].id)?.focus();
  };
  const close = () => {
    dialogRef.current?.close();
  };
  // However it closes - a choice, Escape, the Close button - the focus goes
  // back to the button that opened it.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    // The search is cleared as it closes, so the next opening shows every ride type and the
    // one in use is there to take the focus.
    const onClose = () => {
      setQuery("");
      setFavSaid("");
      openerRef.current?.focus();
    };
    dialog.addEventListener("close", onClose);
    return () => dialog.removeEventListener("close", onClose);
  }, []);

  const pick = (id: PresetId, load: Carrying | null) => {
    // Mountain Bike starts as a loop from the start (slice 6; lib/mtbMode.ts mtbChosen).
    onChoose(id, mtbChosen(preset, id, choose(id, load, dials)));
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
      {/* A label, not a heading: the Ride settings h2 follows it in the outline (the review of the redesign). */}
      <p id="ride-type-heading" className="ride-type-label">
        Ride type
      </p>
      {/* One button, the ride type and its gist on it, that opens the ride types (edit-route redesign, Stephen
          2026-10-18): it was a line of chips with Edit, then this line's Change, two presses to the list. */}
      <div className="ride-type-current">
        <button type="button" ref={openerRef} onClick={open} aria-haspopup="dialog" aria-describedby={current ? "ride-type-gist" : undefined}>
          <span className="ride-type-text">
            <strong>
              {custom ? (
                <>
                  Custom (based on <PresetName id={preset} />)
                </>
              ) : (
                <PresetName id={preset} />
              )}
              {carrying ? `, ${carrying.label.toLowerCase()}` : ""}
              {dials.assist ? ", electric assist" : ""}
              {dials.bike ? `, ${bikeLabel(dials.bike).toLowerCase()}` : ""}
            </strong>
            <span className="hint" aria-hidden="true">
              {current?.summary}
            </span>
          </span>
          <span className="ride-type-change">Change</span>
        </button>
        {current && (
          <span id="ride-type-gist" hidden>
            {current.description}
          </span>
        )}
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
          <p className="hint">
            Choosing one moves the traffic and hills sliders to where it starts them.{" "}
            <button type="button" className="link ride-types-full" aria-pressed={full} onClick={() => setFull(!full)}>
              What each does
            </button>
          </p>
          <RideTypeSearch id="ride-types-search" query={query} onQuery={setQuery} count={rideTypeCount(groups)} />
          <p role="status" className="visually-hidden">
            {favSaid}
          </p>
          {groups.map((group) => (
            <section key={group.id} className="ride-type-group" aria-labelledby={`ride-types-${group.id}`}>
              <h3 id={`ride-types-${group.id}`}>{group.label}</h3>
              <ul className="ride-type-cards">
                {group.ids.map((id) => PRESETS.find((p) => p.id === id)!).map((option) => (
                  <li key={option.id} className={option.id === preset ? "ride-type-card has-fav current" : "ride-type-card has-fav"}>
                    <button
                      type="button"
                      ref={(el) => {
                        if (el) cardRefs.current.set(option.id, el);
                        else cardRefs.current.delete(option.id);
                      }}
                      aria-pressed={option.id === preset && (!carries(option.id) || dials.carrying === "cargo")}
                      onClick={() => pick(option.id, carries(option.id) ? "cargo" : null)}
                    >
                      <strong>
                        <PresetName id={option.id} />
                      </strong>
                      {full ? (
                        <span className="hint">{option.description}</span>
                      ) : (
                        <>
                          <span className="hint" aria-hidden="true">
                            {option.summary}
                          </span>
                          <span className="visually-hidden">{option.description}</span>
                        </>
                      )}
                    </button>
                    <FavoriteStar id={option.id} on={favorites.includes(option.id)} onToggle={(id) => setFavSaid(toggleFromPicker(id, dialogRef.current))} />
                    {carries(option.id) && (
                      <div className="ride-type-loads" role="group" aria-label={`${presetSaid(option.id)}: cargo or passengers`}>
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
            </section>
          ))}
        </div>
      </dialog>
    </section>
  );
}
