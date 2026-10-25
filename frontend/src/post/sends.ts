/**
 * A Featured routes post's Send to Garmin and Send to Wahoo (postPage.tsx gives each its send). What a press did
 * shows in a popup over the page (the owner, 2026-10-25: "Maybe a popup that it saved or something. Because it saved
 * 10 times"): a line under the buttons went unseen, so a rider pressed again and sent the course again. A button is
 * off while its send is under way and stays off once it has sent, so one press sends once; a send that failed turns
 * it back on to try again.
 */

export const SENDING_SAID = "Sending…";
export const SEND_FAILED = "The course could not be sent. Try again.";
/** How long a send's popup stays up, unless tapped away. */
export const POPUP_MS = 10_000;

export function wireSends(
  doc: Pick<Document, "querySelectorAll">,
  said: HTMLElement | null,
  sends: Record<string, () => Promise<string>>,
  later: (run: () => void, ms: number) => unknown = setTimeout,
): void {
  let shown = 0;
  const hide = () => said?.classList.remove("popup");
  // Tapped away, or gone by itself; a screen reader has read it already (the line is a status).
  said?.addEventListener("click", hide);
  const say = (words: string, popup: boolean) => {
    if (!said) return;
    said.textContent = words;
    said.classList.toggle("popup", popup);
    const now = ++shown;
    // Only the latest popup's own time hides it.
    if (popup) later(() => now === shown && hide(), POPUP_MS);
  };
  for (const button of doc.querySelectorAll<HTMLButtonElement>("button[data-send]")) {
    const send = sends[button.dataset.send ?? ""];
    if (!send) continue;
    button.disabled = false;
    button.addEventListener("click", () => {
      if (button.disabled) return;
      button.disabled = true;
      say(SENDING_SAID, false);
      send().then(
        (words) => say(words, true),
        () => {
          button.disabled = false;
          say(SEND_FAILED, true);
        },
      );
    });
  }
}
