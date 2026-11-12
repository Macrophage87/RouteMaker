#!/usr/bin/env python3
"""The route scorecard runner (docs/SCORECARD.md): plan the fixed trips, score them, and
compare with the last run. Standard library only.

    # On the PC, through the route-check service (it checks out any ref):
    python3 scripts/route_scorecard.py queue --ref origin/release/v0.26.0 --label v0.26.0 \\
        --out <queue>/req
    # ...the service answers into <queue>/res; then:
    python3 scripts/route_scorecard.py collect --manifest <queue>/v0.26.0.plans.json \\
        --answers <queue>/res --out runs/v0.26.0.json

    # Straight against a running stack's /api/route (a local stack, or beta from inside):
    python3 scripts/route_scorecard.py http --base-url http://localhost:8000 --label local \\
        --out runs/local.json

    # The report, against the last run:
    python3 scripts/route_scorecard.py report runs/new.json --against runs/old.json \\
        --out report.md

Planning only reads: /api/route saves nothing to any account (drafts come only from the
connector), and every end is a public landmark. Each plan asks `debug_junctions` for the
signal count. Options: `--stress N` plans Default at one slider position (a before/after at
Default is `--stress 70`); every other ride type keeps its own start. `--only id,id` limits
the trips; `--no-contrast` and `--no-stability` drop those checks.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from routemaker import scorecard  # noqa: E402

TRIPS = ROOT / "fixtures" / "scorecard" / "trips.json"
# The route-check service takes up to 8 plans in one request.
PER_REQUEST = 8
# A plan refused as busy (a routing slot held by a rider) waits this long and tries once more.
BUSY_STATUSES = (429, 503)
BUSY_RETRY_S = 60.0
# The findings line for the alert script: only a run this recent, at most this many lines and
# characters (Discord takes 2000 in one post; the script adds its own words). Our defaults.
FRESH_H = 20
MAX_LINES = 12
MAX_CHARS = 1500


def _entries(args) -> list[dict]:
    trips = json.loads(Path(args.trips).read_text())
    extra: dict = {"debug_junctions": True}
    only = [s for s in (args.only or "").split(",") if s] or None
    return scorecard.plans(
        trips,
        extra=extra,
        stress=args.stress,
        contrast=not args.no_contrast,
        stability=not args.no_stability,
        only=only,
    )


def _meta(args, **more) -> dict:
    meta = {
        "label": args.label,
        "made": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }
    if args.stress is not None:
        meta["stress"] = args.stress
    meta.update({k: v for k, v in more.items() if v is not None})
    return meta


def cmd_queue(args) -> int:
    entries = _entries(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # Labels are unique to the run, so answers of two runs in one folder never mix.
    for i, entry in enumerate(entries):
        entry["label"] = f"{_slug(args.label)[:40]} {i:03d}"
    names = []
    for n, chunk in enumerate(_chunks(entries)):
        req = {
            "check": "plan",
            "ref": args.ref,
            "trace": False,
            "plans": [{"label": e["label"], "body": e["body"], "full": True} for e in chunk],
        }
        name = f"scorecard-{_slug(args.label)}-{n:02d}.json"
        tmp = out / (name + ".part")
        tmp.write_text(json.dumps(req, indent=1))
        tmp.replace(out / name)
        names.append(name)
    manifest = {
        "meta": _meta(args, ref=args.ref),
        "requests": names,
        "entries": entries,
    }
    # The manifest is not a request, so it never goes in the request folder (the service
    # would try to run it): by default it goes in the folder above (the queue folder).
    target = (
        Path(args.manifest) if args.manifest else out.parent / f"{_slug(args.label)}.plans.json"
    )
    target.write_text(json.dumps(manifest, indent=1))
    print(f"{len(entries)} plans in {len(names)} requests; manifest {target}")
    return 0


def _chunks(entries: list[dict]) -> list[list[dict]]:
    """Requests of up to PER_REQUEST plans; a long trip goes alone, so one slow calm search
    cannot take seven other answers down with it when the service's 15 minutes run out."""
    out: list[list[dict]] = []
    short: list[dict] = []
    for entry in entries:
        if entry.get("setting") == "long":
            out.append([entry])
            continue
        short.append(entry)
        if len(short) == PER_REQUEST:
            out.append(short)
            short = []
    if short:
        out.append(short)
    return out


