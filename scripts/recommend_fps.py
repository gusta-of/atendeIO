#!/usr/bin/env python3
"""Reconhece o hardware desta máquina e recomenda uma faixa de FPS para as câmeras do atendeIO.

    python scripts/recommend_fps.py                  # detecta o hardware, MEDE o YOLO e recomenda
    python scripts/recommend_fps.py --cameras 4      # considerando 4 câmeras analisando ao mesmo tempo
    python scripts/recommend_fps.py --no-benchmark   # só estima pelos núcleos (não carrega o modelo)
    python scripts/recommend_fps.py --json           # saída para outras ferramentas

Não altera nada: só lê o hardware e mede. Para aplicar, use a tela de Configurações do app (engrenagem).
Dica: feche outros programas pesados antes de medir; a medição usa o processador a fundo por alguns segundos."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atendeio import hardware  # noqa: E402
from atendeio.config import Settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cameras", type=int, default=1, help="quantas câmeras vão analisar ao mesmo tempo (padrão: 1)")
    ap.add_argument("--no-benchmark", action="store_true", help="não mede: estima pelos núcleos do processador")
    ap.add_argument("--frames", type=int, default=10, help="quadros da medição (padrão: 10)")
    ap.add_argument("--json", action="store_true", help="imprime JSON em vez de texto")
    args = ap.parse_args()

    info = hardware.detect()
    bench_ms = None
    if not args.no_benchmark:
        from atendeio.vision.detector import Detector
        cfg = Settings.from_env()
        if not args.json:
            print("Medindo o reconhecimento nesta máquina (alguns segundos)...", file=sys.stderr)
        bench_ms = hardware.benchmark(Detector(cfg.model_path, cfg.conf_threshold), args.frames,
                                      progress=None if args.json else lambda i, n: print(f"  quadro {i}/{n}", file=sys.stderr, end="\r"))
        if not args.json:
            print(" " * 30, file=sys.stderr, end="\r")
        if bench_ms is None and not args.json:
            print("Não consegui medir (modelo indisponível): usando estimativa.", file=sys.stderr)
    rec = hardware.recommend(info, bench_ms, args.cameras)
    if args.json:
        print(json.dumps(hardware.as_dict(info, rec), ensure_ascii=False, indent=2))
    else:
        print("\n".join(["", "SEU HARDWARE", *hardware.hardware_lines(info), "", "RECOMENDAÇÃO DE FPS", *hardware.recommendation_lines(rec), ""]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
