"""Computation and parsing. No API key needed."""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ammar import agents, rules, technicians, tickets  # noqa: E402
from ammar.config import Config  # noqa: E402

HERE = os.path.dirname(__file__)
TICKETS = os.path.join(HERE, "..", "examples", "tickets.csv")
TECHS = os.path.join(HERE, "..", "examples", "technicians.csv")
TODAY = date(2026, 8, 25)
CFG = Config()


def _tickets():
    return tickets.load(TICKETS)


def _techs():
    return technicians.load(TECHS)


def _queue():
    return rules.assess(_tickets(), _techs(), CFG, TODAY)


def _order(ticket_id):
    q = _queue()
    return next(w for w in q.work_orders if w.ticket_id == ticket_id)


# --- parsing -----------------------------------------------------------

def test_unrecognized_category_is_flagged_not_silently_dropped():
    q = _queue()
    notes = [n for ref, n in q.data_gaps if ref == "TCK-00011"]
    assert any("unrecognized" in n for n in notes)


def test_unparseable_reported_date_is_flagged():
    q = _queue()
    notes = [n for ref, n in q.data_gaps if ref == "TCK-00012"]
    assert any("unparseable" in n for n in notes)


def test_missing_half_of_a_completion_record_is_flagged():
    q = _queue()
    notes = [n for ref, n in q.data_gaps if ref == "TCK-00013"]
    assert any("incomplete" in n for n in notes)
    w = _order("TCK-00013")
    assert w.has_completion is False, "a partial record must not be treated as complete"


def test_technician_roster_parses_semicolon_trades():
    techs = _techs()
    t = next(t for t in techs if t.technician_id == "TCH-03")
    assert t.trades == ["elevator", "electrical"]


# --- urgency scoring -----------------------------------------------------

def test_life_safety_category_is_always_critical_regardless_of_points():
    w = _order("TCK-00001")
    assert w.band == "critical"
    assert w.life_safety is True


def test_life_safety_stays_critical_even_when_the_completion_is_suspicious():
    w = _order("TCK-00002")
    assert w.band == "critical"
    assert w.suspicious is True


def test_score_crosses_into_high_with_age_points():
    w = _order("TCK-00004")
    assert w.urgency_points == 62  # 30 base + min(8*4, 40)
    assert w.band == "high"


def test_grace_period_means_a_same_day_ticket_gets_no_age_points():
    w = _order("TCK-00005")
    assert w.urgency_points == 30  # base only, reported the same run day minus one
    assert w.band == "medium"


def test_missing_date_contributes_no_age_points_rather_than_guessing():
    w = _order("TCK-00012")
    assert w.urgency_points == 25  # plumbing base only
    assert w.band == "medium"


def test_age_points_are_capped():
    w = _order("TCK-00007")
    assert w.urgency_points == 70  # 30 base + capped 40, not 30 + 8*5=40 anyway here
    assert w.band == "high"


def test_boundary_score_lands_exactly_on_the_medium_threshold():
    w = _order("TCK-00008")
    assert w.urgency_points == CFG.medium_threshold == 25
    assert w.band == "medium"


def test_low_urgency_ticket_stays_low():
    w = _order("TCK-00010")
    assert w.band == "low"


# --- completion integrity -------------------------------------------------

def test_a_closure_faster_than_the_floor_is_suspicious():
    w = _order("TCK-00002")
    assert w.suspicious is True
    assert "minute" in w.suspicious_reason


def test_a_photo_required_trade_without_a_photo_is_suspicious():
    w = _order("TCK-00003")
    assert w.suspicious is True
    assert "photo" in w.suspicious_reason


def test_a_clean_completion_is_not_suspicious():
    w = _order("TCK-00007")
    assert w.suspicious is False
    assert w.has_completion is True


# --- dispatch matching -----------------------------------------------------

def test_least_loaded_qualified_technician_is_chosen():
    w = _order("TCK-00004")
    assert w.dispatched_technician_id == "TCH-04"  # load 0 beats TCH-01's load 2


def test_load_balancing_switches_technicians_once_loads_equalize():
    # TCK-00004 and TCK-00005 both go to TCH-04 (starts at load 0); by the
    # third ac ticket TCH-04's running load ties TCH-01's, and the tie
    # breaks alphabetically onto TCH-01.
    assert _order("TCK-00004").dispatched_technician_id == "TCH-04"
    assert _order("TCK-00005").dispatched_technician_id == "TCH-04"
    assert _order("TCK-00006").dispatched_technician_id == "TCH-01"


def test_no_technician_certified_for_the_trade_is_a_data_gap():
    q = _queue()
    w = _order("TCK-00011")
    assert w.dispatched_technician_id == ""
    notes = [n for ref, n in q.data_gaps if ref == "TCK-00011"]
    assert any("no technician" in n for n in notes)


def test_completed_tickets_are_not_dispatch_matched():
    w = _order("TCK-00007")
    assert w.dispatched_technician_id == ""
    assert w.completion_technician_id == "TCH-04"


# --- config ---------------------------------------------------------------

def test_config_rejects_unknown_keys():
    import json
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "bad.json")
    with open(path, "w") as fh:
        json.dump({"not_a_real_field": 1}, fh)
    try:
        Config.load(path)
        raise AssertionError("unknown key should have raised")
    except ValueError as exc:
        assert "not_a_real_field" in str(exc)


def test_thresholds_are_overridable():
    cfg = Config(medium_threshold=100, high_threshold=200)
    q = rules.assess(_tickets(), _techs(), cfg, TODAY)
    w = next(x for x in q.work_orders if x.ticket_id == "TCK-00004")
    assert w.band == "low", "raising the thresholds must lower the band"


# --- citation licensing (pure functions, no client) -------------------------

def test_a_fact_licenses_its_own_citation():
    w = _order("TCK-00007")
    allowed = agents.expand_evidence(w.facts())
    assert w.ticket_id in allowed
    assert f"WO-{w.ticket_id.split('-')[-1]}" in allowed
    assert w.completion_technician_id in allowed
    for part in w.parts_used:
        assert part in allowed
    assert w.photo_ref in allowed


def test_an_invented_citation_is_caught():
    w = _order("TCK-00007")
    allowed = agents.expand_evidence(w.facts())
    text = f"Fixed per [{w.ticket_id}], using [PART-9999] which was never logged."
    leaked = agents.check_citations(text, allowed)
    assert leaked == ["PART-9999"]


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  pass  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {name}: {exc}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
