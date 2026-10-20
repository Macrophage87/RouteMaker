/**
 * A stop's card (Stephen 2026-10-19: "when pressing on food or other stops provide information on what's there
 * including a link to the website if available. Then offer a route/detour here", and "don't auto route"): a press
 * on a food, sight, repair, water or restroom point, or on a lettered pin, opens this card and never routes by
 * itself. Most important first: the name, what it is and whether it is open, how far; then the one action and the
 * website. The action is Route here before there is a route and Add as stop (the detour) with one.
 */
import type { LonLat } from "./geo.ts";
import { openNow } from "./repair.ts";

export const ROUTE_HERE = "Route here";
export const ADD_AS_STOP = "Add as stop";

export interface StopAction {
  text: typeof ROUTE_HERE | typeof ADD_AS_STOP;
  run(): void;
}

/** What a stop's card offers for `point`, named `name`; null when it offers nothing (a ride under way). */
export type StopActionFor = (point: LonLat, name: string) => StopAction | null;

export interface StopCardWords {
  /** The name, first and bold. */
  title: string;
  /** What's there, open now, how far: one short line each. */
  lines: readonly string[];
  /** The place's own website, where OSM has one. */
  website?: string | null;
}

/** "Open now." or "Closed now." where the mapped hours can be read at `at`, else nothing (lib/repair.ts openNow). */
export function openNowText(hours: string | undefined, at: Date): string | null {
  if (!hours) return null;
  const open = openNow(hours, at);
  return open === true ? "Open now." : open === false ? "Closed now." : null;
}

/** A website only if it is a web address (http or https): mapped text is never followed as a script or an app link. */
export function safeWebsite(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

/**
 * The card as DOM: the words, then a row with the action (a button; `done` runs first, to close the card) and the
 * website (a link that opens in a new tab and says so to a screen reader).
 */
export function stopCardElement(words: StopCardWords, action: StopAction | null, done: () => void): HTMLElement {
  const body = document.createElement("div");
  body.className = "place-card";
  const title = document.createElement("strong");
  title.textContent = words.title;
  body.appendChild(title);
  for (const line of words.lines) {
    const p = document.createElement("p");
    p.textContent = line;
    body.appendChild(p);
  }
  const website = safeWebsite(words.website);
  if (!action && !website) return body;
  const row = document.createElement("div");
  row.className = "station-actions place-card-actions";
  if (action) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = action.text;
    button.setAttribute("aria-label", `${action.text}: ${words.title}`);
    button.addEventListener("click", () => {
      done();
      action.run();
    });
    row.appendChild(button);
  }
  if (website) {
    const a = document.createElement("a");
    a.href = website;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.className = "food-web";
    a.textContent = "Website";
    a.setAttribute("aria-label", `Website: ${words.title} (opens in a new tab)`);
    row.appendChild(a);
  }
  body.appendChild(row);
  return body;
}
