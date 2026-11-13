"""The connector's backlog item 9 (the owner's "do 9", 2026-11-13; mcp/routemaker_mcp.py): calls an
assistant sends together wait their turn for place search instead of being refused, the
ready-made prompts and the playbook in the server's instructions, and each plan's short computed
"why this way" against the most direct route."""

from __future__ import annotations

import importlib.util
import itertools
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

if "routemaker_mcp" in sys.modules:
    mcp = sys.modules["routemaker_mcp"]
else:
    _spec = importlib.util.spec_from_file_location(
        "routemaker_mcp", Path(__file__).resolve().parents[1] / "mcp" / "routemaker_mcp.py"
    )
    mcp = importlib.util.module_from_spec(_spec)
    sys.modules["routemaker_mcp"] = mcp
    _spec.loader.exec_module(mcp)

MI = mcp.METRES_PER_MILE
LON_MI = 1 / 53.9  # a degree of longitude through DC is about 53.9 mi
LAT_MI = 1 / 69.0
START = (-77.03, 38.90)


# --- Calls sent together ----------------------------------------------------------------------


class Scripted:
    """An api whose `_request` answers from a list, noting each path asked."""

    base = "https://routes.example"

    def __init__(self, answers):
        self.answers = list(answers)
        self.asked: list[str] = []

    def _request(self, method, path, body=None, headers=None, timeout=30):
        self.asked.append(path)
        return self.answers.pop(0)


def busy(retry_after: str = "1", status: int = 429):
    return (
        status,
        {"error": "A place search from this address is already running"},
        {"Retry-After": retry_after},
    )


FOUND = (200, {"results": [{"label": "Dupont Circle", "lon": -77.0434, "lat": 38.9096}]}, {})


