/**
 * Accessibility mode (OWNER-DECISIONS 455, replacing 450's always-visible Map tools): off
 * unless a rider turned it on, remembered on this device. On, "Map tools" (MapTools.tsx) is
 * by the map's zoom buttons, with Add point at map center and Road info at map center, for
 * riders on a keyboard or a screen reader. A switch (a button with aria-pressed), the page's first stop and hidden until it
 * has the focus, turns it on or off; the same toggle is in "More tips". The keyboard's
 * shortcuts (I, the arrows, + and -) work in either state.
 *
 * The hint texts that name Map tools take the state (mapToolsWays) so they stay right when
 * the tools are not on the page.
 */

export const ACCESS_MODE_KEY = "routemaker.accessMode";

/** The control's name in both states (a switch: the state is aria-pressed, not the name). */
export const ACCESS_LABEL = "Accessibility mode";
export const ACCESS_ON_SAID = "Accessibility mode on. Map tools is by the map's zoom buttons.";
export const ACCESS_OFF_SAID = "Accessibility mode off. Map tools is hidden.";
/** The "More tips" line beside the toggle. */
export const ACCESS_HELP =
  "Accessibility mode adds Map tools by the map's zoom buttons, with Add point at map center and Road info at map center. It is also the first button on the page, and is kept on this device.";

/** What a screen reader hears after a press, with the state it went to. */
export function accessModeSaid(on: boolean): string {
  return on ? ACCESS_ON_SAID : ACCESS_OFF_SAID;
}

/** The storage's two methods this uses (a test passes a stand-in). */
export interface KeyValueStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** The browser's localStorage, or null where reaching it throws (blocked site data, some embedded views). */
export function browserStore(): KeyValueStore | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The remembered state; off when nothing is kept, or storage refuses or holds something else. */
export function readAccessMode(store: KeyValueStore | null = browserStore()): boolean {
  try {
    return store?.getItem(ACCESS_MODE_KEY) === "on";
  } catch {
    return false;
  }
}

/** Keep the state on this device; false when storage refused (it then lasts this visit). */
export function writeAccessMode(on: boolean, store: KeyValueStore | null = browserStore()): boolean {
  try {
    if (!store) return false;
    store.setItem(ACCESS_MODE_KEY, on ? "on" : "off");
    return true;
  } catch {
    return false;
  }
}

/**
 * The keyboard's way to add a point or open the road panel, said for the state:
 * on, it names Map tools; off, it first says how to turn the mode on.
 */
export function mapToolsWays(on: boolean): { addPoint: string; roadAndAdd: string } {
  return on
    ? {
        addPoint: 'use "Add point at map center" in Map tools',
        roadAndAdd: "open Map tools (by the map's zoom buttons) for Road info at map center and Add point at map center",
      }
    : {
        addPoint: 'turn on accessibility mode (the first button on the page), then use "Add point at map center" in Map tools',
        roadAndAdd:
          "turn on accessibility mode (the first button on the page) and open Map tools (by the map's zoom buttons) for Road info at map center and Add point at map center",
      };
}
