# -*- coding: utf-8 -*-
"""Reusable chip recognition results and lock-decision orchestration.

Screen-specific OCR adapters feed this module typed details and template scores.
The module deliberately has no warehouse, Pipeline, Maa, or task-option imports.
"""

from __future__ import annotations

from chip_domain import chip_detail_signature, should_lock_chip


LOCKED_SCORE = 0.85
UNLOCKED_SCORE = 0.75


def classify_lock_scores(scores, required_votes=2):
    values = [float(score) for score in scores]
    locked_votes = sum(score >= LOCKED_SCORE for score in values)
    unlocked_votes = sum(score <= UNLOCKED_SCORE for score in values)
    if locked_votes >= required_votes and unlocked_votes == 0:
        return True
    if unlocked_votes >= required_votes and locked_votes == 0:
        return False
    return None


def evaluate_chip(detail, plan):
    return {
        "signature": chip_detail_signature(detail),
        "desired_locked": should_lock_chip(detail, plan),
    }


def confirms_same_unlock(first_detail, confirmed_detail, plan):
    if first_detail is None or confirmed_detail is None:
        return False
    first = evaluate_chip(first_detail, plan)
    confirmed = evaluate_chip(confirmed_detail, plan)
    return (
        first["signature"] == confirmed["signature"]
        and first["desired_locked"] is False
        and confirmed["desired_locked"] is False
    )
