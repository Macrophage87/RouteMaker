/**
 * Accessibility mode (OWNER-DECISIONS 455, replacing 450's always-visible Map tools): off
 * unless a rider turned it on, remembered on this device. It is the one shared mode (the owner:
 * "Accessibility = one shared mode with screen-reader tweaks"): turning it on or off sets High
 * contrast and Large text during a ride with it (accessModeParts), which stay as switches of their
 * own under it in Settings, so a rider can set either one apart afterwards. On, "Map tools" (MapTools.tsx) is
 * by the map's zoom buttons, with Add point at map center and Road info at map center, for
 * riders on a keyboard or a screen reader. A switch (a button with aria-pressed), the page's
 * first stop and hidden until it has the focus, turns it on or off; the same switch is in Settings, Display and
 * under the Points heading's Info (UI-CLEANUP; it was "More tips"). The keyboard's
 * shortcuts (I, the arrows, + and -) work in either state.
 *
 * The hint texts that name Map tools take the state (mapToolsWays) so they stay right when
 * the tools are not on the page.
 */

/**
 * Where the choice is kept: "on" or "off", and only "on" means on. High contrast keeps its own, older key,
 * `routemaker.accessibility` (lib/accessibilitySwitch.ts, stressStyle.js), and Large text its own
 * (lib/rideOutput.ts BIG_TEXT_KEY): a rider who turned only one of them on keeps it, with the mode off.
 */
export const ACCESS_MODE_KEY = "routemaker.accessMode";

/** The control's name in both states (a switch: the state is aria-pressed, not the name). */
export const ACCESS_LABEL = "Accessibility mode";
export const ACCESS_ON_SAID = "Accessibility mode on: high contrast, large text during a ride, and Map tools by the map's zoom buttons.";
export const ACCESS_OFF_SAID = "Accessibility mode off: high contrast and large ride text are off, and Map tools is hidden.";
/** The class on the page's root while the mode is on: Go's small text is drawn larger (styles.css). */
export const ACCESS_MODE_CLASS = "access-mode";
/** The owner's sentence for turning the mode on (OWNER-DECISIONS 455a(4)). */
export const ACCESS_SENTENCE = "For keyboard or screen reader use, turn on accessibility mode.";
/**
 * The same, with where the switch is, for the hints shown outside Points' Info (the search lede and
 * the lone-start hint), whose reader may be far below the page's first button.
 */
export const ACCESS_SENTENCE_WHERE = ACCESS_SENTENCE.replace(/\.$/, " (the first button on the page, or in Settings).");
/** The line beside the toggle in Points' Info and Settings: says where else the switch is. */
export const ACCESS_HELP = `${ACCESS_SENTENCE} It turns on high contrast, large text during a ride, and Map tools by the map's zoom buttons, and is kept on this device. It is also the first button on the page.`;
/** Settings' extra line under it: the two switches below it, which a rider can set apart. */
export const ACCESS_FINE_TUNE = "High contrast and Large text during a ride, below, can also be set on their own.";

/**
 * What one press of the mode's switch sets with it: High contrast and Large text during a ride go the same way
 * (on sets both on, off sets both off). Changing either of those switches leaves the mode and the other alone.
 */
export function accessModeParts(on: boolean): { contrast: boolean; largeText: boolean } {
  return { contrast: on, largeText: on };
}

/** What a screen reader hears after a press, with the state it went to. */
export function accessModeSaid(on: boolean): string {
  return on ? ACCESS_ON_SAID : ACCESS_OFF_SAID;
}

/**
 * One press of either switch, from the state `on`: the state it goes to, what is said, and whether the
 * focus then moves to Map tools. Only the page's first button moves it, and only when turning the mode
 * on (455a(2)); the Info and Settings toggles and turning it off leave the focus where it is.
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
export function mapToolsWays(on: boolean, go = false): { addPoint: string; roadAndAdd: string } {
  // Go names the button for what it does there (roadInfo.ts SET_END_AT_CENTRE_LABEL; lib/appMode.ts goTapSetsEnd).
  const add = go ? "Set destination at map center" : "Add point at map center";
  return on
    ? {
        addPoint: `use "${add}" in Map tools`,
        roadAndAdd: `open Map tools (by the map's zoom buttons) for Road info at map center and ${add}`,
      }
    : {
        // Shown only in Points' Info, whose own line (ACCESS_HELP) says where the switch is (the spec review's SF4).
        addPoint: `turn on accessibility mode, then use "${add}" in Map tools`,
        roadAndAdd: `turn on accessibility mode and open Map tools (by the map's zoom buttons) for Road info at map center and ${add}`,
      };
}
