# Access overrides decided outside the admin

Approved `Override` rows are the plan's one audited path for correcting OSM's
access tags (`pipeline.overrides.load_approved` reads nothing else, and the
rebuild's `APPLY_OVERRIDES` stage applies them). Most rows are entered in the
admin. A correction the owner decides in conversation is checked in here
instead, as a versioned file, so its wording and date are reviewed with the
change and survive in the row's `reason` and `evidence`.

A file is `{"version": 1, "decided": ..., "rows": [...]}`, each row
`{"kind": "access", "osm_way_id": ..., "value": {tag: value}, "reason": ...,
"evidence": ...}`. `value` may write only the keys an access override may
(`pipeline.overrides.ACCESS_KEYS`).

`manage.py load_access_overrides` loads one. It is dry unless `--confirm` is
passed, attributes the rows to the instance admin named by `--actor` (a Discord
user id; any other account is refused and the refusal audited), and writes what
the admin path writes: the row, approved, and an audit entry for the add and
for the approval. It is idempotent - a row already approved with the same kind,
way and value is left alone - and refuses the whole file, before writing, on a
malformed row, a key outside `ACCESS_KEYS`, a way named twice, or an approved
row on the same way that disagrees.

The api image carries `src/` and not `fixtures/`, so the file goes in on
standard input:

    docker compose exec -T api python manage.py load_access_overrides - \
        --actor <discord user id> < fixtures/overrides/<file>.json
    # read what it would do, then the same with --confirm

The rows take effect on the next rebuild.

| File | Decision |
|---|---|
| `2026-09-26-owner-bicycle-access.json` | Key Bridge's Virginia approaches and the 11th Street local span's south landing are legal to ride (owner, 2026-09-26). See `fixtures/crossings/README.md`. |
