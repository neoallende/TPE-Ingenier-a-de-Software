"""Worker del generador: ejecuta un ciclo cada RECO_CYCLE_SECONDS."""
from __future__ import annotations

import logging
import signal
import threading

from .config import Settings
from .db import Database, SqlStore
from .service import RecommenderService

log = logging.getLogger("trotamundos_reco")


def run_forever(service: RecommenderService, interval: float, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            report = service.run_cycle()
            log.info("ciclo: %d ok, %d con error", len(report.ok), len(report.failed))
        except Exception:
            log.exception("el ciclo falló; se reintenta en el próximo intervalo")
        stop.wait(interval)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    service = RecommenderService(SqlStore(Database(settings.db_path)), settings)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run_forever(service, settings.cycle_seconds, stop)


if __name__ == "__main__":
    main()
