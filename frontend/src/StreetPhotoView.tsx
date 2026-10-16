/**
 * The road's street photo (v0.7.0; lib/streetPhoto.ts): the newest Mapillary photo facing along the road,
 * a link to Mapillary's viewer in a new tab, its date under it and in its alt text, and the credit. One
 * plain line where Mapillary has none; nothing where the server cannot look one up.
 *
 * The road panel's, and Review's (ReviewMode.tsx: a small one in each row of a list, a full one on the road's
 * card), which asks Review's own path (`path`) and, in a row (`compact`), only once the row is on screen.
 */
import { useEffect, useRef, useState } from "react";
import { NO_PHOTO_TEXT, fetchStreetPhoto, photoAlt, type PhotoAnswer, type PhotoPath } from "./lib/streetPhoto.ts";

interface Props {
  title: string;
  point: [number, number];
  wayId: number | null;
  path?: PhotoPath;
  /** A table row's: a thumbnail, asked for once it is scrolled into view. */
  compact?: boolean;
}

export function StreetPhotoView({ title, point, wayId, path = "/api/street-photo", compact = false }: Props) {
  const [photo, setPhoto] = useState<PhotoAnswer>(null);
  const [seen, setSeen] = useState(!compact);
  const here = useRef<HTMLDivElement>(null);
  const [lon, lat] = point;
  useEffect(() => {
    if (seen || !here.current) return;
    if (typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const watch = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) setSeen(true);
    });
    watch.observe(here.current);
    return () => watch.disconnect();
  }, [seen]);
  useEffect(() => {
    if (!seen) return;
    const controller = new AbortController();
    setPhoto(null);
    void fetchStreetPhoto(window.location.origin, [lon, lat], wayId, controller.signal, undefined, path).then((answer) => {
      if (!controller.signal.aborted) setPhoto(answer);
    });
    return () => controller.abort();
  }, [lon, lat, wayId, path, seen]);
  if (photo === null) return compact ? <div ref={here} className="review-photo-wait" /> : null;
  if (photo === "none") return <p className={compact ? "hint review-photo-none" : "hint road-info-photo-none"}>{NO_PHOTO_TEXT}</p>;
  return (
    <figure className={compact ? "road-info-photo review-photo-small" : "road-info-photo"}>
      <a href={photo.viewer_url} target="_blank" rel="noopener noreferrer">
        <img src={photo.image_url} alt={photoAlt(title, photo)} width={1024} height={768} loading="lazy" referrerPolicy="no-referrer" />
        <span className="visually-hidden"> (opens Mapillary in a new tab)</span>
      </a>
      <figcaption className="hint">
        {photo.date_words}
        {photo.creator ? `, by ${photo.creator}` : ""} ·{" "}
        <a href={photo.credit_url} target="_blank" rel="noopener noreferrer">
          {photo.credit}
        </a>{" "}
        (
        <a href={photo.licence_url} target="_blank" rel="noopener noreferrer">
          {photo.licence}
        </a>
        )
      </figcaption>
    </figure>
  );
}
