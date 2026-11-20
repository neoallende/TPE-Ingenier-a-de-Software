"""Puertos (ADR-020, D1). El resto del sistema depende solo de RecommendationProvider."""
from __future__ import annotations

from typing import Protocol


class RecommendationProvider(Protocol):
    def get_recommendations(self, user_id: str) -> dict: ...

    def submit_feedback(self, user_id: str, feedback_id: str, accommodation_id: int,
                        kind: str, rating: int = None) -> dict: ...
