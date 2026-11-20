from __future__ import annotations

import os
from dataclasses import dataclass, field

from .domain import Weights


@dataclass(frozen=True)
class Settings:
    db_path: str = "reco.db"
    jwt_secret: str = ""
    token_ttl_seconds: int = 3600
    dev_token_endpoint: bool = False
    cycle_seconds: int = 60
    ttl_seconds: int = 600
    top_k: int = 10
    min_profile_interactions: int = 2
    feedback_alpha: float = 0.3
    max_retries: int = 3
    retry_backoff_seconds: float = 0.5
    valid_reservation_statuses: tuple = ("confirmed", "completed")
    weights: Weights = field(default_factory=Weights)

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        e = os.environ if env is None else env
        secret = e.get("RECO_JWT_SECRET", "")
        if not secret:
            raise RuntimeError("RECO_JWT_SECRET es obligatorio")
        statuses = e.get("RECO_VALID_RESERVATION_STATUSES", "confirmed,completed")
        return cls(
            db_path=e.get("RECO_DB_PATH", "reco.db"),
            jwt_secret=secret,
            token_ttl_seconds=int(e.get("RECO_TOKEN_TTL_SECONDS", "3600")),
            dev_token_endpoint=e.get("RECO_DEV_TOKEN_ENDPOINT", "false").lower() == "true",
            cycle_seconds=int(e.get("RECO_CYCLE_SECONDS", "60")),
            ttl_seconds=int(e.get("RECO_TTL_SECONDS", "600")),
            top_k=int(e.get("RECO_TOP_K", "10")),
            min_profile_interactions=int(e.get("RECO_MIN_PROFILE_INTERACTIONS", "2")),
            feedback_alpha=float(e.get("RECO_FEEDBACK_ALPHA", "0.3")),
            max_retries=int(e.get("RECO_MAX_RETRIES", "3")),
            retry_backoff_seconds=float(e.get("RECO_RETRY_BACKOFF_SECONDS", "0.5")),
            valid_reservation_statuses=tuple(s.strip().lower() for s in statuses.split(",") if s.strip()),
            weights=Weights.parse(e.get("RECO_WEIGHTS", "")),
        )
