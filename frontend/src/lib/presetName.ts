/**
 * A ride type's name as it shows, with its emoji kept from a screen reader (Stephen, 2026-10-12:
 * "Bikeshare + 🚶🚆🚌", said "Bikeshare plus walk, train or bus"). Wherever a name with emoji shows
 * (Go's buttons, the ride type groups and search, Plan's list, the trip's heading), the shown name is
 * aria-hidden and the spoken one is read in its place; a name without emoji is plain text. A
 * createElement component, so a test renders it (node's runner reads .ts, not .tsx).
 */
import { Fragment, createElement as h, type ReactElement } from "react";
import { PRESETS, presetLabel, type PresetId } from "./presets.ts";

export function PresetName({
  id,
  suffix = "",
}: {
  id: PresetId;
  /** Words after the name, shown and said alike: " trip". */
  suffix?: string;
}): ReactElement {
  const option = PRESETS.find((p) => p.id === id);
  if (!option?.spoken) return h(Fragment, null, `${presetLabel(id)}${suffix}`);
  return h(
    Fragment,
    null,
    h("span", { "aria-hidden": "true" }, `${option.label}${suffix}`),
    h("span", { className: "visually-hidden" }, `${option.spoken}${suffix}`),
  );
}
