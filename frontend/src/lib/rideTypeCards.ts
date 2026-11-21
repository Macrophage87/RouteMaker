/**
 * Go's More ride types as cards (Stephen, 2026-10-15: "instead have a popout that has all these
 * options and explains things more"): each ride type a card with its name and one short sentence
 * (PresetOption.summary), the gist first; the longer description stays on Plan's dialog.
 *
 * Each card is one button (with onFavorite, a star toggle beside it: lib/favoriteRides.ts FavoriteStar). Its name is the ride type's name (aria-labelledby, so the emoji of a
 * transit name are not read: PresetName); its sentence is its description (aria-describedby).
 * The ride type in use is pressed (aria-pressed), so it is said as well as shown. A
 * createElement component, so a test renders it (node's runner reads .ts, not .tsx).
 */
import { createElement as h, type ReactElement } from "react";
import { PRESETS, presetLabel, presetSaid, presetSummary, type PresetId } from "./presets.ts";
import { PresetName } from "./presetName.ts";
import { FavoriteStar } from "./favoriteRides.ts";
import { t } from "./i18n.ts";
import { lineIcon } from "./sidebarParts.ts";
import { ownSetup, type OwnRideType } from "./ownRideTypes.ts";
import { rideSummaryParts } from "./rideSummary.ts";

/**
 * Go's default, from the ride type list (the owner, 2026-11-21: "make a button in the ride type list that will make it
 * the default for go"): what the button says is pressed. `key` is a ride type's id or "own:<id>" for one of the
 * rider's own; `current` is Go's now; pressing the pressed one puts Go back on Default.
 */
export interface GoDefault {
  current: string;
  onSet: (key: string) => void;
}

/** One of the rider's own in a line: its ride type, then what its sliders set ("Fast · balanced traffic · waits count 3x"). */
export function ownSummary(own: OwnRideType): string {
  const { preset, dials } = ownSetup(own);
  return [presetLabel(preset), ...rideSummaryParts(preset, dials).slice(1).filter((part) => part !== t("now"))].join(" · ");
}

/** Mass Ride is never Go's (Settings' Primary Go method leaves it out too). */
export const takesGoDefault = (key: string) => key !== "mass-ride";

/** The Go button beside a card's star: "Go" shown, "Go starts on Cargo Bike" heard, pressed where it is Go's. */
export function GoDefaultButton({ goKey, said, go }: { goKey: string; said: string; go: GoDefault }): ReactElement | null {
  if (!takesGoDefault(goKey)) return null;
  const on = go.current === goKey;
  return h(
    "button",
    {
      type: "button",
      className: "ride-fav ride-go-default",
      "data-go": goKey,
      "aria-pressed": on,
      "aria-label": t("Go starts on {ride}", { ride: said }),
      title: t("Go starts on {ride}", { ride: said }),
      onClick: () => go.onSet(on ? "default" : goKey),
    },
    t("Go"),
  );
}

/**
 * "My ride types" (lib/ownRideTypes.ts): each of the rider's own as a card, its name over its ride type and sliders
 * ("Fast · balanced traffic · ..."), pressed where it is what is in use (`inUse`); its Go button, and Remove.
 */
export function OwnRideCards({
  list,
  inUse,
  onPick,
  onRemove,
  idPrefix,
  go,
}: {
  list: readonly OwnRideType[];
  inUse: string | null;
  onPick: (own: OwnRideType) => void;
  onRemove: (own: OwnRideType) => void;
  idPrefix: string;
  go?: GoDefault;
}): ReactElement {
  return h(
    "ul",
    { className: "ride-type-cards ride-sheet-cards own-ride-cards" },
    list.map((own) => {
      const nameId = `${idPrefix}-own-${own.id}-name`;
      const aboutId = `${idPrefix}-own-${own.id}-about`;
      const current = own.id === inUse;
      return h(
        "li",
        { key: own.id, className: `ride-type-card has-fav has-go${current ? " current" : ""}` },
        h(
          "button",
          { type: "button", "aria-pressed": current, "aria-labelledby": nameId, "aria-describedby": aboutId, onClick: () => onPick(own) },
          h("strong", { id: nameId }, own.name),
          h("span", { id: aboutId, className: "hint" }, ownSummary(own)),
        ),
        go ? h(GoDefaultButton, { goKey: `own:${own.id}`, said: own.name, go }) : null,
        h(
          "button",
          { type: "button", className: "ride-fav ride-own-remove", "aria-label": t("Remove {name}", { name: own.name }), onClick: () => onRemove(own) },
          lineIcon("trash", 20),
        ),
      );
    }),
  );
}

export function RideTypeCards({
  ids,
  preset,
  onPick,
  idPrefix,
  favorites,
  onFavorite,
  go,
}: {
  ids: readonly PresetId[];
  preset: PresetId;
  onPick: (id: PresetId) => void;
  /** Makes the name and sentence ids unique in the page. */
  idPrefix: string;
  /** The rider's favorites: with onFavorite, each card has its star (lib/favoriteRides.ts). */
  favorites?: readonly PresetId[];
  onFavorite?: (id: PresetId) => void;
  /** Each card's Go button (GoDefaultButton). */
  go?: GoDefault;
}): ReactElement {
  return h(
    "ul",
    { className: "ride-type-cards ride-sheet-cards" },
    ids.map((id) => {
      const option = PRESETS.find((p) => p.id === id);
      const current = id === preset;
      const nameId = `${idPrefix}-${id}-name`;
      const aboutId = `${idPrefix}-${id}-about`;
      return h(
        "li",
        { key: id, className: `ride-type-card${current ? " current" : ""}${onFavorite ? " has-fav" : ""}${go && takesGoDefault(id) ? " has-go" : ""}` },
        h(
          "button",
          {
            type: "button",
            "aria-pressed": current,
            "aria-labelledby": nameId,
            "aria-describedby": aboutId,
            onClick: () => onPick(id),
          },
          h("strong", { id: nameId }, h(PresetName, { id })),
          h("span", { id: aboutId, className: "hint" }, option ? presetSummary(option) : ""),
        ),
        go ? h(GoDefaultButton, { goKey: id, said: presetSaid(id), go }) : null,
        onFavorite ? h(FavoriteStar, { id, on: favorites?.includes(id) ?? false, onToggle: onFavorite }) : null,
      );
    }),
  );
}
