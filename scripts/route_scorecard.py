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
signal count. Options: `--stress N` plans every trip at one slider position (a before/after
at Default is `--stress 70`); `--only id,id` limits the trips; `--no-contrast` and
`--no-stability` drop those checks.
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


def _entries(args) -> list[dict]:
    trips = json.loads(Path(args.trips).read_text())
    extra: dict = {"debug_junctions": True}
    if args.stress is not None:
        extra["stress"] = args.stress
    only = [s for s in (args.only or "").split(",") if s] or None
    return scorecard.plans(
        trips,
        extra=extra,
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
    for i, entry in enumerate(entries):
        entry["label"] = f"sc {i:03d}"
    names = []
    for n in range(0, len(entries), PER_REQUEST):
        chunk = entries[n : n + PER_REQUEST]
        req = {
            "check": "plan",
            "ref": args.ref,
            "trace": False,
            "plans": [{"label": e["label"], "body": e["body"], "full": True} for e in chunk],
        }
        name = f"scorecard-{_slug(args.label)}-{n // PER_REQUEST:02d}.json"
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


def _answers_from_files(paths: list[Path], entries: list[dict]) -> tuple[dict, dict]:
    by_label = {e["label"]: e["key"] for e in entries}
    answers: dict[str, dict] = {}
    info: dict = {}
    for path in paths:
        files = sorted(path.glob("scorecard-*.json")) if path.is_dir() else [path]
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
                    else {"error": plan.get("error") or _error_of(plan.get("answer"))},
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
    answers, info = _answers_from_files([Path(p) for p in args.answers], entries)
    meta = dict(manifest.get("meta", {}))
    meta.update(info)
    meta["answered"] = f"{len(answers)} of {len(entries)}"
    run = scorecard.run_of(entries, answers, meta)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(run))
    print(f"run {args.out}: {meta['answered']} answered")
    return 0


def cmd_http(args) -> int:
    entries = _entries(args)
    answers: dict[str, dict] = {}
    url = args.base_url.rstrip("/") + "/api/route"
    for entry in entries:
        started = time.monotonic()
        request = urllib.request.Request(
            url,
            data=json.dumps(entry["body"]).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "routemaker-scorecard"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                status, body = response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            status = error.code
            try:
                body = json.loads(error.read() or b"null")
            except ValueError:
                body = {"error": f"HTTP {error.code}"}
        except (urllib.error.URLError, TimeoutError) as error:
            status, body = None, {"error": str(error)[:300]}
        answers[entry["key"]] = {
            "status": status,
            "body": body,
            "seconds": round(time.monotonic() - started, 1),
        }
        print(f"{entry['key']}: {status} in {answers[entry['key']]['seconds']} s", flush=True)
        if args.pause:
            time.sleep(args.pause)
    run = scorecard.run_of(entries, answers, _meta(args, base_url=args.base_url))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(run))
    return 0


def cmd_report(args) -> int:
    new = json.loads(Path(args.run).read_text())
    old = json.loads(Path(args.against).read_text()) if args.against else None
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

    def planning(p):
        p.add_argument("--trips", default=str(TRIPS))
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

    h = sub.add_parser("http", help="Plan over HTTP against a running stack.")
    planning(h)
    h.add_argument("--base-url", required=True)
    h.add_argument("--out", required=True)
    h.add_argument("--timeout", type=float, default=120.0)
    h.add_argument("--pause", type=float, default=2.0, help="Seconds between plans.")
    h.set_defaults(fn=cmd_http)

    r = sub.add_parser("report", help="Write the Markdown report.")
    r.add_argument("run")
    r.add_argument("--against", default=None)
    r.add_argument("--out", default=None)
    r.set_defaults(fn=cmd_report)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
