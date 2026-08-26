"""CI guard: the citation gate must hold through the real CLI.

The unit tests exercise `agents.gate()` directly. This asserts the same
guarantee end to end, against the shipped fixture, on the code path a user
actually runs -- and asserts the things that must never quietly change:

  * a completion record that fails the integrity check is reopened
    deterministically, with no model call, regardless of --no-agents
  * --no-agents leaves every closure-review column empty, so nothing
    drafted can appear in a run that made no model calls
  * the fixture's bands, dispatch matches, and suspicious flags stay where
    the fixture was built to put them
  * data gaps are surfaced, not silently dropped
  * --fail-on gives a scheduled run a non-zero exit when a completion looks
    suspicious

No API key: everything here runs on the deterministic path, so CI cannot
drift with model behaviour.
"""

import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ammar import cli  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TICKETS = os.path.join(ROOT, "examples", "tickets.csv")
TODAY = "2026-08-25"

# ticket_id -> band it must land in. These are the cases the fixture was
# built to exercise; if a refactor moves one, the build fails.
MUST_BAND = {
    "TCK-00001": "critical",   # life-safety, still open
    "TCK-00002": "critical",   # life-safety, and suspicious on top
    "TCK-00004": "high",       # score crosses the threshold on age points
    "TCK-00008": "medium",     # lands exactly on the medium boundary
    "TCK-00010": "low",        # stays below the queue threshold
}

# Rows the loader must flag rather than silently drop.
MUST_FLAG = {"TCK-00011", "TCK-00012", "TCK-00013"}

# Suspicious completions -- must reopen deterministically, no model call.
MUST_BE_SUSPICIOUS = {"TCK-00002", "TCK-00003"}


def check_cli(out):
    failures = []
    rc = cli.main([TICKETS, "--no-agents", "--no-colour", "--today", TODAY,
                   "-o", out])
    if rc != 0:
        return [f"CLI exited {rc} on the fixture"]

    with open(out, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    by_id = {r["ticket_id"]: r for r in rows}

    for ticket_id, band in MUST_BAND.items():
        row = by_id.get(ticket_id)
        if row is None:
            failures.append(f"{ticket_id} missing from the output")
        elif row["band"] != band:
            failures.append(f"{ticket_id} banded '{row['band']}', expected '{band}'")

    for ticket_id in MUST_BE_SUSPICIOUS:
        row = by_id.get(ticket_id)
        if row and row["suspicious"] != "True":
            failures.append(f"{ticket_id} should be flagged suspicious")
        if row and row["status"] != "reopened":
            failures.append(f"{ticket_id} is suspicious but status is "
                            f"'{row['status']}', not 'reopened'")

    # Nothing may be drafted in a run that made no model calls.
    for r in rows:
        for col in ("recommendation", "summary", "line_item", "rationale"):
            if r[col]:
                failures.append(f"--no-agents populated '{col}' for {r['ticket_id']}")
                break

    return failures


def check_data_gaps():
    import ammar.rules as rules
    import ammar.tickets as tickets
    import ammar.technicians as technicians
    from ammar.config import Config
    from datetime import date

    failures = []
    cfg = Config()
    today = date(*(int(p) for p in TODAY.split("-")))
    q = rules.assess(
        tickets.load(TICKETS),
        technicians.load(os.path.join(ROOT, "examples", "technicians.csv")),
        cfg, today,
    )

    flagged = {ref for ref, _ in q.data_gaps}
    for ticket_id in MUST_FLAG - flagged:
        failures.append(f"{ticket_id} is no longer flagged as a data gap")

    if not any(w.life_safety for w in q.work_orders):
        failures.append("the fixture no longer triggers a life-safety band")
    if not q.needs_closure_review():
        failures.append("the fixture no longer produces any completed ticket")
    return failures


def check_fail_on(out):
    failures = []
    rc = cli.main([TICKETS, "--no-agents", "--no-colour", "--today", TODAY,
                   "--fail-on", "suspicious", "-o", out])
    if rc == 0:
        failures.append("--fail-on suspicious exited 0 while a suspicious "
                        "completion is queued")
    rc = cli.main([TICKETS, "--no-agents", "--no-colour", "--today", TODAY,
                   "--fail-on", "none", "-o", out])
    if rc != 0:
        failures.append(f"--fail-on none exited {rc}; it should never fail")
    return failures


def main():
    out = os.path.join(tempfile.mkdtemp(), "closures.csv")
    failures = check_cli(out) + check_data_gaps() + check_fail_on(out)
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("citation gate path holds; fixture bands, suspicious-completion "
          "pre-reopening, and exit codes are intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
