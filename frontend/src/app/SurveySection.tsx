// The Layers sheet's Survey spots section (lib/surveySpots.ts; the owner, 2026-11-25): one switch, off by default, its
// hint, the signed-in rider's count (spots answered, and those answered on the day they rode there), and a list of the
// spots near the map's centre as buttons, so a keyboard or screen reader reaches a spot's card too.
import { useState } from "react";
import { LayerSection } from "../lib/layerSection.ts";
import { SURVEY_HINT, SURVEY_LABEL, SURVEY_NEAR, type SurveySpot } from "../lib/surveySpots.ts";

export interface SurveySectionProps {
  on: boolean;
  onChange: (on: boolean) => void;
  /** Why it cannot draw while on ("" when it can). */
  status: string;
  /** The rider's count line, or why there is none ("" while unknown). */
  count: string;
  /** The spots nearest the map's centre, nearest first (none while the layer is off or loading). */
  near?: () => SurveySpot[];
  onPick?: (spot: SurveySpot) => void;
}

export function SurveySection({ on, onChange, status, count, near, onPick }: SurveySectionProps) {
  const [listed, setListed] = useState<SurveySpot[] | null>(null);
  return (
    <LayerSection id="survey" title={SURVEY_LABEL} layers={[{ key: "survey", label: SURVEY_LABEL, on }]} onLayers={(next) => onChange(next.survey)} status={status}>
      <p className="hint">{SURVEY_HINT}</p>
      {count && <p className="hint survey-count">{count}</p>}
      {on && near && onPick && (
        <>
          <button type="button" className="link" onClick={() => setListed(near())}>
            {SURVEY_NEAR}
          </button>
          {listed && listed.length > 0 && (
            <ul className="survey-near">
              {listed.map((spot) => (
                <li key={spot.id}>
                  <button type="button" className="link" onClick={() => onPick(spot)}>
                    {spot.road}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </LayerSection>
  );
}
