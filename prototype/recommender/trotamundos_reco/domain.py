"""Dominio puro: vectores, perfil, filtros obligatorios, ranking y métricas.

Sin I/O ni dependencias externas, para poder testearlo de forma aislada.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

ZONES = ("palermo", "recoleta", "centro", "san_telmo", "puerto_madero", "belgrano")
TYPES = ("hostel", "apartment", "hotel", "boutique", "aparthotel")
AMENITIES = ("wifi", "breakfast", "pool", "gym", "spa", "parking",
             "pet_friendly", "air_conditioning")


@dataclass(frozen=True)
class Accommodation:
    id: int
    name: str
    zone: str
    type: str
    stars: int
    price_per_night: float
    amenities: tuple = ()


@dataclass(frozen=True)
class Weights:
    stars: float = 1.0
    price: float = 1.0
    zone: float = 1.0
    type: float = 1.0
    amenities: float = 1.0

    @classmethod
    def parse(cls, text: str) -> "Weights":
        """Formato: 'stars=1,price=1.5,zone=1,type=0.5,amenities=1'."""
        values = {}
        for part in filter(None, (p.strip() for p in text.split(","))):
            key, _, raw = part.partition("=")
            if key not in cls.__dataclass_fields__:
                raise ValueError(f"peso desconocido: {key!r}")
            values[key] = float(raw)
            if values[key] < 0:
                raise ValueError("los pesos no pueden ser negativos")
        return cls(**values)


@dataclass(frozen=True)
class FeatureSpace:
    """Define cómo se codifica un alojamiento como vector (ADR-020, D2)."""
    price_min: float
    price_max: float
    weights: Weights = field(default_factory=Weights)

    @classmethod
    def fit(cls, catalog, weights: Weights) -> "FeatureSpace":
        prices = [a.price_per_night for a in catalog]
        return cls(min(prices, default=0.0), max(prices, default=0.0), weights)

    @property
    def dim(self) -> int:
        return 2 + len(ZONES) + len(TYPES) + len(AMENITIES)

    def feature_names(self) -> list:
        return (["stars", "price"] + [f"zone:{z}" for z in ZONES]
                + [f"type:{t}" for t in TYPES] + [f"amenity:{a}" for a in AMENITIES])

    def encode(self, a: Accommodation) -> list:
        w = self.weights
        span = self.price_max - self.price_min
        price = (a.price_per_night - self.price_min) / span if span > 0 else 0.0
        stars = (min(max(a.stars, 1), 5) - 1) / 4
        v = [w.stars * stars, w.price * min(max(price, 0.0), 1.0)]
        v += [w.zone * (1.0 if a.zone == z else 0.0) for z in ZONES]
        v += [w.type * (1.0 if a.type == t else 0.0) for t in TYPES]
        v += [w.amenities * (1.0 if m in a.amenities else 0.0) for m in AMENITIES]
        return v


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def mean_vector(vectors):
    vectors = list(vectors)
    if not vectors:
        return None
    n = len(vectors)
    return [sum(col) / n for col in zip(*vectors)]


@dataclass(frozen=True)
class Profile:
    vector: list
    interactions: int
    source: str = "history"  # "history" | "feedback"

    @property
    def norm(self) -> float:
        return math.sqrt(sum(x * x for x in self.vector))


def feedback_signal(kind: str, rating=None) -> float:
    """accept → +1, reject → −1, rating 1–5 → (r−3)/2 ∈ [−1, 1]."""
    if kind == "accept":
        return 1.0
    if kind == "reject":
        return -1.0
    if kind == "rating":
        if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5:
            raise ValueError("rating debe ser un entero entre 1 y 5")
        return (rating - 3) / 2
    raise ValueError(f"kind inválido: {kind!r}")


def apply_feedback(profile: Profile, item_vector, signal: float, alpha: float) -> Profile:
    """p' = p + α·s·(v − p); s>0 acerca el perfil al ítem, s<0 lo aleja."""
    if not -1.0 <= signal <= 1.0:
        raise ValueError("signal fuera de [-1, 1]")
    new = [max(0.0, p + alpha * signal * (v - p))
           for p, v in zip(profile.vector, item_vector)]
    return Profile(new, profile.interactions + 1, "feedback")


