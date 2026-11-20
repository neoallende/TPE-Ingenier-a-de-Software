"""Recomendador local (implementa RecommendationProvider). ADR-020."""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from .auth import Principal
from .config import Settings
from .domain import (Constraints, FeatureSpace, Profile, apply_feedback, feedback_signal,
                     mean_vector, ndcg_at_k, precision_at_k, recommend)

log = logging.getLogger("trotamundos_reco")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CycleReport:
    ok: list
    failed: dict


class RecommenderService:
    def __init__(self, store, settings: Settings, clock=utcnow, sleep=time.sleep):
        self.store, self.s, self.clock, self._sleep = store, settings, clock, sleep

    # --- helpers --------------------------------------------------------
    def _iso(self, dt=None) -> str:
        return (dt or self.clock()).isoformat()

    def _space(self, catalog) -> FeatureSpace:
        return FeatureSpace.fit(catalog, self.s.weights)

    def _infer_from_history(self, user_id, catalog, space):
        by_id = {a.id: a for a in catalog}
        ids = self.store.accommodation_ids_for(user_id, self.s.valid_reservation_statuses)
        vecs = [space.encode(by_id[i]) for i in ids if i in by_id]
        mean = mean_vector(vecs)
        return Profile(mean, len(vecs), "history") if mean else None

    def _load_profile(self, user_id, catalog, space):
        stored = self.store.get_profile(user_id)
        if stored and stored.source == "feedback":
            return stored
        inferred = self._infer_from_history(user_id, catalog, space)
        if inferred:
            self.store.save_profile(user_id, inferred, self._iso())
            return inferred
        return stored

    # --- generación (idempotente: upsert por user_id) --------------------
    def generate_for_user(self, user_id: str) -> None:
        now = self.clock()
        catalog = self.store.catalog()
        space = self._space(catalog)
        profile = self._load_profile(user_id, catalog, space)
        excluded = {a for a, sig in self.store.latest_signals(user_id).items() if sig < 0}
        result = recommend(profile, catalog, self.store.get_constraints(user_id), space,
                           self.s.top_k, self.s.min_profile_interactions,
                           self.store.popularity(self.s.valid_reservation_statuses), excluded)
        self.store.save_set(user_id, [asdict(i) for i in result.items], result.strategy,
                            result.reason, self._iso(now),
                            self._iso(now + timedelta(seconds=self.s.ttl_seconds)))

    def _with_retries(self, fn):
        for attempt in range(1, self.s.max_retries + 1):
            try:
                return fn()
            except Exception:
                if attempt == self.s.max_retries:
                    raise
                self._sleep(self.s.retry_backoff_seconds * 2 ** (attempt - 1))

    def run_cycle(self) -> CycleReport:
        report = CycleReport([], {})
        for uid in self.store.active_user_ids():
            try:
                self._with_retries(lambda u=uid: self.generate_for_user(u))
                report.ok.append(uid)
            except Exception as exc:  # el set previo se conserva hasta su TTL
                log.warning("falló la generación para %s: %r", uid, exc)
                report.failed[uid] = repr(exc)
        return report

    # --- RecommendationProvider ----------------------------------------
    def get_recommendations(self, user_id: str) -> dict:
        rec = self.store.get_set(user_id)
        base = {"user_id": user_id, "items": [], "strategy": None, "reason": None,
                "generated_at": None, "expires_at": None}
        if rec is None:
            return {**base, "status": "none"}
        expired = self.clock() >= datetime.fromisoformat(rec["expires_at"])
        view = {**base, **{k: rec[k] for k in ("strategy", "reason", "generated_at", "expires_at")}}
        if expired:
            return {**view, "status": "expired", "items": []}
        return {**view, "status": "fresh", "items": rec["items"]}

    def submit_feedback(self, user_id, feedback_id, accommodation_id, kind, rating=None) -> dict:
        if not isinstance(feedback_id, str) or not 0 < len(feedback_id) <= 64:
            raise ValueError("feedback_id obligatorio (1–64 caracteres)")
        signal = feedback_signal(kind, rating)
        catalog = self.store.catalog()
        item = next((a for a in catalog if a.id == accommodation_id), None)
        if item is None:
            raise LookupError(f"alojamiento {accommodation_id} inexistente")
        space = self._space(catalog)

        def update(stored):
            if stored and stored.source == "feedback":
                base = stored
            else:
                base = (self._infer_from_history(user_id, catalog, space)
                        or Profile([0.0] * space.dim, 0, "history"))
            return apply_feedback(base, space.encode(item), signal, self.s.feedback_alpha)

        applied = self.store.record_feedback(user_id, feedback_id, accommodation_id, kind,
                                             rating, signal, self._iso(), update)
        return {"feedback_id": feedback_id, "applied": applied, "signal": signal}

    # --- restricciones y perfil ----------------------------------------
    def set_constraints(self, user_id: str, data: dict) -> dict:
        c = Constraints.from_dict(data)
        self.store.set_constraints(user_id, c, self._iso())
        return c.to_dict()

    def get_constraints(self, user_id: str) -> dict:
        return self.store.get_constraints(user_id).to_dict()

    def profile_view(self, user_id: str) -> dict:
        catalog = self.store.catalog()
        space = self._space(catalog)
        p = self._load_profile(user_id, catalog, space)
        if p is None:
            return {"user_id": user_id, "interactions": 0, "source": None, "features": {},
                    "cold_start": True}
        return {"user_id": user_id, "interactions": p.interactions, "source": p.source,
                "cold_start": p.interactions < self.s.min_profile_interactions or p.norm == 0,
                "features": dict(zip(space.feature_names(), (round(x, 4) for x in p.vector)))}

    # --- administración con auditoría (ADR-019) -------------------------
    def admin_view_profile(self, principal: Principal, target_user_id: str) -> dict:
        if not principal.is_admin:
            raise PermissionError("se requiere rol admin")
        self.store.add_audit(principal.sub, target_user_id, "view_profile", self._iso())
        return self.profile_view(target_user_id)

    def admin_audit_log(self, principal: Principal, limit: int = 100) -> list:
        if not principal.is_admin:
            raise PermissionError("se requiere rol admin")
        return self.store.list_audit(limit)

    # --- evaluación offline (ADR-020, D8) -------------------------------
    def evaluate_user(self, user_id: str, k: int = None) -> dict:
        """Precision@K y NDCG@K contra el feedback del propio usuario."""
        k = k or self.s.top_k
        rec = self.store.get_set(user_id)
        ids = [i["accommodation_id"] for i in rec["items"]] if rec else []
        signals = self.store.latest_signals(user_id)
        relevant = [a for a, s in signals.items() if s > 0]
        gains = {a: s for a, s in signals.items() if s > 0}
        return {"k": k, "precision_at_k": precision_at_k(ids, relevant, k),
                "ndcg_at_k": ndcg_at_k(ids, gains, k), "judged_items": len(signals)}
