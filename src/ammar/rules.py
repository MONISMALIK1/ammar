"""All arithmetic lives here, and only here.

This is the deliberate boundary of the whole tool. Urgency scores, technician
dispatch, and whether a completion record is even plausible are computed in
plain Python from the ticket and the roster. A language model is never asked
to decide any of them -- it is only ever handed the result and asked to
write the account of it.

The reason is specific rather than ideological: "close this ticket, the
compressor was replaced" is a sentence a resident reads and a service charge
bills against. An invented supporting fact in that sentence is not obviously
wrong to the resident reading it, and a wrongly-closed real fault is a
callback, a dispute, and eventually a service-charge audit finding -- not a
bug you fix in the next release.
"""

from dataclasses import dataclass, field
from datetime import date
from collections import defaultdict

from .config import Config

BAND_ORDER = ("critical", "high", "medium", "low")


@dataclass
class WorkOrder:
    ticket_id: str
    tower: str
    unit: str
    category: str
    tenant_name: str
    band: str
    urgency_points: int
    life_safety: bool
    dispatched_technician_id: str = ""      # computed match, open tickets only
    completion_technician_id: str = ""      # who actually did it, closed tickets only
    parts_used: list = field(default_factory=list)
    photo_ref: str = ""
    meter_reading: str = ""
    has_completion: bool = False
    suspicious: bool = False
    suspicious_reason: str = ""

    def facts(self):
        """Every citation an agent is allowed to reference for this ticket."""
        out = {
            "ticket_id": self.ticket_id,
            "work_order_id": f"WO-{self.ticket_id.split('-')[-1]}",
            "technician_id": self.completion_technician_id,
            "parts_used": list(self.parts_used),
        }
        if self.photo_ref:
            out["photo_ref"] = self.photo_ref
        return out


def urgency_points(ticket, today: date, cfg: Config) -> int:
    points = cfg.category_points.get(ticket.category, 0)
    if ticket.reported_at:
        age_days = (today - ticket.reported_at).days
        if age_days > cfg.age_grace_days:
            points += min(cfg.age_points_per_day * (age_days - cfg.age_grace_days),
                          cfg.age_points_cap)
    return points


def band_for(ticket, points: int, cfg: Config) -> str:
    if ticket.category in cfg.life_safety_categories:
        return "critical"
    if points >= cfg.high_threshold:
        return "high"
    if points >= cfg.medium_threshold:
        return "medium"
    return "low"


def suspicious_completion(ticket, cfg: Config):
    """A deterministic integrity check on the completion record itself.

    Independent of anything an agent says -- a closure this fast, or one
    missing the minimum proof a trade requires, does not get a plain-language
    account written about it. It gets reopened.
    """
    if ticket.time_spent_minutes is not None and ticket.time_spent_minutes < cfg.min_plausible_minutes:
        return True, (f"closed in {ticket.time_spent_minutes} minute(s), below "
                      f"the {cfg.min_plausible_minutes}-minute floor for a "
                      f"real repair")
    if ticket.category in cfg.categories_requiring_photo and not ticket.photo_ref:
        return True, f"no photo reference on a '{ticket.category}' ticket, which requires one"
    return False, ""


def match_technician(ticket, technicians, load_counter, cfg: Config):
    """Least-loaded qualified technician, ties broken by ID for reproducibility."""
    candidates = [t for t in technicians if ticket.category in t.trades]
    if not candidates:
        return None, f"no technician on the roster is certified for '{ticket.category}'"
    candidates.sort(key=lambda t: (t.current_load + load_counter[t.technician_id],
                                   t.technician_id))
    chosen = candidates[0]
    if chosen.current_load + load_counter[chosen.technician_id] >= cfg.max_technician_load:
        return None, f"every certified technician is at or above the {cfg.max_technician_load}-ticket load cap"
    load_counter[chosen.technician_id] += 1
    return chosen.technician_id, None


@dataclass
class Queue:
    today: date
    work_orders: list = field(default_factory=list)
    data_gaps: list = field(default_factory=list)

    def by_band(self, band):
        return [w for w in self.work_orders if w.band == band]

    def needs_closure_review(self):
        """Tickets with a completion record that a human eventually has to
        see: either it was suspicious on its face, or it needs the triage
        pipeline's account."""
        return [w for w in self.work_orders if w.has_completion]


def assess(tickets, technicians, cfg: Config, today: date) -> Queue:
    gaps = [(t.ticket_id, note) for t in tickets for note in t.parse_notes]
    load_counter = defaultdict(int)
    orders = []

    for t in tickets:
        points = urgency_points(t, today, cfg)
        band = band_for(t, points, cfg)
        life_safety = t.category in cfg.life_safety_categories

        w = WorkOrder(
            ticket_id=t.ticket_id, tower=t.tower, unit=t.unit,
            category=t.category, tenant_name=t.tenant_name,
            band=band, urgency_points=points, life_safety=life_safety,
        )

        if t.has_completion:
            w.has_completion = True
            w.completion_technician_id = t.technician_id
            w.parts_used = t.parts_used
            w.photo_ref = t.photo_ref
            w.meter_reading = t.meter_reading
            w.suspicious, w.suspicious_reason = suspicious_completion(t, cfg)
        else:
            tech_id, note = match_technician(t, technicians, load_counter, cfg)
            if tech_id:
                w.dispatched_technician_id = tech_id
            elif note:
                gaps.append((t.ticket_id, note))

        orders.append(w)

    orders.sort(key=lambda w: (BAND_ORDER.index(w.band), -w.urgency_points, w.ticket_id))
    return Queue(today=today, work_orders=orders, data_gaps=gaps)