@dataclass(frozen=True)
class Constraints:
    """Restricciones obligatorias: nunca se violan (ADR-020, D8)."""
    max_price_per_night: float = None
    min_stars: int = None
    zones: tuple = ()
    types: tuple = ()
    required_amenities: tuple = ()

    def satisfied_by(self, a: Accommodation) -> bool:
        if self.max_price_per_night is not None and a.price_per_night > self.max_price_per_night:
            return False
        if self.min_stars is not None and a.stars < self.min_stars:
            return False
        if self.zones and a.zone not in self.zones:
            return False
        if self.types and a.type not in self.types:
            return False
        return all(m in a.amenities for m in self.required_amenities)

    def to_dict(self) -> dict:
        return {"max_price_per_night": self.max_price_per_night, "min_stars": self.min_stars,
                "zones": list(self.zones), "types": list(self.types),
                "required_amenities": list(self.required_amenities)}

    @classmethod
    def from_dict(cls, d: dict) -> "Constraints":
        c = cls(
            max_price_per_night=d.get("max_price_per_night"),
            min_stars=d.get("min_stars"),
            zones=tuple(d.get("zones") or ()),
            types=tuple(d.get("types") or ()),
            required_amenities=tuple(d.get("required_amenities") or ()),
        )
        if c.max_price_per_night is not None and c.max_price_per_night < 0:
            raise ValueError("max_price_per_night inválido")
        if c.min_stars is not None and not 1 <= c.min_stars <= 5:
            raise ValueError("min_stars debe estar entre 1 y 5")
        for values, vocab, label in ((c.zones, ZONES, "zones"), (c.types, TYPES, "types"),
                                     (c.required_amenities, AMENITIES, "required_amenities")):
            bad = [x for x in values if x not in vocab]
            if bad:
                raise ValueError(f"{label} desconocidos: {bad}")
        return c


@dataclass(frozen=True)
class ScoredItem:
    accommodation_id: int
    name: str
    score: float
    zone: str
    type: str
    stars: int
    price_per_night: float


@dataclass(frozen=True)
class RankResult:
    items: list
    strategy: str   # "personalized" | "cold_start"
    reason: str     # "ok" | "no_candidates"


def recommend(profile, candidates, constraints, space, k, min_interactions,
              popularity, excluded_ids=frozenset()) -> RankResult:
    personalized = (profile is not None and profile.interactions >= min_interactions
                    and profile.norm > 0.0)
    strategy = "personalized" if personalized else "cold_start"
    eligible = [a for a in candidates
                if a.id not in excluded_ids and constraints.satisfied_by(a)]
    if not eligible:
        return RankResult([], strategy, "no_candidates")

    if personalized:
        scored = [(cosine(profile.vector, space.encode(a)), a) for a in eligible]
        scored.sort(key=lambda t: (-t[0], t[1].id))
    else:  # cold start: popularidad, luego estrellas, luego precio
        top = max((popularity.get(a.id, 0) for a in eligible), default=0) or 1
        scored = [(popularity.get(a.id, 0) / top, a) for a in eligible]
        scored.sort(key=lambda t: (-t[0], -t[1].stars, t[1].price_per_night, t[1].id))

    items = [ScoredItem(a.id, a.name, round(s, 6), a.zone, a.type, a.stars,
                        a.price_per_night) for s, a in scored[:k]]
    return RankResult(items, strategy, "ok")


def precision_at_k(recommended_ids, relevant_ids, k: int) -> float:
    if k <= 0:
        raise ValueError("k debe ser > 0")
    top = list(recommended_ids)[:k]
    if not top:
        return 0.0
    relevant = set(relevant_ids)
    return sum(1 for i in top if i in relevant) / k


def ndcg_at_k(recommended_ids, gains: dict, k: int) -> float:
    if k <= 0:
        raise ValueError("k debe ser > 0")
    dcg = sum(gains.get(i, 0.0) / math.log2(pos + 2)
              for pos, i in enumerate(list(recommended_ids)[:k]))
    ideal = sorted((g for g in gains.values() if g > 0), reverse=True)[:k]
    idcg = sum(g / math.log2(pos + 2) for pos, g in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0
