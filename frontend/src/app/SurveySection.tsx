// The Layers sheet's Survey spots section (lib/surveySpots.ts; the owner, 2026-11-25): one switch, off by default, its
// hint, and the signed-in rider's count (spots answered, and those answered on the day they rode there).
import { LayerSection } from "../lib/layerSection.ts";
import { SURVEY_HINT, SURVEY_LABEL } from "../lib/surveySpots.ts";

export interface SurveySectionProps {
  on: boolean;
  onChange: (on: boolean) => void;
  /** Why it cannot draw while on ("" when it can). */
  status: string;
  /** The rider's count line, or why there is none ("" while unknown). */
  count: string;
}

export function SurveySection({ on, onChange, status, count }: SurveySectionProps) {
  return (
    <LayerSection id="survey" title={SURVEY_LABEL} layers={[{ key: "survey", label: SURVEY_LABEL, on }]} onLayers={(next) => onChange(next.survey)} status={status}>
      <p className="hint">{SURVEY_HINT}</p>
      {count && <p className="hint survey-count">{count}</p>}
    </LayerSection>
  );
}
