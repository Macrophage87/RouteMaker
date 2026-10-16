/**
 * Share as image (lib/shareCard.ts; the owner, 2026-10-16): opened from "Share as image" beside Share in Plan's
 * More. The platform's modal <dialog>, as the closure and road-info dialogs are: the page behind is inert, Escape
 * closes it, the focus starts on its heading and goes back to the button on close. In it: the size, Elevation
 * profile (on by default where the route has elevation) with "Draw it on the map", QR code (off by default), the
 * preview with a text alternative describing the route, and Download, with Share where the browser can share an
 * image file. "Image ready" and the errors are said through a polite status region inside the dialog, always
 * rendered: the page's own region is outside the modal, which makes it inert (RoadInfoDialog's note, review S1).
 */
import { useEffect, useId, useRef, useState } from "react";
import type { RouteProfile } from "./lib/api.ts";
import type { LonLat } from "./lib/geo.ts";
import type { Home } from "./lib/myGo.ts";
import {
  CARD_SIZES,
  CARD_SIZE_DEFAULT,
  CLOSE_LABEL,
  DOWNLOAD_LABEL,
  HOME_TOO_SHORT,
  IMAGE_DOWNLOADED,
  IMAGE_FAILED,
  IMAGE_MAKING,
  IMAGE_READY,
  IMAGE_SHARE_FAILED,
  PROFILE_LABEL,
  PROFILE_NONE,
  PROFILE_ON_MAP_LABEL,
  QR_LABEL,
  QR_LINK_FAILED,
  SHARE_FILE_LABEL,
  SHARE_IMAGE_LABEL,
  SIZE_LABEL,
  cardAlt,
  cardFileName,
  cardName,
  cardRoute,
  cardSize,
  homeEnd,
  qrAvailability,
  type CardSizeId,
} from "./lib/shareCard.ts";
import { renderCard } from "./app/shareCardRender.ts";

export interface ShareCardSource {
  line: LonLat[];
  points: LonLat[];
  home: Home | null;
  /** An opened file's or saved route's own name; null for a planned route. */
  name: string | null;
  distanceM: number;
  climbM: number | null;
  profile: RouteProfile | null;
}

export interface ShareCardDialogProps {
  open: boolean;
  source: ShareCardSource | null;
  /** The route shown is the plan's (no re-plan pending), or an unedited opened file: its exact line can be shared. */
  settled: boolean;
  /** The shared link, made as Share makes it (the exact line kept, the rider's keep choice); null if it could not be. */
  makeLink: () => Promise<string | null>;
  onClose: () => void;
}

interface Preview {
  url: string;
  blob: Blob;
  alt: string;
  size: CardSizeId;
}

/** Whether the browser's share sheet takes this image file. */
function canShareFile(file: File): boolean {
  try {
    return typeof navigator.share === "function" && typeof navigator.canShare === "function" && navigator.canShare({ files: [file] });
  } catch {
    return false;
  }
}

