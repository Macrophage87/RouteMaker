# Override re-match report

Written by the rebuild (`pipeline.rematch`, OWNER-DECISIONS 282). An approved override row names a way by id; where the id is no longer in the extract, the row is re-matched by the stored geometry and street name, and only when that is unambiguous. Every row that was missing is listed; a failed row is left unapplied and still counted as unmatched.

- Rows read: 1783; with a stored fingerprint: 1783
- Re-matched: 0; already covered by a row on the new way: 0; failed: 1; present but drifted: 0

| Kind | Old way | Outcome | New ways | Street | Reason |
|---|---|---|---|---|---|
| stress | 424993005 | failed |  | Harford Road | way 1562097553 of that name runs along part of it without lying along it (merged into a longer way, or redrawn); applying the row to the rest would guess |
