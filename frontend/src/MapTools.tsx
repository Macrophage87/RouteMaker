/**
 * "Map tools" (OWNER-DECISIONS 450; on the page only in accessibility mode, 455: App renders it
 * only then, and the mode's switch, the page's first button, moves the focus here when it turns
 * the mode on): one small visible button with the map's zoom buttons
 * that opens a short disclosure holding the two map-center actions, "Add point at map
 * center" and "Road info at map center". They were two wide buttons in the planner, which
 * pointer riders rarely need; they stay the keyboard's and a screen reader's way to add a
 * point and to the road panel without taking the planner's room.
 *
 * A disclosure, not an ARIA menu: a real button with `aria-expanded` that shows or hides
 * plain buttons after it, so Tab, VoiceOver and TalkBack swipes, and magnification all
 * meet ordinary buttons in the page's order (mobile screen readers handle role=menu
 * poorly; the a11y review's note on 450). Escape closes it and the focus goes back to Map
 * tools; so does choosing one of them, before the action runs, so the road panel gives the
 * focus back to Map tools when it closes. The crosshair shows the map's center while open.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import { ADD_AT_CENTRE_LABEL, INFO_BUTTON_LABEL, MAP_TOOLS_LABEL } from "./lib/roadInfo.ts";

interface Props {
  /** Put a point at the map's center (the next point of the plan). */
  onAddPoint: () => void;
  /** The plan has the most points it can: Add point is unavailable. */
  addDisabled: boolean;
  /** The road panel for the road at the map's center. */
  onRoadInfo: () => void;
  /** Show (or hide) the map's crosshair, the spot both act on. */
  onCrosshair: (on: boolean) => void;
  /** The Map tools button, for App to give the focus to when accessibility mode is turned on. */
  toggleRef?: RefObject<HTMLButtonElement | null>;
  /** Called once Map tools is on the page (the map may still be loading when the mode is turned on). */
  onShown?: () => void;
}

export function MapTools({ onAddPoint, addDisabled, onRoadInfo, onCrosshair, toggleRef: outerRef, onShown }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const ownRef = useRef<HTMLButtonElement>(null);
  const toggleRef = outerRef ?? ownRef;
  const panelId = useId();

  useEffect(() => {
    onCrosshair(open);
  }, [open, onCrosshair]);
  // Turned off with it open: the crosshair goes with it.
  useEffect(() => () => onCrosshair(false), [onCrosshair]);
  // On the page now: App may be waiting to give it the focus. Once, on mount (so no deps).
  useEffect(() => onShown?.(), []);

  // A press anywhere else closes it, as the focus leaving it does (onBlur below).
  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  const closeToToggle = () => {
    setOpen(false);
    toggleRef.current?.focus();
  };
  const run = (action: () => void) => {
    closeToToggle();
    action();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Escape" || !open) return;
    // Its own Escape: not also the map's (a stop's Remove, a junction card).
    event.preventDefault();
    event.stopPropagation();
    closeToToggle();
  };

  return (
    <div
      ref={rootRef}
      className="map-tools"
      onKeyDown={onKeyDown}
      onBlur={(event) => {
        const next = event.relatedTarget as Node | null;
        if (open && next && !rootRef.current?.contains(next)) setOpen(false);
      }}
    >
      <button
        ref={toggleRef}
        type="button"
        className="map-tools-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((on) => !on)}
      >
        {MAP_TOOLS_LABEL}
      </button>
      <div id={panelId} className="map-tools-panel" hidden={!open}>
        <button type="button" disabled={addDisabled} onClick={() => run(onAddPoint)}>
          {ADD_AT_CENTRE_LABEL}
        </button>
        <button type="button" aria-haspopup="dialog" onClick={() => run(onRoadInfo)}>
          {INFO_BUTTON_LABEL}
        </button>
      </div>
    </div>
  );
}