export function ShareCardDialog({ open, source, settled, makeLink, onClose }: ShareCardDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const opener = useRef<Element | null>(null);
  const id = useId();
  const [size, setSize] = useState<CardSizeId>(CARD_SIZE_DEFAULT);
  const hasProfile = source?.profile != null;
  const [profileOn, setProfileOn] = useState(true);
  const [onMap, setOnMap] = useState(false);
  const [qrOn, setQrOn] = useState(false);
  const [qrLink, setQrLink] = useState<string | null>(null);
  const [qrNote, setQrNote] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [said, setSaid] = useState({ text: "", count: 0 });
  const say = (text: string) => setSaid((s) => ({ text, count: s.count + 1 }));
  const [online, setOnline] = useState(() => navigator.onLine !== false);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine !== false);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  const qr = qrAvailability({ online, settled, homeEnd: source ? homeEnd(source.line, source.points, source.home) : false });
  const drawnRoute = source ? cardRoute(source.line, source.points, source.home) : null;
  const name = source ? cardName(source.name, source.home) : null;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal?.();
      headingRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
    }
  }, [open]);

  // A new route, or the dialog closed: the QR code's link is made again when next asked for.
  useEffect(() => {
    setQrOn(false);
    setQrLink(null);
    setQrNote(null);
  }, [source?.line, open]);

  // The preview, drawn again whenever a choice changes. One draw at a time (each is a map of its own, and a phone
  // has few to spare): a change while one is drawing waits for it, and only the latest change is drawn.
  const draws = useRef(0);
  const drawing = useRef<Promise<unknown>>(Promise.resolve());
  // The QR code turned on, and still available (a page gone offline since keeps the link it made).
  const qrWanted = qrOn && qr.ok;
  const qrDrawn = qrWanted && qrLink !== null;
  useEffect(() => {
    if (!open || !source || !drawnRoute) return;
    if (qrWanted && qrLink === null) return;
    const draw = ++draws.current;
    setBusy(true);
    setFailed(false);
    const place = hasProfile && profileOn ? (onMap ? "map" : "band") : "off";
    const next = drawing.current.then(() => {
      if (draw !== draws.current) return null;
      return renderCard({
        size: cardSize(size),
        route: drawnRoute,
        name,
        distanceM: source.distanceM,
        climbM: source.climbM,
        profile: source.profile,
        profilePlace: place,
        qrLink: qrDrawn ? qrLink : null,
      });
    });
    drawing.current = next.catch(() => undefined);
    next.then(
      (drawn) => {
        if (draw !== draws.current || !drawn) return;
        const { blob, strip } = drawn;
        const alt = cardAlt({
          name,
          distanceM: source.distanceM,
          climbM: source.climbM,
          stops: drawnRoute.stops.length,
          startShown: drawnRoute.start !== null,
          finishShown: drawnRoute.finish !== null,
          profile: strip,
          qr: qrDrawn,
        });
        setPreview((before) => {
          if (before) URL.revokeObjectURL(before.url);
          return { url: URL.createObjectURL(blob), blob, alt, size };
        });
        setBusy(false);
        say(IMAGE_READY);
      },
      () => {
        if (draw !== draws.current) return;
        // No image left that does not match the choices shown.
        setPreview((before) => {
          if (before) URL.revokeObjectURL(before.url);
          return null;
        });
        setBusy(false);
        setFailed(true);
        say(IMAGE_FAILED);
      },
    );
    // drawnRoute and name follow source (App memoises it).
  }, [open, source, size, profileOn, onMap, qrWanted, qrLink]);

  // Closed: the image is let go.
  useEffect(() => {
    if (open) return;
    draws.current += 1;
    setBusy(false);
    setPreview((before) => {
      if (before) URL.revokeObjectURL(before.url);
      return null;
    });
  }, [open]);

  const toggleQr = async (on: boolean) => {
    setQrNote(null);
    if (!on) {
      setQrOn(false);
      return;
    }
    setQrOn(true);
    if (qrLink) return;
    // Download and Share wait for the link, so an image without the code is not saved by mistake.
    setBusy(true);
    const link = await makeLink();
    if (link) setQrLink(link);
    else {
      setBusy(false);
      setQrOn(false);
      setQrNote(QR_LINK_FAILED);
      say(QR_LINK_FAILED);
    }
  };

  const file = preview ? new File([preview.blob], cardFileName(preview.size), { type: "image/png" }) : null;
  const shareable = file !== null && canShareFile(file);
  const download = () => {
    if (!preview) return;
    const a = document.createElement("a");
    a.href = preview.url;
    a.download = cardFileName(preview.size);
    document.body.appendChild(a);
    a.click();
    a.remove();
    say(IMAGE_DOWNLOADED);
  };
  // Called inside the press, before any await, so the share sheet opens.
  const share = () => {
    if (!file) return;
    navigator.share({ files: [file], title: SHARE_IMAGE_LABEL }).catch((error: { name?: string }) => {
      if (error?.name !== "AbortError") say(IMAGE_SHARE_FAILED);
    });
  };

  const qrDisabled = !qr.ok;
  const qrWhy = !qr.ok ? qr.why : qrNote;
  return (
    <dialog
      ref={dialogRef}
      className="share-card-dialog"
      aria-labelledby={`${id}-heading`}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <h2 id={`${id}-heading`} ref={headingRef} tabIndex={-1}>
        {SHARE_IMAGE_LABEL}
      </h2>
      {/* Always in the dialog, empty at first: a region created holding its text is often not spoken. */}
      <p className="visually-hidden" role="status">
        {said.text}
        {said.count % 2 === 1 ? " " : ""}
      </p>
      {open && source && !drawnRoute && <p className="notice">{HOME_TOO_SHORT}</p>}
      {open && source && drawnRoute && (
        <>
          <div className="share-card-choices">
            <label htmlFor={`${id}-size`}>{SIZE_LABEL}</label>
            <select id={`${id}-size`} value={size} onChange={(event) => setSize(event.target.value as CardSizeId)}>
              {CARD_SIZES.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
            <div className="share-card-check">
              <input
                id={`${id}-profile`}
                type="checkbox"
                checked={hasProfile && profileOn}
                disabled={!hasProfile}
                aria-describedby={hasProfile ? undefined : `${id}-profile-why`}
                onChange={(event) => setProfileOn(event.target.checked)}
              />
              <label htmlFor={`${id}-profile`}>{PROFILE_LABEL}</label>
            </div>
            <div className="share-card-check share-card-sub">
              <input
                id={`${id}-onmap`}
                type="checkbox"
                checked={hasProfile && profileOn && onMap}
                disabled={!hasProfile || !profileOn}
                aria-describedby={hasProfile ? undefined : `${id}-profile-why`}
                onChange={(event) => setOnMap(event.target.checked)}
              />
              <label htmlFor={`${id}-onmap`}>{PROFILE_ON_MAP_LABEL}</label>
            </div>
            {!hasProfile && (
              <p id={`${id}-profile-why`} className="hint">
                {PROFILE_NONE}
              </p>
            )}
            <div className="share-card-check">
              <input
                id={`${id}-qr`}
                type="checkbox"
                checked={qrOn && !qrDisabled}
                disabled={qrDisabled}
                aria-describedby={qrWhy ? `${id}-qr-why` : undefined}
                onChange={(event) => void toggleQr(event.target.checked)}
              />
              <label htmlFor={`${id}-qr`}>{QR_LABEL}</label>
            </div>
            {qrWhy && (
              <p id={`${id}-qr-why`} className="hint">
                {qrWhy}
              </p>
            )}
          </div>
          <div className="share-card-preview" aria-busy={busy}>
            {preview ? <img src={preview.url} alt={preview.alt} /> : <p className="hint">{failed ? IMAGE_FAILED : IMAGE_MAKING}</p>}
            {busy && preview && (
              <p className="hint" aria-hidden="true">
                {IMAGE_MAKING}
              </p>
            )}
          </div>
        </>
      )}
      <div className="share-card-actions">
        <button type="button" className="primary" onClick={download} disabled={!preview || busy}>
          {DOWNLOAD_LABEL}
        </button>
        {shareable && (
          <button type="button" className="secondary" onClick={share} disabled={busy}>
            {SHARE_FILE_LABEL}
          </button>
        )}
        <button type="button" className="secondary" onClick={onClose}>
          {CLOSE_LABEL}
        </button>
      </div>
    </dialog>
  );
}
