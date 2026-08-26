"""Terminal report and the closure CSV."""

import csv
from collections import Counter

from .rules import BAND_ORDER

BAND_MARK = {"critical": "  CRITICAL", "high": "     HIGH", "medium": "   MEDIUM", "low": "      low"}
BAND_COLOUR = {"critical": "\033[31m", "high": "\033[31m", "medium": "\033[33m", "low": "\033[90m"}


def terminal(queue, cfg, agentic, tasks=None, use_colour=True, show_low=False):
    L = []
    tint = (lambda b, s: f"{BAND_COLOUR.get(b, '')}{s}\033[0m") if use_colour \
        else (lambda b, s: s)
    tasks_by_id = {t["ticket_id"]: t for t in (tasks or [])}

    L.append("")
    L.append("ammar -- tower maintenance dispatch")
    L.append(f"  as of {queue.today.isoformat()}   "
             f"{'computed + triaged + gated' if agentic else 'computed only'}")
    L.append("")

    counts = Counter(w.band for w in queue.work_orders)
    bands = ("critical", "high", "medium") + (("low",) if show_low else ())
    for band in bands:
        orders = queue.by_band(band)
        if not orders:
            continue
        L.append(f"  {band.upper()}  ({len(orders)})")
        for w in orders:
            loc = f"{w.tower}/{w.unit}" if w.tower else w.unit
            if w.has_completion:
                who = w.completion_technician_id
                state = "SUSPICIOUS" if w.suspicious else "completed"
            else:
                who = w.dispatched_technician_id or "UNASSIGNED"
                state = "dispatched" if w.dispatched_technician_id else "no technician available"
            L.append(f"    {tint(band, BAND_MARK[band])}  {w.ticket_id:<10} "
                     f"{loc:<14} {w.category:<12} points {w.urgency_points:>3}  "
                     f"{who:<8} {state}")
            t = tasks_by_id.get(w.ticket_id)
            if t:
                if t.get("status") == "reopened":
                    L.append(f"             REOPENED: {t.get('status_reason', '')}")
                elif t.get("status") == "verified":
                    L.append(f"             verified: {t.get('rationale', '')[:100]}")
        L.append("")

    if not queue.work_orders:
        L.append("  No tickets in the queue.")
        L.append("")

    if queue.data_gaps:
        L.append(f"  DATA GAPS  ({len(queue.data_gaps)}) -- risk this tool "
                 f"cannot see")
        for ref, note in queue.data_gaps[:10]:
            L.append(f"    {ref}: {note}")
        if len(queue.data_gaps) > 10:
            L.append(f"    ... and {len(queue.data_gaps) - 10} more")
        L.append("")

    summary = "   ".join(f"{counts.get(b, 0)} {b}" for b in BAND_ORDER)
    L.append(f"  {summary}")
    if tasks:
        st = Counter(t.get("status") for t in tasks)
        L.append(f"  closure review: {st.get('verified', 0)} verified   "
                 f"{st.get('reopened', 0)} reopened")
        ungrounded = [t for t in tasks if t.get("ungrounded_citations")]
        if ungrounded:
            L.append(f"  {len(ungrounded)} ticket(s) reopened for citing a "
                     f"record with no computed source")
    L.append("  SLA: " + ", ".join(f"{b} {h}h" for b, h in cfg.sla_hours.items()))
    L.append("")
    L.append(f"  {cfg.verify_note()}")
    L.append("")
    return "\n".join(L)


FIELDNAMES = ["ticket_id", "tower", "unit", "category", "band", "urgency_points",
              "has_completion", "suspicious", "technician_id", "status",
              "status_reason", "recommendation", "summary", "line_item", "rationale"]


def write_csv(path, queue, tasks=None):
    tasks_by_id = {t["ticket_id"]: t for t in (tasks or [])}
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w_ = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        w_.writeheader()
        for w in queue.work_orders:
            t = tasks_by_id.get(w.ticket_id, {})
            technician = w.completion_technician_id or w.dispatched_technician_id
            w_.writerow({
                "ticket_id": w.ticket_id, "tower": w.tower, "unit": w.unit,
                "category": w.category, "band": w.band,
                "urgency_points": w.urgency_points,
                "has_completion": w.has_completion, "suspicious": w.suspicious,
                "technician_id": technician,
                "status": t.get("status", ""),
                "status_reason": t.get("status_reason", ""),
                "recommendation": t.get("recommendation", ""),
                "summary": t.get("summary", ""),
                "line_item": t.get("line_item", ""),
                "rationale": t.get("rationale", ""),
            })
    return path
