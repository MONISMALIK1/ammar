"""Write the closure account, cite the record -- but never decide the job is done.

Every urgency score, dispatch match, and completion-integrity check in this
tool is computed in `rules.py`. The agents receive the resulting evidence as
a set of citable record IDs -- [TCK-...], [WO-...], [TCH-...], [PART-...],
[PHOTO-...] -- and are permitted to explain, cost, and recommend against
them. They are not permitted to introduce a citation that was not handed to
them.

That restriction is enforced, not requested. `check_citations()` extracts
every bracketed ID from model output and fails the draft if any of them is
not traceable to the work order's completion record. A drafted closure
summary that cites [PART-9942] when that part was never logged does not
reach a resident as a plausible-sounding "fixed" -- it is reopened, with the
invented citation named.

  closure_drafter    writes the resident-facing account of the work
  cost_reconciler    drafts the service-charge line-item note
  dispute_reviewer   recommends verified or reopen, and is graded on its own
                     citations, never its own confidence

The gate can only ever push a ticket toward reopening. It has no path to
verify a ticket the reviewer did not already recommend verifying, and no
path to override a reopen recommendation. A facilities manager is the only
one who can close a reopened ticket, and nothing here updates a service
charge ledger on its own.
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

MODEL = os.environ.get("AMMAR_MODEL", "claude-opus-5")

# Thinking is on by default on this model, and max_tokens caps thinking and
# response text together. These replies are short, but a tight budget
# truncates the JSON mid-object -- which surfaces as a parse error, which the
# gate turns into a reopen. Every ticket would reopen and it would look like
# the gate correctly failing safe rather than the budget being wrong, so
# this is deliberately loose. See docs/the-verification-gate.md.
MAX_TOKENS = 16000

# If a safety classifier declines an item, retry on the recommended model
# inside the same call rather than failing the ticket. Sent only for the
# default model: an overridden one may not accept the parameter.
_FALLBACK = ({"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
             if MODEL == "claude-opus-5" else {})

_CITATION = re.compile(r"\[([A-Z]{2,6}-[A-Z0-9]+)\]")


def citations_in(text: str) -> set:
    return {m.group(1) for m in _CITATION.finditer(text or "")}


def expand_evidence(facts: dict) -> set:
    """Every citation an agent may legitimately reference for this ticket."""
    allowed = set()
    for key in ("ticket_id", "work_order_id", "technician_id", "photo_ref"):
        v = facts.get(key)
        if v:
            allowed.add(v)
    allowed.update(facts.get("parts_used") or [])
    return allowed


def check_citations(text: str, allowed: set):
    """Citations in `text` that no completion record entry accounts for."""
    return sorted(citations_in(text) - allowed)


CLOSURE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string",
                    "description": "Plain-language account of the repair, for "
                                   "the resident. Every factual claim cites a "
                                   "bracketed ID."},
    },
    "required": ["summary"],
    "additionalProperties": False,
}

COST_SCHEMA = {
    "type": "object",
    "properties": {
        "line_item": {"type": "string",
                      "description": "Service-charge line-item note: what was "
                                     "done and what was used, citing brackets."},
    },
    "required": ["line_item"],
    "additionalProperties": False,
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string", "enum": ["verified", "reopen"]},
        "rationale": {"type": "string",
                      "description": "Reasoning citing evidence in brackets. "
                                     "A recommendation, not a decision."},
    },
    "required": ["recommendation", "rationale"],
    "additionalProperties": False,
}

CLOSURE_SYSTEM = """You write a plain-language closure summary of one
maintenance ticket, for the resident who reported it.

Rules:
- Cite every factual claim using the bracketed IDs you are given -- for
  example [TCK-00042], [WO-00042], [TCH-03], [PART-118]. Never invent an ID,
  and never cite one you were not given.
- State only what the completion record shows. Do not promise the fault
  will never recur.
- Two to three sentences, warm and plain."""

COST_SYSTEM = """You draft the service-charge line-item note for one
completed maintenance ticket, for the building's finance team.

