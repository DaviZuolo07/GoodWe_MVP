"""
Linha de comando do totem virtual. Rodar da RAIZ do repositório:

    python -m totem_virtual painel             página em http://127.0.0.1:8765
    python -m totem_virtual roteiro            teste de aceitação
    ... --bolso                                usa o backend em memória (sem Supabase)
"""

import argparse
import sys

from . import config


def _preparar(args):
    """Devolve (cfg, http, base). Com --bolso, o backend roda dentro deste processo."""
    if args.bolso:
        from . import backend_de_bolso
        http, cfg = backend_de_bolso.subir()
        print("Backend DE BOLSO: FastAPI de backend/ + Supabase falso em memória. Tudo simulado.")
        return cfg, http, ""
    cfg = config.carregar()
    if not cfg.pronta():
        sys.exit("Faltam DEVICE_ID e DEVICE_KEY_HEX em totem_virtual/.env.\n"
                 "Eles saem de `python provisionar.py placa-v2 ...` (rodado pelo Daniel) e chegam "
                 "por canal privado.\nPara testar sem eles: acrescente --bolso.")
    try:
        bytes.fromhex(cfg.chave_hex)
    except ValueError:
        sys.exit("DEVICE_KEY_HEX não é hexadecimal. Copie de novo a saída do provisionar.py.")
    return cfg, None, None


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m totem_virtual",
                                description="Totem virtual: gêmeo digital do ESP32 (ADR-020)")
    sub = p.add_subparsers(dest="comando", required=True)
    for nome, ajuda in (("painel", "página local para operar o totem"),
                        ("roteiro", "roda os cenários e imprime passou/falhou")):
        s = sub.add_parser(nome, help=ajuda)
        s.add_argument("--bolso", action="store_true",
                       help="backend em memória (backend/ + supabase_falso), sem Supabase")
    sub.choices["painel"].add_argument("--porta", type=int, default=None)
    sub.choices["roteiro"].add_argument("--espera", type=float, default=None,
                                        help="segundos de espera por reação do backend (padrão 90)")
    args = p.parse_args()
    cfg, http, base = _preparar(args)

    if args.comando == "roteiro":
        from . import roteiro
        return roteiro.rodar(cfg, http=http, base=base, espera_s=args.espera)

    from . import painel
    return painel.servir(cfg, http=http, base=base, porta=args.porta or cfg.painel_porta)


if __name__ == "__main__":
    raise SystemExit(main())
