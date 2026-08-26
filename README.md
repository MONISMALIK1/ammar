# ammar

**Tower maintenance dispatch for the ticket queue that refills every
morning.** Reads a maintenance-ticket export and a technician roster, scores
urgency and matches technicians in plain Python, and reopens any drafted
closure that cites a record it wasn't given.

Status: working v0.1, built 2026-08-25. 34 tests, hermetic — the citation
gate is verified on constructed tasks, so CI needs no API key.

---

## The daily operational problem

A single Dubai or Abu Dhabi tower can throw off forty maintenance tickets
before lunch — an AC unit down in August, a leak, an elevator making a noise
nobody likes — and a large portfolio generates thousands. Every ticket needs
triage, routing to a certified technician, and a closure report that will
still hold up when the owners' association audits the service charge six
months later. Getting the triage wrong is expensive in one of two
directions: a life-safety fault sitting in a queue behind cosmetic
complaints, or a service charge billed against a repair nobody can actually
verify happened.

## The design

```
tickets.csv + technicians.csv
    |
    +-- loose column matching     every helpdesk names these fields differently
    +-- completion parsing        mismatched or bad data flagged, never dropped
    |
    +-- rules.py                  ALL scoring: urgency, life-safety override,
    |       |                     dispatch matching, completion integrity
    |       +-- facts()           the citable evidence, per work order
    |       |
    |       +--> closure drafter -> cost reconciler -> reviewer  (cite, never invent)
    |       |
    |       +--> gate()           the Verification Gate; runs last, always
    |
  closures.csv  +  terminal report
```

**The Verification Gate is the product.** Every urgency score and dispatch
match comes from `rules.py`. The agents receive the resulting completion
record as a set of citable record IDs — `[TCK-00042]`, `[WO-00042]`,
`[TCH-03]`, `[PART-118]` — and may explain, cost, and recommend against them.
They may not introduce a citation that was not handed to them.
`check_citations()` extracts every bracketed ID from the drafted output and
reopens the ticket if any of them traces to nothing, naming the invented
citation.

There is a test asserting that a clean-looking `verified` recommendation
citing `[WO-99999]` — a work order that does not exist in the completion
record — is reopened anyway, even though the sentence around it is
well-formed and plausible. Fluency is the failure mode; there is no surface
signal separating a citation to a real part log from one the model made up.

## Run it

```bash
make test
make demo-deterministic   # no API key: urgency, dispatch, suspicious flags
make demo                 # full pass; needs ANTHROPIC_API_KEY
```

```bash
ammar tickets.csv --technicians technicians.csv --out closures.csv
```

| flag | why |
|---|---|
| `--today YYYY-MM-DD` | pin the run date, for reproducible output |
| `--config FILE` | override any urgency threshold; unknown keys are rejected |
| `--show-low` | list low-band tickets too (logged, not queued for closure review) |
| `--no-agents` | computed queue only; no model calls |
| `--fail-on suspicious` | exit non-zero when a completion fails the integrity check, for alerting |

Column names vary by helpdesk, so the CSV loader matches loosely:
`ticket_id` / `id` / `ref`, `category` / `trade` / `type`,
`technician_id` / `tech_id` / `assigned_to`, and so on. A ticket counts as
completed only when both `technician_id` and `time_spent_minutes` are
present — one without the other is surfaced as a data gap, not guessed at.

## What the demo shows

Thirteen tickets across two towers, run against 2026-08-25:

```
  CRITICAL  (4)
      CRITICAL  TCK-00003  Marina Tower B/1502 electrical   points  51  TCH-03   SUSPICIOUS
             REOPENED: deterministic completion-integrity check failed -- no model call needed: no photo reference on a 'electrical' ticket, which requires one
      CRITICAL  TCK-00002  Marina Tower A/0801 electrical   points  43  TCH-01   SUSPICIOUS
             REOPENED: deterministic completion-integrity check failed -- no model call needed: closed in 2 minute(s), below the 5-minute floor for a real repair
      CRITICAL  TCK-00013  Marina Tower A/1401 electrical   points  43  TCH-01   dispatched
      CRITICAL  TCK-00001  Marina Tower A/1204 elevator     points  40  TCH-03   dispatched

  DATA GAPS  (4) -- risk this tool cannot see
    TCK-00011: category: unrecognized 'landscaping', scored as baseline
    TCK-00012: reported_at: unparseable date '2026-13-40'
    TCK-00013: technician_id given but time_spent_minutes is missing -- completion record is incomplete
    TCK-00011: no technician on the roster is certified for 'landscaping'

  4 critical   2 high   5 medium   2 low
  closure review: 0 verified   2 reopened
```