Rules:
- Cite every part and every technician using the bracketed IDs you were
  given. An uncited claim is unsupported and will force the ticket to
  reopen.
- State what was used and who did the work. Do not estimate a cost -- that
  is priced from the parts catalogue downstream, not written here."""

REVIEW_SYSTEM = """You review one completed maintenance ticket and recommend
whether it is ready to verify, for a facilities manager who makes the final
call.

Rules:
- Cite every factual claim using the bracketed IDs you were given. An
  uncited claim is treated as unsupported and forces a reopen recommendation
  regardless of your conclusion.
- You are recommending, not deciding. Never write as though the ticket is
  already closed.
- If the completion record does not clearly support the job being done,
  recommend reopening it. A facilities manager can verify an unnecessary
  reopen in seconds; nobody can undo a service charge billed against work
  that was never actually finished."""


class AgentUnavailable(RuntimeError):
    pass


def _client():
    try:
        import anthropic
    except ImportError as exc:
        raise AgentUnavailable(
            "the `anthropic` package is not installed -- run `pip install "
            "anthropic`, or use --no-agents for the computed queue only"
        ) from exc
    return anthropic.Anthropic()


def _structured(client, system, prompt, schema, effort):
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=system,
        output_config={"format": {"type": "json_schema", "schema": schema},
                       "effort": effort},
        messages=[{"role": "user", "content": prompt}],
        **_FALLBACK,
    )
    # Checked before touching resp.content: on a refusal the content list is
    # empty or partial, so reading it first would raise the wrong error.
    if resp.stop_reason == "refusal":
        raise AgentUnavailable("model declined this item")
    if resp.stop_reason == "max_tokens":
        raise AgentUnavailable(
            f"model hit the {MAX_TOKENS}-token cap before finishing its "
            f"reply; raise MAX_TOKENS in agents.py")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


def _handle(client, task):
    """`task` is a dict: {ticket_id, label, facts, allowed}."""
    facts_json = json.dumps(task["facts"])

    try:
        closure = _structured(client, CLOSURE_SYSTEM,
                              f"Ticket: {task['label']}\nRecord: {facts_json}",
                              CLOSURE_SCHEMA, "low")
    except AgentUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"closure drafting failed: {exc}"
        return task
    task["summary"] = closure["summary"]

    try:
        cost = _structured(client, COST_SYSTEM,
                           f"Ticket: {task['label']}\nRecord: {facts_json}",
                           COST_SCHEMA, "low")
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"cost reconciliation failed: {exc}"
        return task
    task["line_item"] = cost["line_item"]

    try:
        review = _structured(client, REVIEW_SYSTEM,
                             f"Ticket: {task['label']}\nRecord: {facts_json}\n"
                             f"Closure summary: {task['summary']}\n"
                             f"Line item: {task['line_item']}\n\n"
                             f"Is this ready to verify?",
                             REVIEW_SCHEMA, "high")
    except Exception as exc:  # noqa: BLE001
        task["error"] = f"review failed: {exc}"
        return task
    task["recommendation"] = review["recommendation"]
    task["rationale"] = review["rationale"]
    return task


def gate(task, allowed: set):
    """Runs after the agents, always. Can only ever push toward reopening."""
    if task.get("error"):
        task["status"] = "reopened"
        task["status_reason"] = task["error"]
        return task

    blob = " ".join(str(task.get(k, "")) for k in
                    ("summary", "line_item", "rationale"))
    ungrounded = check_citations(blob, allowed)
    if ungrounded:
        task["status"] = "reopened"
        task["status_reason"] = ("model cited a record with no computed "
                                 "source: " + ", ".join(ungrounded[:6]))
        task["ungrounded_citations"] = ungrounded
        return task

    if task.get("recommendation") == "reopen":
        task["status"] = "reopened"
        task["status_reason"] = f"reviewer recommended reopening: {task.get('rationale', '')}"
        return task

    task["status"] = "verified"
    task["status_reason"] = ""
    return task


def run(tasks, workers=6):
    client = _client()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda t: _handle(client, t), tasks))
