"""Carga .env sin ejecutar código ni interpolar valores (incluidos hashes con $)."""
import os
from pathlib import Path


def load_env(path=None):
    path = Path(path or Path(__file__).resolve().parent.parent / '.env')
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if not key.isidentifier():
            raise ValueError('Nombre de variable no válido en .env.')
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if value:
            os.environ.setdefault(key, value)
