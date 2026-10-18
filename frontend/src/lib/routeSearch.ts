/**
 * The Save and load sheet's search over the rider's routes (the owner, 2026-10-18: "the files tab (maybe
 * call it save or load) is where we should save the routes and search for them"): the saved routes and
 * the routes kept for offline, by name, every word typed in any order, case and accents ignored.
 */

const fold = (text: string) =>
  text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();

/** The items whose name holds every word of `filter`; all of them when it is blank. */
export function matching<T>(items: readonly T[], filter: string, nameOf: (item: T) => string): T[] {
  const words = fold(filter).split(/\s+/).filter(Boolean);
  if (words.length === 0) return [...items];
  return items.filter((item) => {
    const name = fold(nameOf(item));
    return words.every((word) => name.includes(word));
  });
}

/** What a list says while searched, politely: how many of its routes match, or none; nothing when blank. */
export function matchSaid(shown: number, total: number, filter: string): string {
  if (!filter.trim()) return "";
  if (shown === 0) return noMatch(filter);
  return `${shown} of ${total} match "${filter.trim()}".`;
}

/** What a list says when the search hides every route in it. */
export function noMatch(filter: string): string {
  return `No routes match "${filter.trim()}".`;
}
