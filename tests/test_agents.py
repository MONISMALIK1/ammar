"""The citation guard, against a stubbed client."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ammar import agents  # noqa: E402


def _task(facts=None, ticket_id="TCK-00007"):
    facts = facts or {
        "ticket_id": ticket_id, "work_order_id": "WO-00007",
        "technician_id": "TCH-04", "parts_used": ["PART-118"],
        "photo_ref": "PHOTO-3303",
    }
    return {"ticket_id": ticket_id, "label": "ac ticket in Marina Tower A/0417",
            "facts": facts, "allowed": agents.expand_evidence(facts)}


# --- pure citation logic -----------------------------------------------------

def test_numbers_alone_are_not_treated_as_citations():
    assert agents.citations_in("it took 45 minutes and cost 200") == set()


def test_part_and_technician_ids_match_the_shape():
    assert agents.citations_in("[PART-118] fitted by [TCH-04]") == {"PART-118", "TCH-04"}


# --- orchestration -----------------------------------------------------------

class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, payload, stop_reason="end_turn"):
        self.stop_reason = stop_reason
        self.content = [_Block(json.dumps(payload))]


class FakeMessages:
    def __init__(self, closure, cost, review, explode=(), stop_reason="end_turn"):
        self.payloads = {"closure": closure, "cost": cost, "review": review}
        self.explode = set(explode)
        self.stop_reason = stop_reason
        self.calls = []
        self.kwargs = []

    def create(self, **kw):
        # Route by schema shape, not by grepping the system prompt -- a
        # wrapped docstring can silently split a matched phrase across two
        # lines, and the schema is what actually determines the role.
        props = set(kw["output_config"]["format"]["schema"]["properties"])
        if "recommendation" in props:
            role = "review"
        elif "line_item" in props:
            role = "cost"
        else:
            role = "closure"
        self.calls.append(role)
        self.kwargs.append(kw)
        if role in self.explode:
            raise RuntimeError("simulated API failure")
        return _Resp(self.payloads[role], stop_reason=self.stop_reason)


def _install(msgs):
    # The real call is client.beta.messages.create, so the stub has to nest
    # the same way or the request-shape tests below pass against nothing.
    beta = type("B", (), {"messages": msgs})()
    agents._client = lambda: type("C", (), {"beta": beta})()  # noqa: SLF001
    return msgs


def _closure(text="Replaced the compressor capacitor using [PART-118] on [TCK-00007]; the unit is cooling normally again."):
    return {"summary": text}


def _cost(text="[PART-118] fitted by [TCH-04] against work order [WO-00007]."):
    return {"line_item": text}


def _review(recommendation="reopen",
           rationale="The completion record on [TCK-00007] supports the repair, but the unit should be re-checked in 48 hours."):
    return {"recommendation": recommendation, "rationale": rationale}


def test_clean_reopen_recommendation_is_gated_to_reopened():
    _install(FakeMessages(_closure(), _cost(), _review()))
    t = _task()
    [out] = agents.run([t], workers=1)
    agents.gate(out, out["allowed"])
    assert out["status"] == "reopened"
    assert "recommended reopening" in out["status_reason"]


def test_clean_verified_recommendation_is_gated_to_verified():
    _install(FakeMessages(
        _closure(), _cost(),
        _review(recommendation="verified", rationale="Completion record on [TCK-00007] is complete and consistent."),
    ))
    t = _task()
    [out] = agents.run([t], workers=1)
    agents.gate(out, out["allowed"])
    assert out["status"] == "verified"


def test_invented_citation_in_the_review_forces_reopen_even_if_recommendation_was_verified():
    _install(FakeMessages(
        _closure(), _cost(),
        _review(recommendation="verified", rationale="Consistent with [WO-99999], a prior closure."),
    ))
    t = _task()
    [out] = agents.run([t], workers=1)
    agents.gate(out, out["allowed"])
    assert out["status"] == "reopened"
    assert "WO-99999" in out["status_reason"]


def test_invented_citation_in_the_closure_summary_also_forces_reopen():
    _install(FakeMessages(
        _closure("Replaced the part logged under [PART-42], now cooling normally."),
        _cost(), _review(recommendation="verified"),
    ))
    t = _task()
    [out] = agents.run([t], workers=1)
    agents.gate(out, out["allowed"])
    assert out["status"] == "reopened"
    assert "PART-42" in out["status_reason"]


def test_the_gate_cannot_downgrade_a_reopen_recommendation():
    """The gate only ever pushes toward reopening -- it has no branch that
    turns a reopen recommendation into a verified closure, however clean
    the citations are."""
    _install(FakeMessages(_closure(), _cost(), _review(recommendation="reopen")))
    t = _task()
    [out] = agents.run([t], workers=1)
    agents.gate(out, out["allowed"])
    assert out["status"] == "reopened"


def test_any_agent_failure_reopens():
    for role in ("closure", "cost", "review"):
        _install(FakeMessages(_closure(), _cost(), _review(), explode=(role,)))
        t = _task()
        [out] = agents.run([t], workers=1)
        agents.gate(out, out["allowed"])
        assert out["status"] == "reopened", f"{role} failure did not reopen"


# --- request shape (the token-budget lesson, learned once, enforced here) ---

def test_token_budget_leaves_room_for_thinking():
    """Thinking is on by default on this model and counts against max_tokens.
    A budget tight enough to truncate the JSON mid-object surfaces as a parse
    error, which the gate turns into a reopen -- every ticket would reopen
    and it would look like the gate correctly failing safe rather than the
    budget being wrong. The budget has to be loose enough that it cannot
    happen."""
    assert agents.MAX_TOKENS >= 8000, (
        f"MAX_TOKENS={agents.MAX_TOKENS} risks truncating the reply mid-JSON")
    msgs = _install(FakeMessages(_closure(), _cost(), _review()))
    agents.run([_task()], workers=1)
    for kw in msgs.kwargs:
        assert kw["max_tokens"] == agents.MAX_TOKENS


def test_truncated_reply_is_named_not_reported_as_a_parse_error():
    _install(FakeMessages(_closure(), _cost(), _review(), stop_reason="max_tokens"))
    t = _task()
    try:
        agents.run([t], workers=1)
    except agents.AgentUnavailable as exc:
        assert "token cap" in str(exc), exc
    else:
        raise AssertionError("a truncated reply was not surfaced")


def test_structured_request_shape_is_what_the_api_expects():
    msgs = _install(FakeMessages(_closure(), _cost(), _review()))
    agents.run([_task()], workers=1)
    assert msgs.calls == ["closure", "cost", "review"]
    for kw in msgs.kwargs:
        cfg = kw["output_config"]
        assert cfg["format"]["type"] == "json_schema"
        assert cfg["format"]["schema"]["additionalProperties"] is False
        assert cfg["effort"] in ("low", "medium", "high", "xhigh", "max")
        assert "effort" not in kw, "effort belongs inside output_config"
    # The reviewer is the highest-stakes step and runs at high effort.
    assert msgs.kwargs[2]["output_config"]["effort"] == "high"


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
