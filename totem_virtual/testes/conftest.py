"""Os testes rodam da raiz do repositório:  python -m pytest totem_virtual/testes -q"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
for pasta in (RAIZ, Path(__file__).resolve().parent):
    if str(pasta) not in sys.path:
        sys.path.insert(0, str(pasta))
