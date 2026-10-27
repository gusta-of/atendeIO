#!/usr/bin/env python3
"""Gera histórico de fluxo SINTÉTICO (para demonstrar e testar a tela de análise).

    ATENDEIO_DATA=/tmp/demo python scripts/seed_flow.py --camera 1 --days 14 --yes

Padrão fictício: almoço (12–14h) e jantar (19–22h), mais cheio na sexta e no sábado, terça de tarde vazia, e
algumas lacunas (câmera fora do ar) para mostrar a cobertura. NÃO use contra o banco real: por segurança o script
recusa câmeras que já têm histórico (a menos que `--force`) e exige `--yes`."""

import argparse
import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atendeio.config import Settings  # noqa: E402
from atendeio.db import Database  # noqa: E402
from atendeio.repositories.flow import FlowRepository  # noqa: E402


def level(hour: int, weekday: int) -> float:
    """Média de pessoas ao mesmo tempo, por hora local e dia da semana (0 = segunda)."""
    if not 11 <= hour < 23:
        return 0.0
    base = 2.0
    base += 7.0 * math.exp(-((hour - 13) ** 2) / 1.6)            # almoço
    base += 11.0 * math.exp(-((hour - 20.5) ** 2) / 2.2)         # jantar
    base *= {4: 1.5, 5: 1.7, 6: 1.2, 1: 0.7}.get(weekday, 1.0)   # sexta/sábado/domingo mais cheios, terça fraca
    if weekday == 1 and 15 <= hour <= 16:
        base *= 0.35
    return base


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--yes", action="store_true", help="confirma que isto grava dados SINTÉTICOS")
    ap.add_argument("--force", action="store_true", help="grava mesmo se a câmera já tem histórico")
    args = ap.parse_args()
    if not args.yes:
        raise SystemExit("Isto grava dados SINTÉTICOS no banco. Confirme com --yes (e use ATENDEIO_DATA=/tmp/demo).")

    cfg = Settings.from_env()
    db = Database(cfg.db_path)
    db.init()
    repo = FlowRepository(db)
    tz = ZoneInfo(cfg.timezone)
    if repo.hours(args.camera, 0, 10 ** 9) and not args.force:
        raise SystemExit("Essa câmera já tem histórico real. Nada foi gravado (use --force só em banco de demonstração).")

    rnd = random.Random(7)
    now = datetime.now(tz)
    batches, written = [], 0
    for d in range(args.days, 0, -1):
        day = (now - timedelta(days=d)).date()
        for h in range(11, 23):
            start = datetime(day.year, day.month, day.day, h, tzinfo=tz)
            if rnd.random() < 0.04:
                continue                                          # lacuna: câmera fora do ar nessa hora
            avg = max(0.0, level(h, day.weekday()) * rnd.uniform(0.85, 1.15))
            samples = 3600
            peak = int(round(avg * rnd.uniform(1.3, 1.9))) + (1 if avg > 0.5 else 0)
            hour_key = int(start.timestamp() // 3600)
            minutes = {}
            for m in range(60):                                   # minuto a minuto (a análise do dia usa)
                a = max(0.0, avg * rnd.uniform(0.7, 1.3))
                minutes[hour_key * 60 + m] = [60, int(round(a * 60)), int(a) + 1 if a > 0.4 else 0, int(a * 0.6)]
            batches.append({"camera_id": args.camera, "minute": minutes,
                            "hour": {hour_key: [samples, int(round(avg * samples)), peak, 0]},
                            "area": {(1, hour_key): [samples, int(round(avg * 0.45 * samples)), max(1, peak // 2), "Mesa 1", "mesa"],
                                     (2, hour_key): [samples, int(round(avg * 0.25 * samples)), max(1, peak // 3), "Balcão", "balcao"]}})
            written += 1
    for i in range(0, len(batches), 50):
        repo.apply(batches[i:i + 50])
    print(f"{written} horas SINTÉTICAS gravadas para a câmera {args.camera} em {cfg.db_path}")


if __name__ == "__main__":
    main()