def _answers_from_files(
    paths: list[Path], entries: list[dict], requests: list[str] | None = None
) -> tuple[dict, dict]:
    by_label = {e["label"]: e["key"] for e in entries}
    answers: dict[str, dict] = {}
    info: dict = {}
    for path in paths:
        if path.is_dir():
            # Only this run's own answer files: a folder may hold another run's too.
            files = [path / n for n in requests] if requests else []
            missing = [f.name for f in files if not f.exists()]
            if missing:
                info.setdefault("unanswered_requests", []).extend(missing)
            files = [f for f in files if f.exists()]
        else:
            files = [path]
        for f in files:
            data = json.loads(f.read_text())
            if data.get("sha"):
                info["sha"] = data["sha"]
            if data.get("status") not in ("ok", None):
                info.setdefault("request_errors", []).append(f"{f.name}: {data.get('status')}")
            for plan in data.get("plans", []):
                key = by_label.get(plan.get("label"))
                if key is None:
                    continue
                answers[key] = {
                    "status": plan.get("status"),
                    "body": plan.get("answer")
                    if plan.get("status") == 200
                    else {
                        "error": plan.get("error")
                        or (plan.get("traceback") or "")[-300:]
                        or _error_of(plan.get("answer"))
                    },
                    "seconds": plan.get("seconds"),
                }
    return answers, info


def _error_of(answer) -> str:
    if isinstance(answer, dict):
        return str(answer.get("error") or answer.get("detail") or "")[:300]
    return str(answer)[:300]


def cmd_collect(args) -> int:
    manifest = json.loads(Path(args.manifest).read_text())
    entries = manifest["entries"]
    answers, info = _answers_from_files(
        [Path(p) for p in args.answers], entries, manifest.get("requests")
    )
    meta = dict(manifest.get("meta", {}))
    meta.update(info)
    meta["answered"] = f"{len(answers)} of {len(entries)}"
    run = scorecard.run_of(entries, answers, meta)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(run))
    print(f"run {args.out}: {meta['answered']} answered")
    return 0


def _post(url: str, body: dict, host: str | None, timeout: float) -> tuple[int | None, object]:
    headers = {"Content-Type": "application/json", "User-Agent": "routemaker-scorecard"}
    if host:
        headers["Host"] = host
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read() or b"null")
        except ValueError:
            return error.code, {"error": f"HTTP {error.code}"}
    except (OSError, ValueError) as error:
        # URLError, a dropped connection, a timeout, or a 200 that was not JSON: this plan is
        # unanswered, and the run goes on.
        return None, {"error": f"{type(error).__name__}: {error}"[:300]}


def plan_http(
    entries: list[dict],
    args,
    out: Path,
    meta: dict,
    *,
    post=_post,
    sleep=time.sleep,
    clock=time.monotonic,
) -> dict:
    """Plan every entry against `args.base_url`, one at a time, through the real view (its
    rate limits and routing slots included). A plan refused as busy (429, 503) waits
    `BUSY_RETRY_S` and tries once more. Past `args.budget_min` no new plan starts. The run is
    written to `out` after every plan, so a run cut short keeps what it planned."""
    answers: dict[str, dict] = {}
    url = args.base_url.rstrip("/") + "/api/route"
    started = clock()
    for entry in entries:
        if args.budget_min and clock() - started > args.budget_min * 60:
            print(f"budget of {args.budget_min} min reached; the rest are not planned")
            break
        begun = clock()
        status, body = post(url, entry["body"], args.host, args.timeout)
        if status in BUSY_STATUSES:
            sleep(BUSY_RETRY_S)
            status, body = post(url, entry["body"], args.host, args.timeout)
        answers[entry["key"]] = {
            "status": status,
            "body": body,
            "seconds": round(clock() - begun, 1),
        }
        print(f"{entry['key']}: {status} in {answers[entry['key']]['seconds']} s", flush=True)
        _write(out, scorecard.run_of(entries, answers, meta))
        if args.pause:
            sleep(args.pause)
    run = scorecard.run_of(entries, answers, meta)
    _write(out, run)
    return run


