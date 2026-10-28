/**
 * The side buttons' words (the UI review, 2026-10-28: an unlabelled round Broadcast icon started a real broadcast when
 * a helper tapped it to see what it was): each round button has a short word under it, as 311 has its number. The rail
 * stays one column in its fixed order at every size, Large text too (it used to wrap into a second column and move 311
 * and More): where the words under the buttons do not fit the map's height, each button becomes a 44 px pill with its
 * word beside its icon, which takes far less height.
 *
 * The choice is plain arithmetic on the rail's height and its buttons, so it is tested without a DOM; useRailFit
 * measures and keeps it current (Ride mode and Roam).
 */
import { useLayoutEffect, useState, type RefObject } from "react";

/** "under": round buttons with their words under them; "pill": 44 px pills, the word beside the icon. */
export type RailFit = "under" | "pill";

/** A round button's height (styles.css .ride .ride-round), and the 311 and dock buttons', which are larger. */
export const ROUND_PX = 56;
export const ROUND_LARGE_PX = 60;
/** The height a word under a button takes, and the space between one button's word and the next button. */
export const WORD_PX = 18;
export const GAP_PX = 6;
/** A pill's height: the smallest target the ride screen uses. */
export const PILL_PX = 44;

/** The words fit under the buttons when the buttons, each word and the gaps fit `available` px; else pills. */
export function railFit(available: number, buttons: number, large = 0): RailFit {
  if (buttons <= 0) return "under";
  const need = buttons * (ROUND_PX + WORD_PX) + large * (ROUND_LARGE_PX - ROUND_PX) + (buttons - 1) * GAP_PX;
  return need <= available ? "under" : "pill";
}

/** The rail's fit, measured again as its height changes (Large text, the bottom panel) and as buttons come and go. */
export function useRailFit(rail: RefObject<HTMLElement | null>): RailFit {
  const [fit, setFit] = useState<RailFit>("under");
  useLayoutEffect(() => {
    const element = rail.current;
    if (!element) return;
    const measure = () => {
      // The buttons in the column: a visually hidden hint (1 px) is not one.
      const items = [...element.children].filter((child) => (child as HTMLElement).offsetHeight > 2);
      const large = items.filter((child) => child.matches(".ride-311, .ride-dock")).length;
      setFit(railFit(element.clientHeight, items.length, large));
    };
    measure();
    const resized = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    resized?.observe(element);
    const changed = typeof MutationObserver === "undefined" ? null : new MutationObserver(measure);
    changed?.observe(element, { childList: true });
    return () => {
      resized?.disconnect();
      changed?.disconnect();
    };
  }, [rail]);
  return fit;
}
