"""The technician roster: who can be dispatched, and how busy they already are."""

import csv
from dataclasses import dataclass, field

ALIASES = {
    "technician_id": ("technician_id", "tech_id", "id"),
    "name": ("name", "technician_name"),
    "trades": ("trades", "trade", "certifications"),
    "current_load": ("current_load", "open_tickets", "load"),
}


@dataclass
class Technician:
    technician_id: str
    name: str = ""
    trades: list = field(default_factory=list)
    current_load: int = 0


def _pick(low: dict, key: str, default=""):
    for alias in ALIASES[key]:
        if low.get(alias):
            return low[alias]
    return default


def load(path: str):
    techs = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            low = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items()}
            tech_id = _pick(low, "technician_id")
            if not tech_id:
                continue
            trades = [t.strip() for t in _pick(low, "trades").split(";") if t.strip()]
            try:
                load_val = int(_pick(low, "current_load", default="0"))
            except ValueError:
                load_val = 0
            techs.append(Technician(
                technician_id=tech_id,
                name=_pick(low, "name"),
                trades=trades,
                current_load=load_val,
            ))
    if not techs:
        raise ValueError(f"no technicians found in {path}")
    return techs
