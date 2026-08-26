"""The ticket queue: what was reported, and what a technician actually did."""

import csv
from dataclasses import dataclass, field
from datetime import date, datetime

ALIASES = {
    "ticket_id": ("ticket_id", "id", "ref"),
    "tower": ("tower", "building"),
    "unit": ("unit", "apartment", "flat"),
    "category": ("category", "trade", "type"),
    "tenant_name": ("tenant_name", "resident_name", "reported_by"),
    "reported_at": ("reported_at", "date_reported", "created_at"),
    "technician_id": ("technician_id", "tech_id", "assigned_to"),
    "time_spent_minutes": ("time_spent_minutes", "duration_minutes", "minutes"),
    "parts_used": ("parts_used", "parts"),
    "photo_ref": ("photo_ref", "photo", "photo_id"),
    "meter_reading": ("meter_reading", "reading"),
    "closed_at": ("closed_at", "date_closed", "completed_at"),
}

KNOWN_CATEGORIES = {"elevator", "electrical", "ac", "plumbing", "common_area", "other"}


@dataclass
class Ticket:
    ticket_id: str
    tower: str = ""
    unit: str = ""
    category: str = "other"
    tenant_name: str = ""
    reported_at: date = None
    technician_id: str = ""
    time_spent_minutes: int = None
    parts_used: list = field(default_factory=list)
    photo_ref: str = ""
    meter_reading: str = ""
    closed_at: date = None
    parse_notes: list = field(default_factory=list)

    @property
    def has_completion(self) -> bool:
        return bool(self.technician_id) and self.time_spent_minutes is not None


def _pick(low: dict, key: str, default=""):
    for alias in ALIASES[key]:
        if low.get(alias):
            return low[alias]
    return default


def _parse_date(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None, None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date(), None
        except ValueError:
            continue
    return None, f"unparseable date '{raw}'"


def load(path: str):
    tickets = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=1):
            low = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items()}
            ticket_id = _pick(low, "ticket_id", default=f"TCK-{i:05d}")
            if not ticket_id and not _pick(low, "tenant_name"):
                continue

            notes = []
            category = (_pick(low, "category") or "other").lower()
            if category not in KNOWN_CATEGORIES:
                notes.append(f"category: unrecognized '{category}', scored as baseline")

            reported, note = _parse_date(_pick(low, "reported_at"))
            if note:
                notes.append(f"reported_at: {note}")

            closed, note = _parse_date(_pick(low, "closed_at"))
            if note:
                notes.append(f"closed_at: {note}")

            tech_id = _pick(low, "technician_id")
            minutes_raw = _pick(low, "time_spent_minutes")
            minutes = None
            if minutes_raw:
                try:
                    minutes = int(float(minutes_raw))
                except ValueError:
                    notes.append(f"time_spent_minutes: unparseable '{minutes_raw}'")

            # One of the two completion fields present without the other is
            # a partial completion record, not a clean one -- surfaced, not
            # silently treated as either "open" or "closed".
            if bool(tech_id) and not minutes_raw:
                notes.append("technician_id given but time_spent_minutes is "
                             "missing -- completion record is incomplete")
            elif minutes_raw and not tech_id:
                notes.append("time_spent_minutes given but technician_id is "
                             "missing -- completion record is incomplete")

            parts = [p.strip() for p in _pick(low, "parts_used").split(";") if p.strip()]

            tickets.append(Ticket(
                ticket_id=ticket_id,
                tower=_pick(low, "tower"),
                unit=_pick(low, "unit"),
                category=category,
                tenant_name=_pick(low, "tenant_name"),
                reported_at=reported,
                technician_id=tech_id,
                time_spent_minutes=minutes,
                parts_used=parts,
                photo_ref=_pick(low, "photo_ref"),
                meter_reading=_pick(low, "meter_reading"),
                closed_at=closed,
                parse_notes=notes,
            ))
    if not tickets:
        raise ValueError(
            f"no tickets found in {path} -- expected a column named one of "
            f"{ALIASES['ticket_id']}"
        )
    return tickets