@pytest.fixture
def pauses(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(mcp.time, "sleep", slept.append)
    return slept


def test_a_busy_place_search_waits_its_turn_instead_of_refusing(pauses):
    api = Scripted([busy("1"), busy("1", 503), FOUND])
    found = mcp.Api.geocode(api, "Dupont Circle")
    assert found[0]["label"] == "Dupont Circle"
    assert len(api.asked) == 3
    # Each pause is the Retry-After (1 s) plus up to 0.2 s so calls sent together spread out.
    assert len(pauses) == 2 and all(1.0 <= p <= 1.2 for p in pauses)


def test_a_long_retry_after_is_said_at_once_with_retry_after_s(pauses):
    # The minute's budget spent: waiting a minute inside one call is not worth it.
    api = Scripted([busy("42")])
    with pytest.raises(mcp.Busy) as refused:
        mcp.Api.geocode(api, "Dupont Circle")
    assert refused.value.retry_after_s == 42
    assert "retry_after_s: 42" in str(refused.value)
    assert "Nothing is wrong with the request" in str(refused.value)
    assert pauses == []


def test_the_wait_has_a_ceiling(pauses):
    api = Scripted([busy("2")] * 20)
    with pytest.raises(mcp.Busy):
        mcp.Api.geocode(api, "Dupont Circle")
    assert sum(pauses) <= mcp.LOOKUP_WAIT_S
    assert len(api.asked) <= 1 + mcp.LOOKUP_WAIT_S / mcp.LOOKUP_PAUSE_MAX_S + 1


def test_a_long_ride_out_of_time_is_not_taken_for_busy(pauses):
    api = Scripted([(503, {"error": "too long", "code": "long_ride_timed_out"}, {})])
    status, _, _ = mcp.patient_request(api, "POST", "/api/reach", {})
    assert status == 503 and pauses == []


class OneSearchAtATime(BaseHTTPRequestHandler):
    """The site's place search as its limits answer it: one search per rider at a time
    (core.ratelimit GEOCODE_IN_FLIGHT), a second refused with 429 and Retry-After."""

    running = threading.Lock()
    refused = 0

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path != "/api/geocode":
            self.send_response(404)
            self.end_headers()
            return
        if not OneSearchAtATime.running.acquire(blocking=False):
            OneSearchAtATime.refused += 1
            self._json(429, {"error": "already running"}, {"Retry-After": "1"})
            return
        try:
            time.sleep(0.3)
            query = parse_qs(url.query)["q"][0]
            row = {"label": query, "name": query, "lon": START[0], "lat": START[1]}
            self._json(200, {"results": [row]})
        finally:
            OneSearchAtATime.running.release()

    def _json(self, status, payload, headers=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def test_three_place_searches_sent_together_all_answer():
    """The live failure of 2026-11-12: six calls sent together, three refused. Now each waits."""
    site = ThreadingHTTPServer(("127.0.0.1", 0), OneSearchAtATime)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    OneSearchAtATime.refused = 0
    base = f"http://127.0.0.1:{site.server_port}"
    server = mcp.Server(lambda: mcp.Api(base), stations=[], out_dir=None)
    answers: dict[str, dict] = {}

    def ask(name):
        answers[name] = mcp.handle(
            server,
            {
                "jsonrpc": "2.0",
                "id": name,
                "method": "tools/call",
                "params": {"name": "find_place", "arguments": {"query": name}},
            },
        )

    try:
        names = ("Dupont", "Takoma", "Brookland")
        askers = [threading.Thread(target=ask, args=(n,)) for n in names]
        for t in askers:
            t.start()
        for t in askers:
            t.join(20)
    finally:
        site.shutdown()
    assert OneSearchAtATime.refused >= 1  # they did collide
    for name, answer in answers.items():
        assert answer["result"]["isError"] is False, answer
        assert name in answer["result"]["content"][-1]["text"]
    assert len(answers) == 3


def test_a_refusal_after_the_wait_tells_the_assistant_when_to_ask_again(pauses):
    class AlwaysBusy(Scripted):
        def _request(self, method, path, body=None, headers=None, timeout=30):
            return busy("30")

        def geocode(self, query, near=None):
            return mcp.Api.geocode(self, query, near)

    server = mcp.Server(lambda: AlwaysBusy([]), stations=[], out_dir=None)
    answer = mcp.handle(
        server,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "find_place", "arguments": {"query": "Dupont Circle"}},
        },
    )
    assert answer["result"]["isError"] is True
    assert "retry_after_s: 30" in answer["result"]["content"][0]["text"]


# --- Prompts and the playbook ----------------------------------------------------------------


