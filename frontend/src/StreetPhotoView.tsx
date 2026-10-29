/**
 * The road's street photo (v0.7.0; lib/streetPhoto.ts): the newest Mapillary photo facing along the road,
 * a link to Mapillary's viewer in a new tab, its date under it and in its alt text, and the credit. One
 * plain line where Mapillary has none; nothing where the server cannot look one up.
 *
 * The road panel's, and Review's (ReviewMode.tsx: on the road's card once it settles, never in the list's rows,
 * so a page of roads asks for no photos), which asks Review's own path (`path`). Each road's answer is asked
 * for once and kept (PHOTOS).
 */
import { useEffect, useState } from "react";
import { NO_PHOTO_TEXT, fetchStreetPhoto, makePhotoMemo, photoAlt, type PhotoAnswer, type PhotoPath } from "./lib/streetPhoto.ts";
import { t } from "./lib/i18n.ts";

/** Every road's photo, asked for once a session (a re-render, the road opened again or its row back in view asks nothing). */
const PHOTOS = makePhotoMemo();

interface Props {
  title: string;
  point: [number, number];
  wayId: number | null;
  path?: PhotoPath;
}

export function StreetPhotoView({ title, point, wayId, path = "/api/street-photo" }: Props) {
  const [lon, lat] = point;
  const [photo, setPhoto] = useState<PhotoAnswer>(() => PHOTOS.known(path, [lon, lat], wayId) ?? null);
  useEffect(() => {
    let live = true;
    setPhoto(PHOTOS.known(path, [lon, lat], wayId) ?? null);
    // Not cancelled when the road changes: the answer is kept for the next time the road is drawn.
    void PHOTOS.get(path, [lon, lat], wayId, () => fetchStreetPhoto(window.location.origin, [lon, lat], wayId, undefined, undefined, path)).then((answer) => {
      if (live) setPhoto(answer);
    });
    return () => {
      live = false;
    };
  }, [lon, lat, wayId, path]);
  if (photo === null) return null;
  if (photo === "none") return <p className="hint road-info-photo-none">{NO_PHOTO_TEXT}</p>;
  return (
    <figure className="road-info-photo">
      <a href={photo.viewer_url} target="_blank" rel="noopener noreferrer">
        <img src={photo.image_url} alt={photoAlt(title, photo)} width={1024} height={768} loading="lazy" referrerPolicy="no-referrer" />
        <span className="visually-hidden"> {t("(opens Mapillary in a new tab)")}</span>
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
