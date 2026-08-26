# Architecture

![Ammar architecture: a tenant portal and technician roster feed a deterministic Triage Engine that scores urgency and matches a certified technician, producing a computed Work Order. That work order renders straight to a portfolio dashboard and separately becomes the completion record for a three-agent pipeline (Closure Drafter, Cost Reconciler, Dispute-Risk Reviewer). A Verification Gate compares the drafted closure summary directly against the technician's completion record -- not against the agents' own account of the job -- and routes the ticket to Verified or Reopened before a facilities manager signs off and the service-charge ledger is updated.](architecture.svg)

**A proposed architecture, not a shipped system.** The deterministic core
(`rules.py`), the agents (`agents.py`), and the Verification Gate are real,
tested code in this repository. The tenant portal, the live technician
mobile app, and the service-charge billing system are not -- they are the
boundaries a real deployment would build against, drawn here so the trust
boundary is explicit before any of that gets built.

## The problem

A single Dubai tower can throw off forty maintenance tickets before lunch --
an AC unit down in August, a leak, an elevator making a noise nobody likes --
and a large portfolio (Emaar/Aldar-scale) generates thousands. Every ticket
needs triage, routing to a certified technician, and a closure report that
will still hold up when the owners' association audits the service charge
six months later. Ammar drafts the closure report a resident reads, but it
is never the one deciding the ticket is actually fixed.

## Reading the diagram

**Deterministic core (slate blue).** The Triage Engine scores urgency from
the ticket's category and how long it has sat open, and treats a fixed list
of life-safety categories (elevator, electrical) as always critical,
regardless of score. Dispatch Matching assigns the least-loaded technician
certified for the trade. Nothing in this band calls a model. Its output, the
Work Order, is a set of facts and citable record IDs: the ticket itself, the
work order, the technician, every part used.

**The split.** The Work Order feeds two things independently. It renders
straight to a portfolio dashboard -- open tickets, SLA status, load by
tower -- on every run, agents or not. And once a technician has actually
submitted a completion record, it becomes the evidence packet the agentic
layer is allowed to cite from. These are drawn as two separate lanes on
purpose: the dashboard's numbers never pass through a model.

**Agentic layer (safety orange).** Three agents run in sequence against the
completion record only -- never against the raw ticket, never against a
technician's unstructured notes. The Closure Drafter writes the
resident-facing account. The Cost Reconciler drafts the service-charge line
item. The Dispute-Risk Reviewer recommends verified or reopen, and is
explicitly instructed never to write as though the ticket is already closed.

**Verification Gate.** This is the one arrow in the diagram that matters
most: the Completion Builder's record feeds the gate *directly* (the orange
path on the right, bypassing the three agents entirely), so the gate checks
the draft against the actual completion record, not against the agents'
account of what happened. Every bracketed citation in the draft is extracted
and checked against that record. Anything ungrounded forces the ticket to
reopen, regardless of what the reviewer recommended.

**Outcomes and the human checkpoint.** A grounded, verified-recommended
ticket is `Verified`; anything else -- an ungrounded citation, an agent
error, a suspicious completion caught before the agents even ran, or the
reviewer's own recommendation to reopen -- is `Reopened`. Both routes end at
a facilities manager: nothing here updates a service charge ledger or
closes a ticket in a system of record on its own.

## What this repository actually implements

- `rules.py` -- urgency scoring by trade category and ticket age, a
  fixed life-safety override, least-loaded technician dispatch matching,
  and a deterministic completion-integrity check (too fast to be real, or
  missing the photo a trade requires) that reopens a ticket before any
  model call.
- `agents.py` -- the three-agent pipeline and the citation gate described
  above, including the token-budget lesson learned while building this
  project's sibling tools `rasid` and `yaqeen`: thinking is on by default on
  the configured model, and a tight `max_tokens` truncates the JSON in a way
  that looks exactly like the gate correctly failing safe. That failure mode
  is closed from the first commit here, not re-discovered.
- `tickets.py` / `technicians.py` -- loose CSV loading with column aliases,
  because every helpdesk and workforce tool names these fields differently,
  and mismatched or unparseable data is surfaced as a data gap rather than
  silently dropped or guessed at.

## What this repository does not implement

- **A real tenant-facing intake.** Tickets are read from a CSV export. A
  deployment needs the actual portal/app/call-centre integration that
  produces tickets continuously, not once a day.
- **Live technician status.** Dispatch matching uses each technician's
  `current_load` as given in the roster at the start of a run. It does not
  track real-time acceptance, en-route status, or a technician going
  off-shift mid-run.
- **The billing step itself.** The Cost Reconciler drafts a line-item note;
  nothing here posts a charge to a service-charge ledger. That's a
  regulated, auditable action with its own review chain and is out of scope
  here on purpose.
