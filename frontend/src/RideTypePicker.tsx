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
import { Fragment, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { t } from "./lib/i18n.ts";
import { PRESETS, presetDescription, presetSaid, presetSummary, type PresetId } from "./lib/presets.ts";
import { PresetName } from "./lib/presetName.ts";
import { CARRYINGS, carries, type Carrying, type Dials } from "./lib/dials.ts";
import { bikeLabel } from "./lib/bikeshare.ts";
import { choose, closesDialog, initialCard, isCustom, nextFocus } from "./lib/rideTypeDialog.ts";
import { mtbChosen } from "./lib/mtbMode.ts";
import { rideSections, rideTypeCount, rideTypeSections, RideTypeSearch } from "./lib/rideTypeGroups.ts";
import { FavoriteStar, toggleFromPicker, useFavoriteRides } from "./lib/favoriteRides.ts";
import { matchingOwn, ownSetup, removeOwn, requestCreate, useOwnRideTypes, type OwnRideType } from "./lib/ownRideTypes.ts";
import { GoDefaultButton, OwnRideCards, ownSummary, takesGoDefault, type GoDefault } from "./lib/rideTypeCards.ts";

interface Props {
  preset: PresetId;
  dials: Dials;
  onChoose: (preset: PresetId, dials: Dials) => void;
  /** Each card's Go button (the owner, 2026-11-21: "make a button in the ride type list that will make it the default for go"). */
  go?: GoDefault;
}

/** The groups shown open in the dialog: the rider's favorites and the common ride types. */
const OPEN_GROUPS: readonly string[] = ["favorites", "common"];

/** A group of the dialog's ride types, folded under its name and count, or as it is. */
function GroupFold({ fold, label, count, open, children }: { fold: boolean; label: string; count: number; open: boolean; children: ReactNode }) {
  if (!fold) return <>{children}</>;
  return (
    <details className="fold ride-type-fold" open={open || undefined}>
      <summary>{`${label} (${count})`}</summary>
      <div className="fold-body">{children}</div>
    </details>
  );
}

// A fold's summary too, and only what shows: a card in a closed fold cannot take the focus.
const FOCUSABLE = "button:not([disabled]), [href], input:not([disabled]), summary, [tabindex]:not([tabindex='-1'])";

export function RideTypePicker({ preset, dials, onChoose, go }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const cardRefs = useRef(new Map<PresetId, HTMLButtonElement>());
  const [query, setQuery] = useState("");
  // Plan streamline (Stephen 2026-10-17): each card shows its one-line gist; "What each does" shows the full words.
  // A screen reader hears the full words either way.
  const [full, setFull] = useState(false);
  // Favorites (Stephen 2026-10-19): starred ride types first, under their own heading (lib/favoriteRides.ts).
  const favorites = useFavoriteRides();
  // The same groups as Go's Ride sheet and Settings' Primary Go method (P3): favorites, Common, then the rest.
  const groups = rideTypeSections(query, favorites);
  // One screen in the popup (the owner, 2026-10-28), as Go's Ride sheet has it: favorites and Common open, the rest
  // in their groups, folded (the one in use opens its group); a search shows every match flat.
  const folded = rideSections(query, undefined, favorites).folded;
  const current = PRESETS.find((p) => p.id === preset);
  const carrying = CARRYINGS.find((c) => c.id === dials.carrying);
  // The rider's own ride types (lib/ownRideTypes.ts), first; the one in use names the button.
  const own = useOwnRideTypes();
  const mine = matchingOwn(own.list, preset, dials);
  const custom = !mine && isCustom(preset, dials);

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

  const pickOwn = (choice: OwnRideType) => {
    const setup = ownSetup(choice);
    onChoose(setup.preset, setup.dials);
    close();
  };

  // My ride types and Create custom (the owner, 2026-11-21: "Put it after favorites"): after Favorites, else first.
  const ownSection =
    query === "" ? (
            <section className="ride-type-group" aria-labelledby="ride-types-own">
              <h3 id="ride-types-own">{t("My ride types")}</h3>
              {/* Create custom (the owner, 2026-11-21): Ride settings opens with its name box ready. */}
              <button
                type="button"
                className="secondary own-ride-create"
                onClick={() => {
                  close();
                  requestCreate();
                }}
              >
                {t("Create custom")}
              </button>
              <OwnRideCards list={own.list} inUse={mine?.id ?? null} onPick={pickOwn} onRemove={(o) => removeOwn(o.id)} idPrefix="ride-types" go={go} />
            </section>
    ) : null;
  const hasFavorites = groups.some((group) => group.id === "favorites");

  const onKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (closesDialog(event.key)) {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;
    const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.getClientRects().length > 0);
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
        {t("Ride type")}
      </p>
      {/* One button, the ride type and its gist on it, that opens the ride types (edit-route redesign, Stephen
          2026-10-18): it was a line of chips with Edit, then this line's Change, two presses to the list. */}
      <div className="ride-type-current">
        <button type="button" ref={openerRef} onClick={open} aria-haspopup="dialog" aria-describedby={current ? "ride-type-gist" : undefined}>
          <span className="ride-type-text">
            <strong>
              {mine ? (
                mine.name
              ) : custom ? (
                <>
                  {t("Custom (based on")} <PresetName id={preset} />)
                </>
              ) : (
                <PresetName id={preset} />
              )}
              {carrying ? `, ${carrying.label.toLowerCase()}` : ""}
              {dials.assist ? t(", electric assist") : ""}
              {dials.bike ? `, ${bikeLabel(dials.bike).toLowerCase()}` : ""}
            </strong>
            <span className="hint" aria-hidden="true">
              {mine ? ownSummary(mine) : current && presetSummary(current)}
            </span>
          </span>
          <span className="ride-type-change">{t("Change")}</span>
        </button>
        {current && (
          <span id="ride-type-gist" hidden>
            {presetDescription(current)}
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
            <h2 id="ride-types-title">{t("Choose a ride type")}</h2>
            <button type="button" className="secondary" onClick={close}>
              {t("Close")}
            </button>
          </header>
          <p className="hint">
            {t("Sets traffic and hills for this kind of ride.")}{" "}
            <button type="button" className="link ride-types-full" aria-pressed={full} onClick={() => setFull(!full)}>
              {t("What each does")}
            </button>
          </p>
          <RideTypeSearch id="ride-types-search" query={query} onQuery={setQuery} count={rideTypeCount(groups)} />
          {!hasFavorites && ownSection}
          {groups.map((group) => (
            <Fragment key={group.id}>
            <GroupFold key={group.id} fold={folded && !OPEN_GROUPS.includes(group.id)} label={group.label} count={group.ids.length} open={group.ids.includes(preset)}>
            <section className="ride-type-group" aria-labelledby={`ride-types-${group.id}`}>
              <h3 id={`ride-types-${group.id}`} className={folded && !OPEN_GROUPS.includes(group.id) ? "visually-hidden" : undefined}>{group.label}</h3>
              <ul className="ride-type-cards">
                {group.ids.map((id) => PRESETS.find((p) => p.id === id)!).map((option) => (
                  <li
                    key={option.id}
                    className={["ride-type-card", "has-fav", go && takesGoDefault(option.id) && "has-go", option.id === preset && !mine && "current", carries(option.id) && "with-loads"].filter(Boolean).join(" ")}
                  >
                    <button
                      type="button"
                      ref={(el) => {
                        if (el) cardRefs.current.set(option.id, el);
                        else cardRefs.current.delete(option.id);
                      }}
                      aria-pressed={option.id === preset && !mine && (!carries(option.id) || dials.carrying === "cargo")}
                      onClick={() => pick(option.id, carries(option.id) ? "cargo" : null)}
                    >
                      <strong>
                        <PresetName id={option.id} />
                      </strong>
                      {full ? (
                        <span className="hint">{presetDescription(option)}</span>
                      ) : (
                        <>
                          <span className="hint" aria-hidden="true">
                            {presetSummary(option)}
                          </span>
                          <span className="visually-hidden">{presetDescription(option)}</span>
                        </>
                      )}
                    </button>
                    <FavoriteStar id={option.id} on={favorites.includes(option.id)} onToggle={(id) => toggleFromPicker(id, dialogRef.current)} />
                    {carries(option.id) && (
                      <div className="ride-type-loads" role="group" aria-label={t("{ride}: cargo or passengers", { ride: presetSaid(option.id) })}>
                        {CARRYINGS.map((load) => (
                          <button
                            key={load.id}
                            type="button"
                            className="secondary"
                            aria-pressed={option.id === preset && dials.carrying === load.id}
                            onClick={() => pick(option.id, load.id)}
                          >
                            {load.label}
                            {full ? (
                              <span className="hint">{load.hint}</span>
                            ) : (
                              <>
                                <span className="hint" aria-hidden="true">
                                  {load.summary}
                                </span>
                                <span className="visually-hidden">{load.hint}</span>
                              </>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                    {/* Under the card, after a cargo bike's loads (the owner, 2026-11-21: "Make Go's default"). */}
                    {go && <GoDefaultButton goKey={option.id} said={presetSaid(option.id)} go={go} />}
                  </li>
                ))}
              </ul>
            </section>
            </GroupFold>
            {group.id === "favorites" && ownSection}
            </Fragment>
          ))}
        </div>
      </dialog>
    </section>
  );
}
