"""Thresholds, and where each one came from.

Every number in this file is a policy or risk-appetite parameter, not a fact
of nature. Urgency weights, SLA targets, and what counts as a plausible
repair time are all choices a facilities manager or an owners' association
board makes and revisits. Nothing here is hardcoded into the rules logic.
Override any of it with `--config my.json`.

**None of these defaults are RERA or contractual advice.** Confirm against
the building's own service charge budget, the management contract's SLA
schedule, and current RERA guidance before relying on a band or a bill.
"""

import json
from dataclasses import dataclass, asdict, field

RERA = "https://www.rera.gov.ae/"


@dataclass
class Config:
    # --- urgency scoring ---------------------------------------------------
    # Points per trade category. VERIFY: these are the building's own risk
    # appetite, not a regulatory schedule.
    category_points: dict = field(default_factory=lambda: {
        "elevator": 40, "electrical": 35, "ac": 30, "plumbing": 25,
        "common_area": 10, "other": 5,
    })

    # A ticket in one of these categories is always dispatched as critical,
    # regardless of score -- a life-safety system does not wait on points.
    life_safety_categories: list = field(default_factory=lambda: [
        "elevator", "electrical",
    ])

    # A ticket accrues age points once it has sat open longer than the grace
    # period, capped so an ancient low-priority ticket cannot out-rank a
    # fresh life-safety one on points alone (life-safety bypasses points
    # entirely, so this cap mostly protects the high/medium boundary).
    age_grace_days: int = 1
    age_points_per_day: int = 8
    age_points_cap: int = 40

    high_threshold: int = 50
    medium_threshold: int = 25

    # --- dispatch -----------------------------------------------------------
    # A technician is eligible if their trades include the ticket's
    # category. Ties broken by technician_id for reproducibility.
    max_technician_load: int = 8

    # --- completion integrity -------------------------------------------
    # A closure this fast is either miscoded or not actually done. VERIFY:
    # tune per trade if one category genuinely closes faster than others.
    min_plausible_minutes: int = 5
    # Trades where a photo is the minimum acceptable proof of work.
    categories_requiring_photo: list = field(default_factory=lambda: [
        "ac", "elevator", "electrical", "plumbing",
    ])

    # --- SLA -----------------------------------------------------------
    # VERIFY: internal targets, usually set by the management contract, not
    # a statutory clock -- but an owners' association board treats them like
    # one at the annual meeting.
    sla_hours: dict = field(default_factory=lambda: {
        "critical": 2, "high": 8, "medium": 24, "low": 72,
    })

    sources: dict = field(default_factory=lambda: {
        "category_points": "building risk appetite, not regulatory",
        "life_safety_categories": "management contract + RERA life-safety guidance",
        "sla_hours": "management contract SLA schedule",
    })

    VERIFY_FIELDS = (
        "category_points", "life_safety_categories", "sla_hours",
        "min_plausible_minutes",
    )

    def to_dict(self):
        return asdict(self)

    @classmethod
    def load(cls, path=None):
        cfg = cls()
        if not path:
            return cfg
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        unknown = set(data) - set(asdict(cfg))
        if unknown:
            raise ValueError(f"unknown config keys: {', '.join(sorted(unknown))}")
        for k, v in data.items():
            setattr(cfg, k, v)
        return cfg

    def verify_note(self):
        return ("Urgency and SLA figures are defaults and change often. "
                "Verify " + ", ".join(self.VERIFY_FIELDS)
                + f" against the building's management contract and "
                  f"{RERA} before relying on a band or a bill.")
