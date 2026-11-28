"""The closure agent on the worker (v0.31.0, core.closure_agent): the agencies' pages read by
Claude every hour, each closure drawn on the map and entered, moved on and ended as the page
says. Claude, the pages and the map are stand-ins here: nothing leaves the test."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone
from test_stress_edits import LAT, LON
from test_suggestions import live

from core import closure_agent as agent
from core import reviewed_closures as rc
from core import workzones
from core.models import AuditLogEntry, BikeshareFeedCache, ReviewedClosure
from routemaker import ridetime

FIXTURES = (live,)
db = pytest.mark.django_db(transaction=True)

LINE = [[LON - 0.003 + i * 0.0005, LAT] for i in range(5)]
PAGE = "https://agency.example/closures"
SOURCE = agent.Source("testpark", "Test Parks", PAGE, "Test County, Maryland")
# The real drawing, before the fixture below stands in for it.
PLACE = agent.place
TREE = {
    "way": "Test Trail",
    "from_place": "First Street",
    "to_place": "Second Street",
    "mileposts": [],
    "first_day": "",
    "last_day": "",
    "reason": "tree down",
}


class Claude:
    """Answers each ask with the closures it is given, and counts the asks."""

    def __init__(self, closures: list[dict]) -> None:
        self.closures = closures
        self.asks: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.asks.append(request)
        text = json.dumps({"closures": self.closures})
        return SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)]
        )


def page(words: str):
    return lambda url: f"<html><script>var x=1</script><body><p>{words}</p></body></html>"


def today(n: int = 0) -> str:
    return (timezone.now().astimezone(ridetime.ZONE).date() + timedelta(days=n)).isoformat()


def last_day(row: ReviewedClosure) -> str:
    return (row.end - timedelta(seconds=1)).astimezone(ridetime.ZONE).date().isoformat()


@pytest.fixture(autouse=True)
def _one_source(monkeypatch):
    monkeypatch.setattr(agent, "SOURCES", (SOURCE,))
    monkeypatch.setattr(agent, "place", lambda source, found, get_json: [LINE])
    workzones.forget()
    yield
    workzones.forget()


def test_the_pages_words_without_its_scripts() -> None:
    html = "<div><script>x()</script><nav>Menu</nav><h2>B&amp;A Trail</h2><p>Closed  today</p>"
    assert agent.page_text(html) == "B&A Trail\nClosed today"


def test_the_same_closure_keeps_its_key_whatever_the_words_round_it() -> None:
    other = dict(TREE, reason="bridge work", way="test  trail")
    assert agent.alert_key(SOURCE, TREE) == agent.alert_key(SOURCE, other)
    assert agent.alert_key(SOURCE, TREE) != agent.alert_key(SOURCE, dict(TREE, to_place="Third"))
    assert agent.alert_key(SOURCE, TREE).startswith("a:testpark:")


@db
def test_without_claude_credentials_the_agent_is_off(monkeypatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_IDENTITY_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert agent.run(get=page("anything")).startswith("off")
    assert not ReviewedClosure.objects.exists()


@db
def test_a_closure_is_entered_moved_on_while_listed_and_ended_when_dropped(live) -> None:
    claude = Claude([TREE])
    line = agent.run(get=page("Test Trail closed: tree down"), get_json=None, client=claude)
    assert "asked 1" in line and "entered 1" in line, line
    row = ReviewedClosure.objects.get()
    assert row.created_by is None and row.agent_key.startswith("a:testpark:")
    assert row.reason == "Test Trail closed: tree down (Test Parks)"
    assert row.source_url == PAGE
    assert last_day(row) == today(0)  # no last day given: today only
    entered = AuditLogEntry.objects.get(action="closure_enter")
    assert entered.actor_id is None
    assert workzones.closures_on(LINE)["closures"]

    # The page has not changed: Claude is not asked again, the closure runs on through tomorrow.
    line = agent.run(get=page("Test Trail closed: tree down"), client=claude)
    assert len(claude.asks) == 1 and "asked 0" in line and "extended 1" in line, line
    assert last_day(ReviewedClosure.objects.get()) == today(1)

    # The page no longer lists it: it ends at once.
    claude.closures = []
    line = agent.run(get=page("All trails open"), client=claude)
    assert "ended 1" in line, line
    assert ReviewedClosure.objects.get().ended_at is not None


@db
def test_a_page_that_cannot_be_read_changes_nothing(live) -> None:
    claude = Claude([TREE])
    agent.run(get=page("Test Trail closed"), client=claude)

    def refused(url):
        raise OSError("refused")

    line = agent.run(get=refused, client=claude)
    assert "failed testpark (OSError)" in line and "ended 0" in line, line
    assert ReviewedClosure.objects.get().ended_at is None


@db
def test_the_pages_own_days_are_kept_and_past_closures_left_out(live) -> None:
    dated = dict(TREE, first_day=today(0), last_day=today(5))
    past = dict(TREE, to_place="Third Street", first_day=today(-9), last_day=today(-2))
    agent.run(get=page("Detour this week"), client=Claude([dated, past]))
    row = ReviewedClosure.objects.get()
    assert last_day(row) == today(5)


@db
def test_a_closure_that_cannot_be_drawn_is_counted_not_guessed(live, monkeypatch) -> None:
    monkeypatch.setattr(agent, "place", lambda source, found, get_json: None)
    line = agent.run(get=page("Muddy Branch Trail closed near the lock"), client=Claude([TREE]))
    assert "not placed 1" in line and "entered 0" in line, line
    assert not ReviewedClosure.objects.exists()


@db
def test_no_more_asks_than_the_days_allowance(live, monkeypatch) -> None:
    monkeypatch.setattr(agent, "CALLS_PER_DAY", 1)
    claude = Claude([])
    agent.run(get=page("one"), client=claude)
    line = agent.run(get=page("two"), client=claude)
    assert len(claude.asks) == 1 and "over the day's 1 asks: testpark" in line, line
    payload = BikeshareFeedCache.objects.get(key=agent.KEY).payload
    assert payload["calls"] == {"day": today(0), "n": 1}


@db
def test_the_agent_never_ends_a_persons_closure_or_a_connector_agents(live) -> None:
    from test_stress_edits import make_user

    person = rc.create(make_user(), line=LINE, reason="Bridge out", agent_key="testpark:x:1")
    agent.run(get=page("All open"), client=Claude([]))
    person.refresh_from_db()
    assert person.ended_at is None


def test_claude_is_asked_for_the_closures_shape_with_todays_date() -> None:
    claude = Claude([TREE])
    found = agent.ask(SOURCE, "Test Trail closed", timezone.now().date(), claude)
    assert found == [TREE]
    (request,) = claude.asks
    assert request["model"] == agent.MODEL
    assert request["output_config"]["format"]["schema"] == agent.SCHEMA
    assert "Today is" in request["messages"][0]["content"]
    assert "<page>\nTest Trail closed\n</page>" in request["messages"][0]["content"]


def test_the_c_and_o_is_drawn_by_its_mileposts(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        agent.pa, "towpath_lines", lambda a, b: calls.append((a, b)) or [[[0, 0], [1, 1]]]
    )
    found = dict(TREE, way="C&O Canal Towpath", mileposts=[5.2, 4.7])
    assert PLACE(agent.BY_KEY["choh"], found, get_json=None) == [[[0, 0], [1, 1]]]
    assert calls == [(4.7, 5.2)]
    # Elsewhere, one named place is not enough to draw anything.
    assert PLACE(agent.BY_KEY["fcpa"], dict(TREE, to_place=""), get_json=None) is None


@db
def test_a_closure_a_person_ended_is_not_entered_again(live) -> None:
    from test_stress_edits import make_user

    claude = Claude([TREE])
    agent.run(get=page("Test Trail closed"), client=claude)
    rc.end_now(make_user(), ReviewedClosure.objects.get().pk)
    line = agent.run(get=page("Test Trail closed"), client=claude)
    assert "entered 0" in line, line
    assert ReviewedClosure.objects.count() == 1


@db
def test_a_map_that_cannot_be_read_keeps_the_last_line_and_asks_claude_no_more(
    live, monkeypatch
) -> None:
    claude = Claude([TREE])
    agent.run(get=page("Test Trail closed"), client=claude)

    def refused(source, found, get_json):
        raise OSError("429")

    monkeypatch.setattr(agent, "place", refused)
    line = agent.run(get=page("Test Trail closed, still"), client=claude)
    assert "map not read for 1" in line and "ended 0" in line, line
    assert ReviewedClosure.objects.get().ended_at is None
    agent.run(get=page("Test Trail closed, still"), client=claude)
    assert len(claude.asks) == 2  # the changed page once, not again for the map


@db
def test_a_page_claude_cannot_read_is_tried_three_times_then_waits(live) -> None:
    class Broken(Claude):
        def create(self, **request):
            self.asks.append(request)
            return SimpleNamespace(stop_reason="max_tokens", content=[])

    claude = Broken([])
    for _ in range(5):
        line = agent.run(get=page("Something long"), client=claude)
    assert len(claude.asks) == agent.ASK_TRIES, line


def test_the_answer_is_the_last_models_after_a_fallback() -> None:
    class Fallback(Claude):
        def create(self, **request):
            blocks = [
                SimpleNamespace(type="text", text='{"clos'),
                SimpleNamespace(type="fallback"),
                SimpleNamespace(type="text", text=json.dumps({"closures": [TREE]})),
            ]
            return SimpleNamespace(stop_reason="end_turn", content=blocks)

    assert agent.ask(SOURCE, "page", timezone.now().date(), Fallback([])) == [TREE]


def test_the_agent_cannot_confirm_or_reject_a_riders_report() -> None:
    with pytest.raises(rc.Forbidden):
        rc.reject_report(rc.WORKER, 1)