Three things in that output are the reason the tool exists:

- **A suspicious completion never reaches a model.** `TCK-00002` closed in
  two minutes; `TCK-00003` has no photo on a trade that requires one. Both
  are reopened deterministically in `cli.py`, before any agent call — there
  is nothing for an agent to add to a completion record that already fails
  on its face.
- **Life-safety bypasses the score entirely, in both directions.** An open
  elevator ticket (`TCK-00001`) and a *closed but suspicious* electrical
  ticket (`TCK-00002`) both land in `CRITICAL` regardless of points, because
  a life-safety category is never something points decide.
- **Dispatch matching load-balances across a run, not just against the
  roster's starting state.** Three `ac` tickets in a row send the first two
  to the least-loaded technician; by the third, that technician's running
  load has caught up and the assignment switches — a test asserts this
  exact tie-break.

## Documentation

- [docs/architecture.md](docs/architecture.md) — the enterprise architecture
  diagram and what each part is (and isn't) responsible for.
- [docs/the-verification-gate.md](docs/the-verification-gate.md) — the
  safety argument: what licenses a citation, every path to `reopened`, what
  the gate does *not* catch, and the token-budget failure mode that looks
  exactly like the gate working.

## Design notes

**All scoring lives in one file, and that is the point.** `rules.py`
computes urgency, the life-safety override, dispatch matching, and
completion-integrity checks. A model is never asked to decide whether a
repair actually happened. The reason is specific rather than ideological: an
invented supporting detail in a closure summary is not obviously wrong to
the resident reading it, and a wrongly-closed real fault is not a bug you
fix in the next release.

**The gate can only reopen, never verify.** There is no code path where the
gate manufactures a verification the reviewer did not itself recommend, and
no path from `reopened` back to `verified`. It fails safe in the one
direction that matters: toward a human seeing the ticket, never away from
one.

**The token budget is set correctly from the first commit.** Thinking is on
by default on the configured model, and a `max_tokens` cap tight enough to
truncate a reply produces a JSON parse error that the gate turns into a
reopen — every ticket would reopen, and the run would read as the gate
correctly failing safe rather than the budget being wrong. That failure mode
was found once, the expensive way, on the first tool in this pattern
(`rasid`); it's closed here from the start rather than re-discovered a third
time.

**The run degrades rather than fails.** No `anthropic` package, no API key,
or an unreachable endpoint prints the reason and falls back to the computed
queue. Every figure the tool exists to produce — bands, dispatch matches,
suspicious flags, data gaps — is present in `--no-agents` mode.

## Limits

- **Not a shipped facilities system.** This is a proposed architecture with
  a real, tested core and citation gate — there is no live tenant portal,
  no real-time technician status, and nothing here posts to a service-charge
  ledger. See [Limits in docs/architecture.md](docs/architecture.md#what-this-repository-does-not-implement).
- **The gate is citation-shaped.** It catches an invented record reference.
  It does not catch a true citation attached to a false characterisation of
  what that record shows — that gap is why every closure, verified or
  reopened, still goes to a facilities manager.
- **Dispatch matching uses a snapshot of technician load.** It does not
  track real-time acceptance, en-route status, or a technician going
  off-shift mid-run.
- **`verified` means "recommended by this tool," not "billed."** Nothing
  here closes a ticket in a system of record or posts a service-charge line
  item — a facilities manager is the sole authority, every time.

## Layout

```
src/ammar/
  rules.py        ALL scoring: urgency, life-safety override, dispatch, integrity
  agents.py       closure drafter, cost reconciler, reviewer, and the gate
  config.py       every threshold, with a source pointer and a verify list
  tickets.py      loose CSV loading, completion parsing, data-gap reporting
  technicians.py  roster loading
  report.py       terminal view + the closure CSV
  cli.py
examples/         13-ticket fixture: life-safety, suspicious completions,
                  load-balanced dispatch, and three deliberately malformed rows
docs/             architecture diagram + the verification-gate safety argument
tests/            rule matching, citation logic, gate, CI guard
```
