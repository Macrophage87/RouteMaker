import { language } from "./i18n.ts";

/**
 * How Ride mode's card shows a cue (the owner, 2026-10-19: "Ride mode title takes up way too much real
 * estate"): the instruction large, what follows its first comma in small print under it, street words
 * shortened ("Florida Avenue Northeast" to "Florida Ave NE"). Shown only: the voice and screen readers keep
 * the whole sentence.
 */

// A street word is shortened only where it ends a name: after a capitalised word ("R Street", "Florida Avenue"),
// and, for a type, only before a quadrant or the end of the name ("Supreme Court" stays as it is mid-name less often
// than "Northwest Branch", which stays whole). Never in plain words such as "bike lane" or "busy road". The same
// words as the course file's (lib/course.ts STREET_WORDS).
const AFTER_NAME = String.raw`(?<=\b[A-Z0-9][\w'.-]* )`;
const QUADRANTS = ["Northwest", "Northeast", "Southwest", "Southeast", "NW", "NE", "SW", "SE"];
// A name's end in any of the app's languages: punctuation, a bidi isolate (lib/i18n.ts t), or the sentence's own
// words in another script straight after it, spaced, hyphened or not ("R Street Northwestに", "R Street Northwest पर",
// "R Street Northwest-এ").
const OTHER_SCRIPT = String.raw`\u2069。、，،።፣]|[\s-]?[^\x00-\x7F]`;
const NAME_END = String.raw`(?=[,.;:)${OTHER_SCRIPT}|$| (?:${QUADRANTS.join("|")})\b)`;
const TYPES: readonly [string, string][] = [
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
  ["Trail", "Trl"],
  ["Highway", "Hwy"],
  ["Circle", "Cir"],
  ["Square", "Sq"],
  ["Bridge", "Br"],
];
const SHORT: readonly [RegExp, string][] = [
  ...TYPES.map(([long, short]) => [new RegExp(`${AFTER_NAME}${long}${NAME_END}`, "g"), short] as [RegExp, string]),
  ...(
    [
      ["Northwest", "NW"],
      ["Northeast", "NE"],
      ["Southwest", "SW"],
      ["Southeast", "SE"],
    ] as const
  ).map(([long, short]) => [new RegExp(`${AFTER_NAME}${long}(?=[,.;:)${OTHER_SCRIPT}|$| [a-z])`, "g"), short] as [RegExp, string]),
];

// Spanish turn words run half again as long as the English (the owner, 2026-10-27: "use shorter words so it all
// fits"): the card shows them shorter, "Gire a la izquierda hacia" as "A la izquierda hacia". Shown only, as above.
const SHORT_ES: readonly [RegExp, string][] = [
  [/\b([Gg])ire ligeramente a la (izquierda|derecha)\b/g, "leve a la $2"],
  [/\b([Gg])ire a la (izquierda|derecha)\b/g, "a la $2"],
  [/\b([Dd])é la vuelta en U\b/g, "vuelta en U"],
  [/\b([Ii])nmediatamente\b/g, "enseguida"],
];

/** The Spanish turn words shortened, with a capital where the long words had one (the first group is that letter). */
function shortTurnsEs(text: string): string {
  return SHORT_ES.reduce(
    (out, [long, short]) =>
      out.replace(long, (_, first: string, side: unknown) => {
        const said = typeof side === "string" ? short.replace("$2", side) : short;
        return first === first.toUpperCase() ? said.charAt(0).toUpperCase() + said.slice(1) : said;
      }),
    text,
  );
}

/** "Left onto R Street Northwest." as "Left onto R St NW.". */
export function shortStreets(text: string): string {
  return SHORT.reduce((out, [long, short]) => out.replace(long, short), text);
}

// The street's last words kept on one line in the other languages (the owner, 2026-10-28: "make sure ... the words fit
// properly in the spaces"): a narrow card broke "R St NW" as "R / St NW". English and Spanish wrap as before.
const SHORT_WORD = new RegExp(String.raw`(?<=[A-Za-z0-9.]) (?=(?:${[...TYPES.map(([, short]) => short), "NW", "NE", "SW", "SE"].join("|")})\b(?! [a-z]))`, "g");

/** The cue split at its first comma: the instruction, then the rest with a capital ("No signal mapped, busy road (LTS 3)."). */
export function cueParts(text: string): { head: string; rest: string } {
  const streets = shortStreets(text.trim());
  const lang = language();
  const short = lang === "es" ? shortTurnsEs(streets) : lang === "en" ? streets : streets.replace(SHORT_WORD, "\u00a0");
  // The comma as each script writes it: ", ", the Chinese and Japanese "，" and "、", the Arabic "، ", the Ge'ez "፣ ".
  const comma = /, |，|、|، |፣ /.exec(short);
  if (!comma) return { head: short, rest: "" };
  const at = comma.index;
  const rest = short.slice(at + comma[0].length).trimStart();
  return { head: short.slice(0, at), rest: rest.charAt(0).toUpperCase() + rest.slice(1) };
}
