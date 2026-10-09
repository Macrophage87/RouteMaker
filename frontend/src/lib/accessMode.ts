/**
 * Accessibility mode (OWNER-DECISIONS 455, replacing 450's always-visible Map tools): off
 * unless a rider turned it on, remembered on this device. On, "Map tools" (MapTools.tsx) is
 * by the map's zoom buttons, with Add point at map center and Road info at map center, for
 * riders on a keyboard or a screen reader. A switch (a button with aria-pressed), the page's
 * first stop and hidden until it has the focus, turns it on or off; the same switch is in "More tips". The keyboard's
 * shortcuts (I, the arrows, + and -) work in either state.
 *
 * The hint texts that name Map tools take the state (mapToolsWays) so they stay right when
 * the tools are not on the page.
 */

/**
 * Where the choice is kept: "on" or "off", and only "on" means on. Unrelated to the High contrast
 * switch, whose key is the older `routemaker.accessibility` (lib/accessibilitySwitch.ts, stressStyle.js).
 */
export const ACCESS_MODE_KEY = "routemaker.accessMode";

/** The control's name in both states (a switch: the state is aria-pressed, not the name). */
export const ACCESS_LABEL = "Accessibility mode";
export const ACCESS_ON_SAID = "Accessibility mode on. Map tools is by the map's zoom buttons.";
export const ACCESS_OFF_SAID = "Accessibility mode off. Map tools is hidden.";
/** The owner's sentence for turning the mode on (OWNER-DECISIONS 455a(4)). */
export const ACCESS_SENTENCE = "For keyboard or screen reader use, turn on accessibility mode.";
/**
 * The same, with where the switch is, for the hints shown outside "More tips" (the search lede and
 * the lone-start hint), whose reader may be far below the page's first button.
 */
export const ACCESS_SENTENCE_WHERE = ACCESS_SENTENCE.replace(/\.$/, " (the first button on the page, or in More tips).");
/** The "More tips" line beside the toggle: the one place in More tips that says where the switch is. */
export const ACCESS_HELP = `${ACCESS_SENTENCE} It adds Map tools by the map's zoom buttons and is kept on this device. It is also the first button on the page.`;

/** What a screen reader hears after a press, with the state it went to. */
export function accessModeSaid(on: boolean): string {
  return on ? ACCESS_ON_SAID : ACCESS_OFF_SAID;
}

/**
 * One press of either switch, from the state `on`: the state it goes to, what is said, and whether the
 * focus then moves to Map tools. Only the page's first button moves it, and only when turning the mode
 * on (455a(2)); the More tips toggle and turning it off leave the focus where it is.
 */
export function accessModeToggle(on: boolean, fromFirstStop: boolean): { next: boolean; said: string; focusTools: boolean } {
  const next = !on;
  return { next, said: accessModeSaid(next), focusTools: next && fromFirstStop };
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
        // Shown only in More tips, whose own line (ACCESS_HELP) says where the switch is (the spec review's SF4).
        addPoint: 'turn on accessibility mode, then use "Add point at map center" in Map tools',
        roadAndAdd:
          "turn on accessibility mode and open Map tools (by the map's zoom buttons) for Road info at map center and Add point at map center",
      };
}
