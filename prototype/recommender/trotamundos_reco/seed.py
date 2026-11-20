"""Catálogo de ejemplo determinístico (40 alojamientos) y reservas demo."""
from __future__ import annotations

import argparse
import os
import random

from .db import Database, SqlStore
from .domain import AMENITIES, TYPES, ZONES, Accommodation

_PRICE = {"hostel": (15, 35), "apartment": (40, 110), "hotel": (50, 180),
          "boutique": (90, 260), "aparthotel": (60, 150)}
_STARS = {"hostel": (1, 2), "apartment": (2, 4), "hotel": (2, 5),
          "boutique": (3, 5), "aparthotel": (3, 4)}
_LABEL = {"hostel": "Hostel", "apartment": "Depto", "hotel": "Hotel",
          "boutique": "Boutique", "aparthotel": "Aparthotel"}


def build_catalog(n: int = 40, seed: int = 42) -> list:
    rnd = random.Random(seed)
    out = []
    for i in range(1, n + 1):
        t = TYPES[(i - 1) % len(TYPES)]
        zone = ZONES[rnd.randrange(len(ZONES))]
        stars = rnd.randint(*_STARS[t])
        price = round(rnd.uniform(*_PRICE[t]) * (0.85 + 0.1 * stars), 2)
        k = min(len(AMENITIES), 1 + stars + rnd.randint(0, 2))
        amenities = tuple(sorted(rnd.sample(AMENITIES, k)))
        out.append(Accommodation(i, f"{_LABEL[t]} {zone.replace('_', ' ').title()} {i:02d}",
                                 zone, t, stars, price, amenities))
    return out


def seed_catalog(store: SqlStore) -> int:
    items = build_catalog()
    store.upsert_accommodations(items)
    return len(items)


def seed_demo_reservations(store: SqlStore) -> None:
    demo = {"demo-lujo": [34, 29, 24, 19], "demo-mochilero": [1, 6, 11, 16], "demo-nuevo": []}
    for user, ids in demo.items():
        for n, acc in enumerate(ids):
            store.upsert_reservation(f"{user}-r{n}", user, acc, "confirmed")


def main() -> None:
    p = argparse.ArgumentParser(description="Carga el catálogo de ejemplo")
    p.add_argument("--demo", action="store_true", help="agrega reservas demo")
    args = p.parse_args()
    store = SqlStore(Database(os.environ.get("RECO_DB_PATH", "reco.db")))
    print(f"{seed_catalog(store)} alojamientos cargados")
    if args.demo:
        seed_demo_reservations(store)
        print("reservas demo cargadas")


if __name__ == "__main__":
    main()
