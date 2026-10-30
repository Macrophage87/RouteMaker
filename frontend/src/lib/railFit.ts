/**
 * The side buttons' words (the UI review, 2026-10-28: an unlabelled round Broadcast icon started a real broadcast when
 * a helper tapped it to see what it was): each round button has a short word under it, as 311 has its number. The rail
 * stays one column in its fixed order at every size, Large text too (it used to wrap into a second column and move 311
 * and More): where the words under the buttons do not fit the map's height, each button becomes a 44 px pill with its
 * word beside its icon, which takes far less height.
 *
 * Icons only (Settings > Display, Stephen 2026-10-29): no words, so the buttons stay round with a smaller gap; short of
 * room even so, they become 44 px circles.
 *
 * The choice is plain arithmetic on the rail's height and its buttons, so it is tested without a DOM; useRailFit
 * measures and keeps it current (Ride mode and Roam).
 */
import { useLayoutEffect, useState, type RefObject } from "react";

/** "under": round buttons with their words under them (none with icons only); "pill": 44 px pills, the word beside the
 * icon (44 px circles with icons only). */
export type RailFit = "under" | "pill";

/** A round button's height (styles.css .ride .ride-round), and the 311 and dock buttons', which are larger. */
export const ROUND_PX = 56;
export const ROUND_LARGE_PX = 60;
/** The height a word under a button takes, and the space between one button's word and the next button. */
export const WORD_PX = 18;
export const GAP_PX = 6;
/** A pill's height: the smallest target the ride screen uses. */
export const PILL_PX = 44;
/** The space between two round buttons with icons only (styles.css .ride-rail-icons.ride-rail-under). */
export const ICON_GAP_PX = 12;

/** The words fit under the buttons when the buttons, each word and the gaps fit `available` px; else pills. With icons
 * only, the round buttons and their gaps alone. */
export function railFit(available: number, buttons: number, large = 0, iconsOnly = false): RailFit {
  if (buttons <= 0) return "under";
  const each = iconsOnly ? ROUND_PX : ROUND_PX + WORD_PX;
  const gap = iconsOnly ? ICON_GAP_PX : GAP_PX;
  const need = buttons * each + large * (ROUND_LARGE_PX - ROUND_PX) + (buttons - 1) * gap;
  return need <= available ? "under" : "pill";
}

/** A box on the screen, as getBoundingClientRect gives it. */
export interface Box {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/**
 * How far down the rail the ride group's bar (Send alert and the riders, just under the ride's card) reaches, in px:
 * the rail starts below it, so its top button (See everyone, while others share) is never under Send alert (the
 * v0.15.2 end-to-end pass, 2026-10-30: at 390 px Send alert covered its top 24 px). Nothing when there is no bar or
 * it is beside the rail, not over it.
 */
export function barOverlap(rail: Box, bar: Box | null): number {
  if (!bar || bar.bottom <= bar.top || bar.right <= rail.left || bar.left >= rail.right) return 0;
  return Math.max(0, Math.ceil(bar.bottom - rail.top));
}

/** The rail's fit, measured again as its height changes (Large text, the bottom panel) and as buttons come and go. */
export function useRailFit(rail: RefObject<HTMLElement | null>, iconsOnly = false): RailFit {
  const [fit, setFit] = useState<RailFit>("under");
  useLayoutEffect(() => {
    const element = rail.current;
    if (!element) return;
    const resized = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => measure());
    // The ride groups' bars (a route's and Roam's may both be up), each watched for its size once seen.
    const barsSeen = new Set<Element>();
    const bars = () => [...document.querySelectorAll(".ride-group-bar")];
    const measure = () => {
      // The buttons in the column: a visually hidden hint (1 px) is not one.
      const items = [...element.children].filter((child) => (child as HTMLElement).offsetHeight > 2);
      const large = items.filter((child) => child.matches(".ride-311, .ride-dock")).length;
      // A group's bar over the rail's top: the rail starts below it (barOverlap), with that much less room.
      const box = element.getBoundingClientRect();
      let clear = 0;
      for (const bar of bars()) {
        if (!barsSeen.has(bar)) {
          barsSeen.add(bar);
          resized?.observe(bar);
        }
        clear = Math.max(clear, barOverlap(box, bar.getBoundingClientRect()));
      }
      element.style.paddingTop = clear > 0 ? `${clear}px` : "";
      setFit(railFit(element.clientHeight - clear, items.length, large, iconsOnly));
    };
    measure();
    resized?.observe(element);
    // A bar that comes or goes after the rail (the ride group renders outside it, once its ride is settled): measured again.
    const barsChanged = typeof MutationObserver === "undefined" ? null : new MutationObserver(() => {
      const now = bars();
      if (now.length === barsSeen.size && now.every((bar) => barsSeen.has(bar))) return;
      for (const bar of barsSeen) {
        if (now.includes(bar)) continue;
        resized?.unobserve(bar);
        barsSeen.delete(bar);
      }
      measure();
    });
    barsChanged?.observe(element.closest(".app") ?? document.body, { childList: true, subtree: true });
    const changed = typeof MutationObserver === "undefined" ? null : new MutationObserver(measure);
    changed?.observe(element, { childList: true });
    return () => {
      resized?.disconnect();
      changed?.disconnect();
      barsChanged?.disconnect();
    };
  }, [rail, iconsOnly]);
  return fit;
}
