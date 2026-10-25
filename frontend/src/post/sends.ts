/**
 * A Featured routes post's Send to Garmin and Send to Wahoo (postPage.tsx gives each its send). What a press did
 * shows in a popup over the page (the owner, 2026-10-25: "Maybe a popup that it saved or something. Because it saved
 * 10 times"): the line under the buttons alone went unseen, so a rider pressed again and sent the course again. While
 * a send is under way, its button says so and another press does nothing; once the popup has said what happened, the
 * button works again (a rider who closed the share sheet can try again).
 *
 * The line under the buttons keeps the words for screen readers (it is a status); the popup shows the same words
 * over the page, hidden from them, so nothing is said twice and the page does not move.
 */

export const SENDING_SAID = "Sending…";
export const SEND_FAILED = "The course could not be sent. Try again.";
/** How long a send's popup stays up, unless tapped away. */
export const POPUP_MS = 10_000;

export function wireSends(
  doc: Pick<Document, "querySelectorAll" | "createElement" | "body">,
  said: HTMLElement | null,
  sends: Record<string, () => Promise<string>>,
  later: (run: () => void, ms: number) => unknown = setTimeout,
): void {
  const popup = doc.createElement("div");
  popup.className = "send-popup";
  popup.hidden = true;
  popup.setAttribute("aria-hidden", "true");
  popup.addEventListener("click", () => (popup.hidden = true));
  doc.body.append(popup);
  let shown = 0;
  const say = (words: string, pop: boolean) => {
    if (said) said.textContent = words;
    popup.textContent = words;
    popup.hidden = !pop;
    const now = ++shown;
    // Only the latest popup's own time hides it.
    if (pop) later(() => now === shown && (popup.hidden = true), POPUP_MS);
  };
  for (const button of doc.querySelectorAll<HTMLButtonElement>("button[data-send]")) {
    const send = sends[button.dataset.send ?? ""];
    if (!send) continue;
    button.disabled = false;
    button.addEventListener("click", () => {
      // aria-disabled, not disabled: the button keeps a keyboard rider's focus.
      if (button.getAttribute("aria-disabled") === "true") return;
      button.setAttribute("aria-disabled", "true");
      say(SENDING_SAID, false);
      send()
        .then(
          (words) => say(words, true),
          () => say(SEND_FAILED, true),
        )
        .finally(() => button.removeAttribute("aria-disabled"));
    });
  }
}
