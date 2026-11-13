/**
 * Render a component into a DOM in Node and look at it as a rider would: by role, by label and by the text shown.
 * The DOM is happy-dom's; the .tsx files come through tsxHooks.mjs (loaded by `npm test`).
 *
 *   import { render, click } from "./testSupport/render.ts";
 *   const screen = await render(<RideTypePicker ... />);   // in a .test.tsx file
 *   await click(screen.button("Change"));
 *   assert.ok(screen.dialog());
 *
 * A test of what the rider sees goes here, not in a readFileSync of App.tsx, RideMode.tsx or styles.css: those
 * pass while the screen is broken and fail when working code is only reformatted (frontend/TESTING.md).
 */
import { after, afterEach } from "node:test";
import { Window } from "happy-dom";
import type { ReactNode } from "react";

const window = new Window({ url: "http://localhost/", width: 390, height: 844 });
// The page's globals, as a browser has them, for React and for the component under test. Node's own (fetch, URL,
// timers, ...) stay.
for (const key of Object.getOwnPropertyNames(window)) {
  if (key in globalThis) continue;
  try {
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value: (window as unknown as Record<string, unknown>)[key] });
  } catch {
    // A getter happy-dom does not let be read from outside: no component here needs it.
  }
}
// The DOM's own events, not Node's, so a component's `new Event(...)` dispatches on happy-dom's nodes.
for (const key of ["Event", "CustomEvent", "KeyboardEvent", "MouseEvent", "FocusEvent", "InputEvent", "PointerEvent", "window", "document", "navigator", "localStorage", "sessionStorage", "location", "getComputedStyle", "requestAnimationFrame", "cancelAnimationFrame", "matchMedia"]) {
  const value = key === "window" ? window : (window as unknown as Record<string, unknown>)[key];
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value: typeof value === "function" ? value.bind(window) : value });
}
after(() => window.happyDOM.close());
// React's own switch for act() outside a test framework it knows.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const { act } = await import("react");
const { createRoot } = await import("react-dom/client");

/** The text a screen reader reads from an element: its text, leaving out what is aria-hidden or hidden. */
export function spokenText(node: Node): string {
  if (node.nodeType === 3) return node.textContent ?? "";
  if (node.nodeType !== 1) return "";
  const el = node as Element;
  if (el.getAttribute("aria-hidden") === "true" || el.hasAttribute("hidden")) return "";
  return [...el.childNodes].map(spokenText).join("");
}

/** An element's accessible name, near enough for a test: aria-label, aria-labelledby, else its spoken text. */
export function nameOf(el: Element): string {
  const label = el.getAttribute("aria-label");
  if (label) return label.trim();
  const by = el.getAttribute("aria-labelledby");
  const text = by ? by.split(/\s+/).map((id) => { const at = document.getElementById(id); return at ? spokenText(at) : ""; }).join(" ") : spokenText(el);
  return text.replace(/\s+/g, " ").trim();
}

/** Whether an element is shown: not hidden by the hidden attribute or aria-hidden on it or a parent. */
export function shown(el: Element): boolean {
  for (let at: Element | null = el; at; at = at.parentElement) {
    if (at.hasAttribute("hidden") || at.getAttribute("aria-hidden") === "true") return false;
    if (at.tagName === "DIALOG" && !at.hasAttribute("open")) return false;
  }
  return true;
}

const ROLES: Record<string, string> = {
  button: 'button, [role="button"], input[type="button"], input[type="submit"]',
  checkbox: 'input[type="checkbox"], [role="checkbox"], [role="switch"]',
  dialog: 'dialog, [role="dialog"], [role="alertdialog"]',
  heading: "h1, h2, h3, h4, h5, h6, [role=heading]",
  link: "a[href], [role=link]",
  radio: 'input[type="radio"], [role="radio"]',
  searchbox: 'input[type="search"], [role="searchbox"]',
  textbox: 'input:not([type]), input[type="text"], textarea, [role="textbox"]',
};

export interface Screen {
  container: HTMLElement;
  /** Every shown element of a role (button, dialog, heading, ...) whose name matches, in page order. */
  all(role: string, name?: string | RegExp): HTMLElement[];
  /** The one shown element of a role whose name matches; fails if there is none or more than one. */
  get(role: string, name?: string | RegExp): HTMLElement;
  button(name?: string | RegExp): HTMLElement;
  dialog(name?: string | RegExp): HTMLElement;
  /** The page's shown text, spaces collapsed. */
  text(): string;
  rerender(ui: ReactNode): Promise<void>;
  unmount(): Promise<void>;
}

function matches(name: string, want: string | RegExp | undefined): boolean {
  if (want === undefined) return true;
  return typeof want === "string" ? name === want : want.test(name);
}

/** What each test rendered, unmounted after it (pass or fail), so no test sees another's screen. */
const mounted = new Set<Screen>();
afterEach(async () => {
  for (const screen of [...mounted]) await screen.unmount();
});

/** Renders `ui` into a fresh container on the page and returns ways to look at it. Unmounted after the test. */
export async function render(ui: ReactNode): Promise<Screen> {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(ui));
  const all = (role: string, name?: string | RegExp): HTMLElement[] => {
    const selector = ROLES[role] ?? `[role="${role}"]`;
    // A dialog lives where React put it, sometimes outside the container (a portal): look over the whole page.
    return [...document.body.querySelectorAll<HTMLElement>(selector)].filter((el) => shown(el) && matches(nameOf(el), name));
  };
  const get = (role: string, name?: string | RegExp): HTMLElement => {
    const found = all(role, name);
    if (found.length !== 1) throw new Error(`expected one ${role}${name === undefined ? "" : ` named ${String(name)}`}, found ${found.length}: ${found.map(nameOf).join(" | ")}`);
    return found[0];
  };
  const screen: Screen = {
    container,
    all,
    get,
    button: (name) => get("button", name),
    dialog: (name) => get("dialog", name),
    text: () => (container.textContent ?? "").replace(/\s+/g, " ").trim(),
    rerender: async (next) => act(async () => root.render(next)),
    unmount: async () => {
      if (!mounted.delete(screen)) return;
      await act(async () => root.unmount());
      container.remove();
    },
  };
  mounted.add(screen);
  return screen;
}

/** Clicks an element as a rider's tap would, and lets React finish what it starts. */
export async function click(el: Element): Promise<void> {
  await act(async () => {
    (el as HTMLElement).click();
  });
}

/** Types into a text box (its whole value), firing the input event React listens for. */
export async function type(el: Element, value: string): Promise<void> {
  await act(async () => {
    const input = el as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value")?.set;
    setter?.call(input, value);
    input.dispatchEvent(new window.Event("input", { bubbles: true }) as unknown as Event);
  });
}

/** Presses a key on an element (keydown), as the keyboard would. */
export async function press(el: Element, key: string): Promise<void> {
  await act(async () => {
    el.dispatchEvent(new window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }) as unknown as Event);
  });
}
