/**
 * How Ride mode's card shows a cue (the owner, 2026-10-19: "Ride mode title takes up way too much real
 * estate"): the instruction large, what follows its first comma in small print under it, street words
 * shortened ("Florida Avenue Northeast" to "Florida Ave NE"). Shown only: the voice and screen readers keep
 * the whole sentence.
 */

// A street word is shortened only after a capitalised word ("R Street", "Florida Avenue"), never in plain
// words such as "bike lane" or "busy road".
const AFTER_NAME = String.raw`(?<=\b[A-Z0-9][\w'.-]* )`;
const SHORT: readonly [RegExp, string][] = [
  ["Avenue", "Ave"],
  ["Street", "St"],
  ["Road", "Rd"],
  ["Boulevard", "Blvd"],
  ["Drive", "Dr"],
  ["Parkway", "Pkwy"],
  ["Place", "Pl"],
  ["Terrace", "Ter"],
  ["Lane", "Ln"],
  ["Court", "Ct"],
  ["Northwest", "NW"],
  ["Northeast", "NE"],
  ["Southwest", "SW"],
  ["Southeast", "SE"],
].map(([long, short]) => [new RegExp(`${AFTER_NAME}${long}\\b`, "g"), short] as [RegExp, string]);

/** "Left onto R Street Northwest." as "Left onto R St NW.". */
export function shortStreets(text: string): string {
  return SHORT.reduce((out, [long, short]) => out.replace(long, short), text);
}

/** The cue split at its first comma: the instruction, then the rest with a capital ("No signal mapped, busy road (LTS 3)."). */
export function cueParts(text: string): { head: string; rest: string } {
  const short = shortStreets(text.trim());
  const at = short.indexOf(", ");
  if (at < 0) return { head: short, rest: "" };
  const rest = short.slice(at + 2);
  return { head: short.slice(0, at), rest: rest.charAt(0).toUpperCase() + rest.slice(1) };
}
