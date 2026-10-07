"""Human-readable sequential identifiers (CF-1042, ACT-0007, ...)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from models.entities import Counter

START = {"CF": 1036, "PLN": 0, "ACT": 0, "APR": 0, "TSK": 0, "RSV": 0, "MSG": 0, "HLD": 0}
WIDTH = {"CF": 4}


def next_id(session: Session, prefix: str) -> str:
    c = session.get(Counter, prefix)
    if c is None:
        c = Counter(name=prefix, value=START.get(prefix, 0))
        session.add(c)
    c.value += 1
    session.flush()
    return f"{prefix}-{c.value:0{WIDTH.get(prefix, 4)}d}"
