"""Restaura reservas e visitantes ao estado de dados/*.json e apaga as sessões."""

from . import db
from .config import DB_SESSOES


def main():
    db.restaurar()
    for sufixo in ("", "-wal", "-shm"):
        DB_SESSOES.with_name(DB_SESSOES.name + sufixo).unlink(missing_ok=True)
    print("Dados restaurados e sessões apagadas.")


if __name__ == "__main__":
    main()
