/**
 * When a Featured routes post's section minimaps are made and let go (postPage.tsx draws them). Kept apart from the
 * map code so it can be tested without a browser.
 */

export const MINIMAP_LABEL = "Map of this stretch of the route";
/** How near the screen a minimap is made, and how far past it is let go: a browser keeps only so many maps (about
 * 16 WebGL contexts in Chrome, the oldest dropped first, which would be the route's own map). */
export const MINIMAP_NEAR = "400px 0px";
export const MINIMAP_FAR = "1600px 0px";

export type Observe = (callback: (entries: { target: Element; isIntersecting: boolean }[]) => void, margin: string) => { observe(el: Element): void };

/** Each section's small map, made when it nears the screen and let go when far from it. `make` draws one and
 * returns what lets it go; `stretches` are the page data's lines, which each host names by its data-section. */
export function showMinimaps(
  doc: Pick<Document, "querySelectorAll">,
  stretches: readonly number[][][],
  make: (host: HTMLElement, stretch: number[][]) => () => void,
  observe: Observe | null = typeof IntersectionObserver === "undefined" ? null : (callback, margin) => new IntersectionObserver(callback, { rootMargin: margin }),
): void {
  const lineOf = (host: Element) => stretches[Number((host as HTMLElement).dataset.section)];
  const hosts = [...doc.querySelectorAll<HTMLElement>(".section-map[data-section]")].filter((host) => (lineOf(host)?.length ?? 0) >= 2);
  const shown = new Map<Element, () => void>();
  const draw = (host: Element) => {
    if (shown.has(host)) return;
    try {
      shown.set(host, make(host as HTMLElement, lineOf(host)));
    } catch {
      // No WebGL: the caption stays on its own.
    }
  };
  if (!observe) {
    hosts.forEach(draw);
    return;
  }
  const near = observe((seen) => seen.forEach((entry) => entry.isIntersecting && draw(entry.target)), MINIMAP_NEAR);
  const far = observe(
    (seen) =>
      seen.forEach((entry) => {
        if (entry.isIntersecting) return;
        shown.get(entry.target)?.();
        shown.delete(entry.target);
      }),
    MINIMAP_FAR,
  );
  hosts.forEach((host) => {
    near.observe(host);
    far.observe(host);
  });
}

