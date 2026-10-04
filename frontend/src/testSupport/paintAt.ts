// A line layer's paint property for a feature at a zoom, evaluated by the
// style specification's own expression engine (a plain value is returned as
// it is), so a test can read what the map would draw.
import * as spec from "@maplibre/maplibre-gl-style-spec";

interface PaintLayer {
  id: string;
  paint: Record<string, unknown>;
}

export function paintAt(layer: PaintLayer, name: string, properties: Record<string, unknown> = {}, zoom = 14): unknown {
  const value = layer.paint[name];
  if (value === undefined || typeof value === "number" || typeof value === "string") return value;
  const definition = (spec.latest.paint_line as Record<string, unknown>)[name];
  const expression = spec.createExpression(value, definition as never);
  if (expression.result !== "success") throw new Error(`layers[${layer.id}].paint.${name}: ${JSON.stringify(expression.value)}`);
  const result = expression.value.evaluate({ zoom } as never, { type: 2, properties, geometry: [] } as never);
  return hexIfColour(result);
}

/** A colour the expression engine returns (channels 0-1) as the "#rrggbb" the palettes are written in. */
export function hexIfColour(value: unknown): unknown {
  const c = value as { r?: unknown; g?: unknown; b?: unknown; a?: unknown } | null;
  if (c && typeof c === "object" && typeof c.r === "number" && typeof c.g === "number" && typeof c.b === "number" && c.a === 1) {
    return `#${[c.r, c.g, c.b].map((n) => Math.round((n as number) * 255).toString(16).padStart(2, "0")).join("")}`;
  }
  return value;
}
