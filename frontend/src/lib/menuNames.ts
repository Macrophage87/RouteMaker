/**
 * Menu names in a phone's settings steps are marked **like this** in the words and their translations, so they show
 * in bold (the owner, 2026-10-28: "bold the exact menu names so they stand out"). MenuStep.tsx draws them; the voice
 * and screen readers get the words without the marks.
 */

/** The words in turn, each with whether it is a menu name. */
export function menuParts(text: string): { text: string; menu: boolean }[] {
  return text.split("**").map((part, i) => ({ text: part, menu: i % 2 === 1 })).filter((part) => part.text !== "");
}

/** The words without the marks, to say or read out. */
export function withoutMenuMarks(text: string): string {
  return text.split("**").join("");
}
