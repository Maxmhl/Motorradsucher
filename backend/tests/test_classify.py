"""Stufe 4: 'Unpassender Zustand' schlaegt 'unpassende Optik'."""

from __future__ import annotations

from app.models import FinalClass, Listing, ListingStatus
from app.pipeline.stage_classify import classify
from app.pipeline.stage_rank import _fallback_score


def _listing(**kwargs) -> Listing:
    listing = Listing(url="https://example.org/x", status=ListingStatus.new)
    for key, value in kwargs.items():
        setattr(listing, key, value)
    return listing


def test_text_ok_and_optical_ok_is_passend():
    listing = _listing(
        status=ListingStatus.optical_ok,
        text_verdict={"verdict": "ok"},
        optical_verdict={"verdict": "ok"},
    )
    assert classify(listing) is FinalClass.passend


def test_text_ok_and_optical_rejected_is_unpassende_optik():
    listing = _listing(
        status=ListingStatus.optical_rejected,
        text_verdict={"verdict": "ok"},
        optical_verdict={"verdict": "rejected"},
    )
    assert classify(listing) is FinalClass.unpassende_optik


def test_text_rejected_is_unpassender_zustand():
    listing = _listing(status=ListingStatus.text_rejected, text_verdict={"verdict": "rejected"})
    assert classify(listing) is FinalClass.unpassender_zustand


def test_zustand_wins_over_optik():
    """Die entscheidende Regel aus dem Plan."""
    listing = _listing(
        status=ListingStatus.optical_rejected,
        text_verdict={"verdict": "rejected"},
        optical_verdict={"verdict": "rejected"},
    )
    assert classify(listing) is FinalClass.unpassender_zustand


def test_fallback_score_prefers_cheaper_newer_lower_km():
    ok_high = {"verdict": "ok", "confidence": 0.9}
    ok_low = {"verdict": "ok", "confidence": 0.4}
    good = _listing(price=4200, year=2021, km=9000, text_verdict=ok_high)
    weak = _listing(price=5000, year=2018, km=29000, text_verdict=ok_low)
    assert _fallback_score(good) > _fallback_score(weak)
    assert 0 <= _fallback_score(weak) <= 100
