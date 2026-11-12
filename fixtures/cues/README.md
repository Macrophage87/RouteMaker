# The cue bench's fixtures

Made-up trips (start and end points round junctions where a cue went wrong before), planned once
and kept. Never anyone's ride: no GPS track, rider, date or time is in any file here.

- `trips.json`: the trips. `scripts/cue_bench_capture.py <server>` plans them again and writes
  `<name>.json` (the answer, cut to what Ride, the exports and the connector read; work zones
  left out, as they change by the day).
- `transcripts/<name>.txt`: Ride riding each trip on a seeded synthetic track at 8, 12 and 18 mph,
  with a missed turn and 30 s of weak GPS at 12 mph: every sentence, when, and whether it was
  said, held, cut off or dropped, then the rules' findings (`!` lines). Written by
  `frontend/src/lib/cueBench.ts`.
- `expected/<name>.json`: the cue rows of Ride's strip and phone images (cueSheetPdf.ts), which the
  connector's cue cards (src/core/cue_cards.py) must match (tests/test_cue_fixtures.py).

From `frontend/`:

    node scripts/cueBench.ts            # check every fixture; list the findings
    node scripts/cueBench.ts --update   # write transcripts/ and expected/ afresh, then read git diff
    node scripts/cueBench.ts --out DIR  # write transcripts to DIR (two checkouts, then diff -ru)

A change that moves a cue changes a transcript: `npm test` fails until `--update` is run, and the
diff goes in the pull request, so a reviewer sees every cue it touched.

The bench's own figures are our defaults, unmeasured: speech at 14 characters a second, GPS noise
up to 4 m with 8 m accuracy, a first warning at least 8 s before a turn, sharp bends of 60 degrees
with no cue within 40 m listed for a look (a curve with no junction is a fair answer).
