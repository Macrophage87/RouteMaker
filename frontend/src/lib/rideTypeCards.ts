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
import { createElement as h, type ReactElement, type ReactNode } from "react";
import { PRESETS, presetSummary, type PresetId } from "./presets.ts";
import { PresetName } from "./presetName.ts";
import { FavoriteStar } from "./favoriteRides.ts";

export function RideTypeCards({
  ids,
  preset,
  onPick,
  icon,
  idPrefix,
  favorites,
  onFavorite,
}: {
  ids: readonly PresetId[];
  preset: PresetId;
  onPick: (id: PresetId) => void;
  /** The card's icon (decorative: aria-hidden); a function so the .tsx Icon stays out of this file. */
  icon?: (id: PresetId) => ReactNode;
  /** Makes the name and sentence ids unique in the page. */
  idPrefix: string;
  /** The rider's favorites: with onFavorite, each card has its star (lib/favoriteRides.ts). */
  favorites?: readonly PresetId[];
  onFavorite?: (id: PresetId) => void;
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
        { key: id, className: `ride-type-card${current ? " current" : ""}${onFavorite ? " has-fav" : ""}` },
        h(
          "button",
          {
            type: "button",
            "aria-pressed": current,
            "aria-labelledby": nameId,
            "aria-describedby": aboutId,
            onClick: () => onPick(id),
          },
          icon ? h("span", { className: "ride-card-icon", "aria-hidden": "true" }, icon(id)) : null,
          h("strong", { id: nameId }, h(PresetName, { id })),
          h("span", { id: aboutId, className: "hint" }, option ? presetSummary(option) : ""),
        ),
        onFavorite ? h(FavoriteStar, { id, on: favorites?.includes(id) ?? false, onToggle: onFavorite }) : null,
      );
    }),
  );
}
