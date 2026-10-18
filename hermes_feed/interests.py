"""Interest weighting: every signal decays exponentially, the sum decides the interest's state.

Pure functions with an injectable ``now`` so drift is testable without waiting weeks.
"""
from __future__ import annotations

import re
from typing import Iterable, Tuple

# Signal kinds the agent, the hook, and the UI can record, and how much each one counts.
SIGNAL_VALUES = {
    "explicit": 3.0,   # "I'm really into X" / user stated it directly
    "manual": 3.0,     # added by hand in the Interests panel
    "open": 2.5,       # opened the story: the strongest feed signal (counted once per story)
    "save": 2.0,
    "like": 1.5,       # positive, but weaker than actually reading it
    "mention": 1.0,    # came up in conversation
    "less": -2.0,      # "show less of this" after dismissing a story
    "dismiss": -2.5,   # "not for me": hides the story and cools its interests
    "abandon": -4.0,   # "I'm not into X any more"
}

ACTIVE_THRESHOLD = 0.75  # one chat mention stays active ~6 days at the default half-life
FADING_THRESHOLD = 0.3
DEFAULT_HALF_LIFE_DAYS = 14.0

DAY = 86400.0


def signal_value(kind: str) -> float:
    if kind not in SIGNAL_VALUES:
        raise ValueError(f"unknown signal kind {kind!r}; expected one of {sorted(SIGNAL_VALUES)}")
    return SIGNAL_VALUES[kind]


def decayed_weight(signals: Iterable[Tuple[float, float]], now: float,
                   half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> float:
    """Sum of ``value * 0.5 ** (age / half_life)`` over ``(value, at_epoch)`` pairs."""
    half_life = max(half_life_days, 0.01) * DAY
    total = 0.0
    for value, at in signals:
        age = max(0.0, now - at)
        total += value * 0.5 ** (age / half_life)
    return total


def state_for(weight: float, *, pinned: bool = False, muted: bool = False) -> str:
    if muted:
        return "muted"
    if pinned:
        return "active"
    if weight >= ACTIVE_THRESHOLD:
        return "active"
    if weight >= FADING_THRESHOLD:
        return "fading"
    return "dormant"


def effective_weight(weight: float, *, pinned: bool = False, muted: bool = False) -> float:
    if muted:
        return 0.0
    if pinned:
        return max(weight, ACTIVE_THRESHOLD)
    return weight


def search_budget(weights: dict, total: int = 24, max_interests: int = 12, per_interest_max: int = 3) -> dict:
    """Split ``total`` searches over the strongest interests, proportional to weight (1..3 each)."""
    ranked = sorted(((k, w) for k, w in weights.items() if w >= FADING_THRESHOLD),
                    key=lambda kv: kv[1], reverse=True)[:max_interests]
    if not ranked:
        return {}
    weight_sum = sum(w for _, w in ranked)
    return {k: max(1, min(per_interest_max, round(total * w / weight_sum))) for k, w in ranked}


_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize_label(label: str) -> str:
    """Key used to dedupe interests: lowercase, punctuation-insensitive, trailing plural 's' dropped."""
    words = [w for w in _NON_WORD.split(label.lower()) if w]
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words)
