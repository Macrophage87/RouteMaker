/**
 * A note's or a stop's icon as the map and Plan's dialogs draw it (lib/iconStyle.ts): a Noto Emoji picture (our
 * default; Stephen 2026-11-10 "We can use noto"), or the phone's own emoji. The pictures are bundled files (Vite's
 * ?url), fetched only when a sign shows one and kept offline with the rest of the app; an <img> keeps each file's
 * own gradient ids to itself. Their source, sha256 and licence are in fixtures/icons/README.md and docs/SOURCES.md.
 */
import warning from "../icons/noto-emoji-u26a0.svg?url";
import pothole from "../icons/noto-emoji-u1f573.svg?url";
import traffic from "../icons/noto-emoji-u1f697.svg?url";
import construction from "../icons/noto-emoji-u1f6a7.svg?url";
import view from "../icons/noto-emoji-u1f3de.svg?url";
import photo from "../icons/noto-emoji-u1f4f7.svg?url";
import water from "../icons/noto-emoji-u1f4a7.svg?url";
import food from "../icons/noto-emoji-u1f374.svg?url";
import coffee from "../icons/noto-emoji-u2615.svg?url";
import restroom from "../icons/noto-emoji-u1f6bb.svg?url";
import bikeshop from "../icons/noto-emoji-u1f527.svg?url";
import pin from "../icons/noto-emoji-u1f4cd.svg?url";
import { useEffect, useState } from "react";
import { NOTE_ICONS, type NoteIcon } from "../lib/routeNotes.ts";
import { ICON_STYLE_EVENT, readIconStyle, type IconStyle } from "../lib/iconStyle.ts";

export const NOTO_ICON_URLS: Record<NoteIcon, string> = { warning, pothole, traffic, construction, view, photo, water, food, coffee, restroom, bikeshop, pin };

/** The icon as an element, hidden from screen readers (the sign or the choice beside it carries the words). */
export function iconArt(icon: NoteIcon, style: IconStyle = readIconStyle(), className = "icon-art"): HTMLElement {
  if (style === "emoji") {
    const span = document.createElement("span");
    span.className = `${className} icon-art-emoji`;
    span.textContent = NOTE_ICONS[icon];
    span.setAttribute("aria-hidden", "true");
    return span;
  }
  const img = document.createElement("img");
  img.className = className;
  img.src = NOTO_ICON_URLS[icon];
  img.alt = "";
  img.draggable = false;
  img.setAttribute("aria-hidden", "true");
  return img;
}

/** The style chosen in Settings, followed as it changes. */
export function useIconStyle(): IconStyle {
  const [style, setStyle] = useState<IconStyle>(() => readIconStyle());
  useEffect(() => {
    const changed = () => setStyle(readIconStyle());
    window.addEventListener(ICON_STYLE_EVENT, changed);
    return () => window.removeEventListener(ICON_STYLE_EVENT, changed);
  }, []);
  return style;
}

/** The icon in a React tree (Plan's note and stop dialogs). */
export function IconArt({ icon, style }: { icon: NoteIcon; style: IconStyle }) {
  return style === "emoji" ? (
    <span className="icon-art icon-art-emoji" aria-hidden="true">
      {NOTE_ICONS[icon]}
    </span>
  ) : (
    <img className="icon-art" src={NOTO_ICON_URLS[icon]} alt="" draggable={false} aria-hidden="true" />
  );
}