def rpc(method, params=None):
    server = mcp.Server(lambda: None, stations=[], out_dir=None)
    return mcp.handle(server, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def test_the_server_offers_prompts_and_a_short_playbook():
    result = rpc("initialize", {"protocolVersion": mcp.PROTOCOL_VERSIONS[0]})["result"]
    assert result["capabilities"]["prompts"] == {"listChanged": False}
    playbook = result["instructions"]
    for said in ("novice", "bike-transit", "stress 80", "test: true", "retry_after_s", "`why`"):
        assert said in playbook
    # Short: the tool descriptions hold the detail (no wall of text).
    assert len(playbook) < 1800
    # The old "send place searches one at a time" is gone with its cause.
    assert "one at a time" not in playbook


def test_four_prompts_are_listed_without_their_text():
    prompts = rpc("prompts/list")["result"]["prompts"]
    assert [p["title"] for p in prompts] == [
        "Plan a commute",
        "Family trail ride",
        "Loop of N miles",
        "Bike plus Metro",
    ]
    for p in prompts:
        assert "text" not in p
        assert any(a.get("required") for a in p["arguments"])


def test_a_prompt_puts_the_persons_words_in_one_ask():
    got = rpc(
        "prompts/get",
        {"name": "plan_commute", "arguments": {"start": "Takoma", "end": "Union Station"}},
    )["result"]
    (message,) = got["messages"]
    text = message["content"]["text"]
    assert message["role"] == "user"
    assert "from Takoma to Union Station" in text
    assert "plan_route" in text and "ride_conditions" in text and "`why`" in text
    assert "{" not in text  # every blank filled


def test_a_loop_near_metro_uses_the_metro_loop_and_one_without_plans_a_loop():
    def loop(**extra):
        args = {"start": "Silver Spring", "miles": "30", **extra}
        got = rpc("prompts/get", {"name": "loop_of_n_miles", "arguments": args})
        return got["result"]["messages"][0]["content"]["text"]

    assert "plan_metro_loop" in loop(near_metro="yes")
    plain = loop()
    assert "plan_metro_loop" not in plain and "loop true" in plain and "30 miles" in plain


def test_a_family_ride_with_no_end_comes_back_and_one_with_an_end_does_not():
    def family(**args):
        got = rpc("prompts/get", {"name": "family_trail_ride", "arguments": args})
        return got["result"]["messages"][0]["content"]["text"]

    assert "and back" in family(start="Takoma Park") and "loop true" in family(start="Takoma Park")
    one_way = family(start="Takoma Park", end="Sligo Creek")
    assert "to Sligo Creek" in one_way and "loop true" not in one_way


def test_a_prompt_without_its_place_or_by_another_name_is_refused():
    assert (
        rpc("prompts/get", {"name": "plan_commute", "arguments": {"start": "x"}})["error"]["code"]
        == -32602
    )
    assert "no prompt" in rpc("prompts/get", {"name": "nope"})["error"]["message"]


# --- Why this way ----------------------------------------------------------------------------

# Every other test file plans without it (tests/conftest.py _no_why_plans).
why_plans = pytest.mark.why_plans


def stretch(street, a, b, tier, facility=None):
    return {
        "kind": "stretch",
        "street": street,
        "from_mi": a,
        "to_mi": b,
        "from_m": round(a * MI),
        "to_m": round(b * MI),
        "tier": tier,
        "facility": facility,
    }


def answer(line, entries, minutes) -> dict:
    miles = entries[-1]["to_mi"]
    stress: dict = {}
    for e in entries:
        key = str(e["tier"])
        stress[key] = stress.get(key, 0.0) + (e["to_mi"] - e["from_mi"]) * MI
    total = sum(mcp.haversine_mi(tuple(a), tuple(b)) for a, b in itertools.pairwise(line))
    # The line's length as the description's, so miles along the one are miles along the other.
    assert abs(total - miles) < 0.05
    return {
        "geometry": {"type": "LineString", "coordinates": line},
        "leg_ends": [len(line) - 1],
        "distance_m": miles * MI,
        "duration_s": minutes * 60,
        "stress_m": stress,
        "stress_spans": [{"from_m": 0, "to_m": round(miles * MI)}],
        "description": entries,
        "dials": {"stress": 70, "hills": 0},
    }


def at(east_mi, north_mi=0.0):
    return [START[0] + east_mi * LON_MI, START[1] + north_mi * LAT_MI]


# The direct route: 2 mi east on Georgia Avenue (LTS 4). This one: a half mile north on a
# quiet street, 2 mi east on the trail beside it, a half mile back: 3 mi.
DIRECT = answer(
    [at(i / 10) for i in range(21)], [stretch("Georgia Avenue", 0.0, 2.0, 4)], minutes=10
)
CALM_LINE = (
    [at(0, i / 10) for i in range(6)]
    + [at(i / 10, 0.5) for i in range(1, 21)]
    + [at(2, 0.5 - i / 10) for i in range(1, 6)]
)
CALM = answer(
    CALM_LINE,
    [
        stretch("Quiet Street", 0.0, 0.5, 2),
        stretch("Metropolitan Branch Trail", 0.5, 2.5, 1, "path"),
        stretch("Other Quiet Street", 2.5, 3.0, 2),
    ],
    minutes=18,
)


def test_why_says_the_cost_and_the_busy_road_left_for_the_trail():
    why = mcp.why_this_way(CALM, DIRECT)
    assert why["extra_miles"] == 1.0
    assert why["extra_minutes"] == 6  # at this route's own 10 mph, not the direct ride type's
    assert why["fewer_busy_miles"] == 2.0
    assert why["fewer_lts_4_miles"] == 2.0
    assert why["said"] == (
        "1.0 mi (1.6 km) longer, about 6 min more; 2.0 fewer miles on busy roads (LTS 3 and up)"
    )
    (left,) = why["leaves"]
    assert left == {
        "road": "Georgia Avenue",
        "lts": 4,
        "busy_miles": 2.0,
        "for": "Metropolitan Branch Trail",
        "for_lts": 1,
        "for_facility": "path",
        "at_mile": 0.5,
    }


def test_why_on_the_direct_route_itself_says_so_briefly():
    why = mcp.why_this_way(DIRECT, DIRECT)
    assert why["said"].startswith("this is the direct route")
    assert "leaves" not in why


class Site:
    """Plans by ride type: Fast takes Georgia Avenue, every other one the trail."""

    base = "https://routes.example"

    def __init__(self, fail_fast=False):
        self.sent: list[dict] = []
        self.fail_fast = fail_fast

    def route(self, body):
        self.sent.append(body)
        if body["preset"] == "fast":
            if self.fail_fast:
                raise mcp.ToolError("the planner is busy")
            return json.loads(json.dumps(DIRECT))
        return json.loads(json.dumps(CALM))

    def share(self, body):
        return body["id"]

    def closures_map(self, box, permits):
        return []


def plan(site, **args):
    server = mcp.Server(lambda: site, stations=[], out_dir=None)
    return server.call("plan_route", {"points": [at(0), at(2)], "test": True, **args})


@why_plans
def test_a_plan_carries_its_why_from_one_more_plan_at_fast():
    site = Site()
    out = plan(site, preset="novice", when="weekend")
    assert [b["preset"] for b in site.sent] == ["novice", "fast"]
    # The direct route is ridden at the same time of day, with none of this ride's own dials.
    assert site.sent[1]["when"] == "weekend"
    assert out["why"]["leaves"][0]["road"] == "Georgia Avenue"


@why_plans
@pytest.mark.parametrize(
    "args",
    [
        {"preset": "fast"},  # it is the direct route
        {"preset": "bike-transit"},  # a trip, not a ride
        {"preset": "mass-ride"},  # its roadway is fixed by the ride size
        {"loop": True},  # no direct route back to the start
    ],
)
def test_no_why_where_a_direct_route_means_nothing(args):
    site = Site()
    try:
        out = plan(site, **args)
    except mcp.ToolError:
        return  # a ride type that refuses these points plans nothing at all
    assert "why" not in out
    assert [b["preset"] for b in site.sent if b["preset"] == "fast"] == (
        ["fast"] if args.get("preset") == "fast" else []
    )


@why_plans
def test_no_why_on_a_long_ride_or_when_the_direct_plan_fails():
    far = mcp.WHY_MAX_MI + 1
    site = Site()
    server = mcp.Server(lambda: site, stations=[], out_dir=None)
    out = server.call("plan_route", {"points": [at(0), at(far)], "test": True})
    assert "why" not in out and len(site.sent) == 1
    out = plan(Site(fail_fast=True))
    assert "why" not in out and out["draft_id"]


@why_plans
def test_no_why_when_the_call_has_no_time_for_another_plan():
    site = Site()
    server = mcp.Server(lambda: site, stations=[], out_dir=None)
    call = mcp.Call(deadline=time.monotonic() + 1)  # far less than one plan's budget
    out = server.call("plan_route", {"points": [at(0), at(2)], "test": True}, call)
    assert "why" not in out and len(site.sent) == 1
