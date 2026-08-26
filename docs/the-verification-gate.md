# The Verification Gate

The safety argument for letting a model near a maintenance closure.

## The problem this exists for

The sentence this tool produces is:

> Replaced the compressor capacitor using [PART-118]; the unit is cooling
> normally again.

That sentence gets acted on. A resident reads it and stops calling; a
facilities manager reads it and signs off; a service charge gets billed
against it. A model that writes a fluent, specific-sounding closure with an
invented part number or a fabricated detail is not obviously wrong to
anyone reading it -- fluency is the failure mode. There is no surface signal
separating a citation to a part the technician actually logged from one the
model made up, and a wrongly-closed real fault is a callback, a dispute, and
eventually a service-charge audit finding, not a bug report.

So the model is not asked to invent what happened on site, and it is not
trusted not to.

## The split

```
tickets.csv + technicians.csv
    |
    +-- rules.py            urgency scoring, life-safety override, dispatch
    |                       matching, completion-integrity checks -- all
    |                       computed in plain Python
    |
    +-- facts()             the citable evidence, per work order
    |       |
    |       +-- closure_drafter    resident-facing account
    |       +-- cost_reconciler    service-charge line item
    |       +-- dispute_reviewer   recommends verified or reopen
    |       |
    |       +-- gate()       runs last, always
    |
  closures.csv  +  terminal report
```

`rules.py` opens with the boundary stated plainly, and nothing outside it
decides whether a repair actually happened. The agents receive the
completion record as a set of citable IDs and are permitted to explain, cost,
and recommend against them. They are not permitted to introduce a citation
that was not handed to them.

## How the restriction is enforced

Not by asking. The system prompts do ask -- `CLOSURE_SYSTEM` says *cite
every factual claim using the bracketed IDs you are given* -- but a prompt is
a request, and requests are occasionally declined by things that cannot tell
you they declined.

The enforcement is `check_citations()`. It extracts every bracketed ID from
the model's output and subtracts the set of IDs licensed by the work order's
completion record. Anything left over is a citation the model invented, and
the ticket is reopened with the offending ID named:

```
REOPENED: model cited a record with no computed source: PART-9999
```

A reopened ticket is never shown to a facilities manager as a quiet
closure. It appears with its reason, and the run reports how many tickets
were reopened for exactly this.

### What a citation looks like

`[TCK-00042]`, `[WO-00042]`, `[TCH-03]`, `[PART-118]`, `[PHOTO-3303]` -- a
short uppercase prefix, a hyphen, and an identifier. `citations_in()`
matches that shape and nothing else, so a plain number in prose ("it took 45
minutes") is never mistaken for a citation; only a bracketed record
reference is checked.

### What licenses a citation

`expand_evidence()` builds the allowed set directly from the work order's
`facts()`: the ticket's own ID, the work order ID, the technician who
actually did the job, and every part logged against the completion record.
If a citation is not one of those exact strings, it is ungrounded, full
stop -- there is no fuzzy matching, no "close enough."

### What the gate cannot do

The gate is citation-shaped. It catches an invented reference. It does not
catch an invented *characterisation* of a real one -- "the technician found
extensive corrosion" citing a real `[PHOTO-3303]` that in fact shows nothing
of the kind would pass, because the citation itself is grounded. That gap is
why the closure drafter's system prompt is instructed to state only what the
completion record shows, and why every closure -- verified or reopened --
still goes to a facilities manager for sign-off. The gate is a floor, not a
ceiling.

## Ordering, and the direction it can move

`gate()` runs after every agent, always, and it only ever pushes toward
reopening:

| condition | status |
|---|---|
| any agent errored | `reopened` |
| output contains an ungrounded citation | `reopened` |
| the reviewer itself recommended reopening | `reopened` |
| everything grounded and the reviewer recommended verified | `verified` |

There is no path from `reopened` back to `verified`. There is also no path
where the gate manufactures a verification the reviewer did not itself
recommend -- the gate can only take away a `verified` status, never grant
one the reviewer withheld. A ticket that errored during closure drafting is
reopened before its citations are even examined, because a partial account
is not a safe account.

A suspicious completion record never reaches this pipeline at all. It is
detected in `rules.py` -- closed faster than physically plausible, or
missing the photo a trade requires -- and reopened in `cli.py` before any
model call, because there is nothing for an agent to add to a completion
record that already fails on its face.

`verified` means "recommended by this tool", not "billed". Nothing here
posts a service-charge line item or closes a ticket in any system of
record -- a facilities manager is the sole authority, on every ticket, every
time.

## The failure mode that imitates the gate

Every ticket reopened is the gate's success state, which makes it a bad
place to hide a configuration error. One in particular is worth naming,
because it produces a run where *every* ticket reopens and the report reads
like the gate correctly failing safe.

Thinking is on by default on the configured model, and `max_tokens` bounds
thinking and response text together. Set that budget too tight and the
model's JSON is cut off mid-object. `json.loads` then raises, `_handle`
catches it into `task["error"]`, and `gate()` reopens the ticket --
correctly, by its own rules, because a partial task is not a safe task. The
output would read:

```
  closure review: 0 verified   13 reopened
```

Nothing about that line says the budget was wrong. So `_structured()` checks
`stop_reason` for `max_tokens` before parsing and raises with the cap named,
and `MAX_TOKENS` is set to 16000 -- well above what these short JSON replies
need. Two tests assert this directly: that the budget stays loose enough to
leave room for thinking, and that a truncated reply is reported as a
truncated reply rather than as a parse failure. This was found once, the
expensive way, while building the first sibling tool in this pattern
(`rasid`); it is fixed here from the first commit rather than being
re-discovered a third time.

The general rule this is an instance of: when a safety mechanism's trigger
is also a plausible symptom of misconfiguration, the mechanism has to
distinguish the two itself. A human reading the summary will not.

## Running without models at all

`--no-agents` produces the computed queue and the closure CSV with every
review column empty. Every figure this tool exists to produce is present in
that mode -- urgency bands, dispatch matches, suspicious flags, data gaps.
The agents add the plain-language closure, the cost line item, and the
recommendation, and nothing else.

If the `anthropic` package is missing or the API is unreachable, the run
does not fail. It prints the reason and falls back to the computed queue:

```
ammar: the `anthropic` package is not installed -- run `pip install anthropic`
ammar: falling back to the computed queue.
```

There is a CI guard, `tests/check_closures.py`, asserting that `--no-agents`
leaves every review column empty and that suspicious completions are still
pre-reopened deterministically -- so a run that made no model calls can
never show a drafted closure, and a completion that fails on its face is
never silently accepted because the model layer happened to be off.