def _write(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def cmd_http(args) -> int:
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    plan_http(_entries(args), args, out, _meta(args, base_url=args.base_url))
    return 0


# --- nightly, on the beta host (scripts/beta/alert.sh scorecard) ----------------------------


def _runs(folder: Path) -> list[Path]:
    """The kept runs, newest first: run-<UTC stamp>.json. A run marked mixed (the map or the
    api changed while it ran) ends .mixed.json and is never compared with."""
    return sorted(folder.glob("run-*Z.json"), reverse=True)


def cmd_nightly(args) -> int:
    folder = Path(args.dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%MZ")
    args.label = f"nightly {stamp}"
    out = folder / f"run-{stamp}.json"
    run = plan_http(_entries(args), args, out, _meta(args, base_url=args.base_url))
    for old in sorted(folder.glob("run-*.json"), reverse=True)[args.keep :]:
        old.unlink()
    failed = sum(1 for r in run["rows"].values() if r.get("status") != 200)
    print(f"{out.name}: {len(run['rows'])} plans, {failed} not planned")
    return 0


def cmd_findings(args) -> int:
    """For the alert script: the newest run's stamp on one line and what moved after it, only
    when that run is under `FRESH_H` hours old and something moved; nothing otherwise."""
    runs = _runs(Path(args.dir))
    if not runs:
        return 0
    newest = runs[0]
    age_h = (time.time() - newest.stat().st_mtime) / 3600
    if age_h > FRESH_H:
        return 0
    new = json.loads(newest.read_text())
    older = [json.loads(p.read_text()) for p in runs[1 : 1 + args.lookback]]
    if not older:
        return 0
    diff = scorecard.compare(scorecard.baseline(older), new)
    lines = scorecard.night_text(new, diff).splitlines()
    if not lines:
        return 0
    shown: list[str] = []
    for line in lines[:MAX_LINES]:
        if sum(len(x) + 1 for x in shown) + len(line) > MAX_CHARS:
            break
        shown.append(line)
    more = len(lines) - len(shown)
    print(newest.stem.removeprefix("run-"))
    print(f"route scorecard {newest.stem.removeprefix('run-')}: {len(lines)} changes")
    print("\n".join(shown))
    if more:
        print(f"...and {more} more")
    print("Full table: alert.sh scorecard-report on the beta")
    return 0


def cmd_report(args) -> int:
    if args.dir:
        runs = _runs(Path(args.dir))
        if not runs:
            print("No kept run yet.")
            return 0
        new = json.loads(runs[0].read_text())
        older = [json.loads(p.read_text()) for p in runs[1:8]]
        old = scorecard.baseline(older) if older else None
    elif args.run:
        new = json.loads(Path(args.run).read_text())
        old = json.loads(Path(args.against).read_text()) if args.against else None
    else:
        sys.exit("report: give a run file or --dir")
    text = scorecard.report(new, old)
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)
    return 0


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in ".-" else "-" for c in text) or "run"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    def planning(p, label=True):
        p.add_argument("--trips", default=str(TRIPS))
        if label:
            p.add_argument("--label", required=True, help="Names the run: a version or branch.")
        p.add_argument("--stress", type=int, default=None)
        p.add_argument("--only", default=None, help="Comma-separated trip ids.")
        p.add_argument("--no-contrast", action="store_true")
        p.add_argument("--no-stability", action="store_true")

    q = sub.add_parser("queue", help="Write route-check service requests.")
    planning(q)
    q.add_argument("--ref", required=True)
    q.add_argument("--out", required=True, help="The service's queue/req folder.")
    q.add_argument("--manifest", default=None, help="Where the manifest goes.")
    q.set_defaults(fn=cmd_queue)

    c = sub.add_parser("collect", help="Read the service's answers into a run.")
    c.add_argument("--manifest", required=True)
    c.add_argument("--answers", nargs="+", required=True, help="Answer files or folders.")
    c.add_argument("--out", required=True)
    c.set_defaults(fn=cmd_collect)

    def over_http(p):
        p.add_argument("--base-url", required=True)
        p.add_argument("--host", default=None, help="The Host header (the beta's own name).")
        p.add_argument("--timeout", type=float, default=120.0)
        p.add_argument("--pause", type=float, default=2.0, help="Seconds between plans.")
        p.add_argument(
            "--budget-min", type=float, default=90.0, help="Start no plan after this long."
        )

    h = sub.add_parser("http", help="Plan over HTTP against a running stack.")
    planning(h)
    over_http(h)
    h.add_argument("--out", required=True)
    h.set_defaults(fn=cmd_http)

    n = sub.add_parser("nightly", help="One nightly run into a folder of kept runs.")
    planning(n, label=False)
    over_http(n)
    n.add_argument("--dir", required=True)
    n.add_argument("--keep", type=int, default=60, help="Runs kept (our default).")
    n.set_defaults(fn=cmd_nightly, label="nightly")

    f = sub.add_parser("findings", help="What the newest kept run moved, for the alert script.")
    f.add_argument("--dir", required=True)
    f.add_argument("--lookback", type=int, default=7, help="Older runs a baseline draws on.")
    f.set_defaults(fn=cmd_findings)

    r = sub.add_parser("report", help="Write the Markdown report.")
    r.add_argument("run", nargs="?", help="A run file; or --dir for the newest kept run.")
    r.add_argument("--dir", default=None, help="A nightly folder: newest run against its baseline.")
    r.add_argument("--against", default=None)
    r.add_argument("--out", default=None)
    r.set_defaults(fn=cmd_report)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
