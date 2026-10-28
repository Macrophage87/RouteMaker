/**
 * Detail behind an (i) as short bullets, not a paragraph (P8: "no walls of text"): a note's sentences, one to a
 * bullet. The wording stays the note's own, so its translation and what a screen reader hears are unchanged.
 */

/** Words whose full stop is not a sentence's end ("St. Elmo", "e.g. a park"). */
const ABBREVIATION = /\b(?:e\.g|i\.e|St|Mt|Ave|Dr|vs|approx|etc|Sr|Jr|Av|aprox)\.$/i;

/** A text's sentences, in order: split after a full stop, question or exclamation mark followed by a space. */
export function sentences(text: string): string[] {
  const parts = text.trim().split(/(?<=[.!?])\s+/);
  const out: string[] = [];
  for (const part of parts) {
    const last = out.length - 1;
    if (last >= 0 && ABBREVIATION.test(out[last])) out[last] = `${out[last]} ${part}`;
    else if (part) out.push(part);
  }
  return out;
}
