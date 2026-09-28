/**
 * The rail stations' two cards as state, apart from the DOM that draws them
 * (railInteraction.ts), so a test can run them against a stand-in view: the
 * hover card, shown for the station under the pointer, and the tap card,
 * opened by a click, which the hover card never covers.
 */

/** An open card, as the view made it. */
export interface CardHandle {
  isOpen(): boolean;
  remove(): void;
}

export interface RailCardView<F> {
  /** What distinguishes one hover card from another. */
  key(found: F): string;
  showHover(found: F, lineHint: boolean): void;
  hideHover(): void;
  openCard(found: F): CardHandle;
}

export class RailCards<F> {
  private hovered = "";
  private card: CardHandle | null = null;
  private readonly view: RailCardView<F>;

  constructor(view: RailCardView<F>) {
    this.view = view;
  }

  /** Whether a tap card is open - not once it has closed itself (Escape, its close button, an action). */
  cardOpen(): boolean {
    return this.card?.isOpen() ?? false;
  }

  /** The hover card for `found`, or none; never while a tap card is open, and built only when it changes. */
  hover(found: F | null, lineHint = false): void {
    const key = found !== null && !this.cardOpen() ? `${this.view.key(found)}|${lineHint ? "line" : ""}` : "";
    if (key === this.hovered) return;
    this.hovered = key;
    if (found === null || key === "") this.view.hideHover();
    else this.view.showHover(found, lineHint);
  }

  /** Open the tap card for `found`, in place of any other card. */
  open(found: F): void {
    this.hover(null);
    this.close();
    this.card = this.view.openCard(found);
  }

  /** Close the tap card, if one is open; whether one was. */
  close(): boolean {
    const open = this.cardOpen();
    this.card?.remove();
    this.card = null;
    return open;
  }
}
