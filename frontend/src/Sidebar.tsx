/**
 * The sidebar redesign's small parts (OWNER-DECISIONS 312, mockup v3): the
 * "More tips" toggle, the Ride line that opens the ride settings, the folds
 * (native <details>) of the route summary, the quick figures, the bottom bar
 * and the sheet it opens. Kept out of App.tsx, which places them.
 *
 * Every one is a real button or a real <details>, 44 px high at least, with its
 * state in aria-expanded (or the element's own) and its words in text; none
 * depends on colour. A sheet takes the focus to its heading when it opens, and
 * the Back button (or Escape) takes it back to the bar button that opened it.
 */
import { useId, useState, type KeyboardEvent, type ReactNode, type Ref } from "react";
import { BAR_ITEMS, FEWER_TIPS, MORE_TIPS, rideActionLabel, type BarItem, type PanelView } from "./lib/sidebar.ts";
import type { QuickFigure } from "./lib/quickFigures.ts";

/** Help that is not needed every time, behind a toggle (the mockup's "More tips"). */
export function MoreTips({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="more-tips">
      <button type="button" className="link tips-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        {open ? FEWER_TIPS : MORE_TIPS}
      </button>
      <div id={id} className="tips-body" hidden={!open}>
        {children}
      </div>
    </div>
  );
}

/**
 * The Ride line: one line saying how the ride is set, and Edit, which opens the
 * controls (`children`). A heading holds the button, so a screen reader can
 * jump to it. The controls stay in the page while closed (hidden), so nothing
 * they hold is lost.
 */
export function RideSettings({ summary, spoken, children }: { summary: string; spoken: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  return (
    <section className="ride-settings" aria-labelledby="ride-settings-heading">
      <h2 id="ride-settings-heading" className="ride-line">
        <button type="button" className="ride-line-button" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen(!open)}>
          <span className="ride-line-text">
            <span className="ride-line-label">Ride</span>
            <span className="ride-line-summary" aria-hidden="true">
              {summary}
            </span>
            <span className="visually-hidden">: {spoken}.</span>
          </span>
          <span className="ride-line-action">{rideActionLabel(open)}</span>
        </button>
      </h2>
      <div id={bodyId} className="ride-settings-body" hidden={!open}>
        {children}
      </div>
    </section>
  );
}

/** A collapsible section of the route summary: a native disclosure, closed unless `open`. */
export function Fold({ title, open, className, children }: { title: string; open?: boolean; className?: string; children: ReactNode }) {
  return (
    <details className={className ? `fold ${className}` : "fold"} open={open}>
      <summary>{title}</summary>
      <div className="fold-body">{children}</div>
    </details>
  );
}

/** The four quick figures: a label and a figure each, as a description list. */
export function QuickFigures({ figures }: { figures: readonly QuickFigure[] }) {
  return (
    <dl className="quick-figures">
      {figures.map((figure) => (
        <div key={figure.key} className={`quick-figure quick-${figure.key}`}>
          <dt>{figure.label}</dt>
          <dd>{figure.value}</dd>
        </div>
      ))}
    </dl>
  );
}

const ICONS: Record<BarItem["id"], ReactNode> = {
  layers: <path d="M12 3 3 8l9 5 9-5-9-5zM3 13l9 5 9-5" />,
  legend: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v4M12 16h.01" />
    </>
  ),
  gpx: <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />,
  about: (
    <>
      <circle cx="12" cy="8" r="3" />
      <path d="M5 21c0-4 3-6 7-6s7 2 7 6" />
    </>
  ),
};

/** The bottom bar: real buttons, each with an icon (hidden from screen readers) and its words. */
export function BottomBar({
  view,
  legend,
  onOpen,
  buttonRef,
}: {
  view: PanelView;
  /** Whether the layers sheet was opened by Legend, so that button is the current one. */
  legend: boolean;
  onOpen: (item: BarItem) => void;
  buttonRef: (id: BarItem["id"], button: HTMLButtonElement | null) => void;
}) {
  return (
    <nav aria-label="More" className="bottom-bar">
      {BAR_ITEMS.map((item) => {
        const current = view === item.opens && (item.id !== "layers" || !legend) && (item.id !== "legend" || legend);
        return (
          <button
            key={item.id}
            type="button"
            ref={(button) => buttonRef(item.id, button)}
            className="bar-button"
            aria-current={current ? "true" : undefined}
            aria-describedby={`bar-${item.id}-hint`}
            onClick={() => onOpen(item)}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              {ICONS[item.id]}
            </svg>
            <span>{item.label}</span>
            <span id={`bar-${item.id}-hint`} className="visually-hidden">
              {item.description}
            </span>
          </button>
        );
      })}
    </nav>
  );
}

/**
 * One of the bottom bar's sheets: a header with a Back button and a heading,
 * over its content. It stays in the page when hidden, so what it holds (the
 * opened GPX file, the switches) keeps its state.
 */
export function SheetFrame({
  id,
  title,
  open,
  onBack,
  headingRef,
  children,
}: {
  id: string;
  title: string;
  open: boolean;
  onBack: () => void;
  headingRef: Ref<HTMLHeadingElement>;
  children: ReactNode;
}) {
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    // Escape inside a nested dialog or the place search's list is theirs, not the sheet's.
    if (event.key !== "Escape" || event.defaultPrevented) return;
    const target = event.target as HTMLElement;
    if (target.closest("dialog") || target.getAttribute("role") === "combobox") return;
    event.preventDefault();
    onBack();
  };
  return (
    <section id={id} className="sheet" aria-labelledby={`${id}-title`} hidden={!open} onKeyDown={onKeyDown}>
      <header className="sheet-header">
        <button type="button" className="sheet-back" aria-label="Back to the planner" onClick={onBack}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <h2 id={`${id}-title`} ref={headingRef} tabIndex={-1}>
          {title}
        </h2>
      </header>
      {children}
    </section>
  );
}
