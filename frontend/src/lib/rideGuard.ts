/** What a RideGuard (RideGuard.tsx) does with an error in its part: leave the part out during a ride or Roam, else pass it on. */
export function guardOutcome(onBike: boolean): "leave-out" | "pass-on" {
  return onBike ? "leave-out" : "pass-on";
}
