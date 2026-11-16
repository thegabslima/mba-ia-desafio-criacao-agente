"""Armazenamento do condomínio em SQLite.

As regras críticas de dados moram aqui, no banco, e não no prompt:
- índice único parcial garante uma reserva ativa por área e data (Garantia 5);
- reservas canceladas não são apagadas, então o código (PRIMARY KEY) nunca repete.
"""

import json
import secrets
import sqlite3
from contextlib import contextmanager

from .config import DADOS, DB_CONDOMINIO

SCHEMA = """
CREATE TABLE IF NOT EXISTS apartamentos (
    numero  TEXT PRIMARY KEY,
    morador TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS areas (
    id   TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    taxa REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reservas (
    codigo      TEXT PRIMARY KEY,
    apartamento TEXT NOT NULL,
    area        TEXT NOT NULL REFERENCES areas(id),
    data        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ativa'
);
-- Exclusividade no instante da gravação: no máximo UMA reserva ativa por área/data.
CREATE UNIQUE INDEX IF NOT EXISTS ux_reserva_ativa
    ON reservas(area, data) WHERE status = 'ativa';
CREATE TABLE IF NOT EXISTS visitantes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    apartamento TEXT NOT NULL,
    nome        TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessoes (
    session_id  TEXT PRIMARY KEY,
    apartamento TEXT NOT NULL
);
"""


@contextmanager
def conectar():
    con = sqlite3.connect(DB_CONDOMINIO, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    try:
        yield con
    finally:
        con.close()


def inicializar():
    with conectar() as con:
        con.executescript(SCHEMA)
        vazio = con.execute("SELECT COUNT(*) FROM areas").fetchone()[0] == 0
    if vazio:
        restaurar()


def _ler(nome):
    return json.loads((DADOS / nome).read_text(encoding="utf-8"))


def restaurar():
    """Volta apartamentos, áreas, reservas e visitantes ao estado de dados/*.json."""
    with conectar() as con:
        con.executescript(SCHEMA)
        con.execute("BEGIN IMMEDIATE")
        for tabela in ("reservas", "visitantes", "apartamentos", "areas", "sessoes"):
            con.execute(f"DELETE FROM {tabela}")
        con.executemany(
            "INSERT INTO apartamentos(numero, morador) VALUES (:numero, :morador)",
            _ler("apartamentos.json"),
        )
        con.executemany(
            "INSERT INTO areas(id, nome, taxa) VALUES (:id, :nome, :taxa)",
            _ler("areas.json"),
        )
        con.executemany(
            "INSERT INTO reservas(codigo, apartamento, area, data) "
            "VALUES (:codigo, :apartamento, :area, :data)",
            _ler("reservas.json"),
        )
        con.executemany(
            "INSERT INTO visitantes(apartamento, nome, data) VALUES (:apartamento, :nome, :data)",
            _ler("visitantes.json"),
        )
        con.execute("COMMIT")


# ---------- sessões ----------

def registrar_sessao(session_id: str, apartamento: str):
    with conectar() as con:
        con.execute(
            "INSERT INTO sessoes(session_id, apartamento) VALUES (?, ?)",
            (session_id, apartamento),
        )


def apartamento_da_sessao(session_id: str) -> str | None:
    with conectar() as con:
        row = con.execute(
            "SELECT apartamento FROM sessoes WHERE session_id = ?", (session_id,)
        ).fetchone()
    return row["apartamento"] if row else None


# ---------- áreas ----------

def listar_areas() -> list[dict]:
    with conectar() as con:
        return [dict(r) for r in con.execute("SELECT id, nome, taxa FROM areas")]


def obter_area(area_id: str) -> dict | None:
    with conectar() as con:
        row = con.execute("SELECT id, nome, taxa FROM areas WHERE id = ?", (area_id,)).fetchone()
    return dict(row) if row else None


# ---------- reservas ----------

def reservas_do_apartamento(apartamento: str) -> list[dict]:
    with conectar() as con:
        rows = con.execute(
            "SELECT codigo, area, data FROM reservas "
            "WHERE apartamento = ? AND status = 'ativa' ORDER BY data, area",
            (apartamento,),
        )
        return [dict(r) for r in rows]


def data_livre(area: str, data: str) -> bool:
    """Só diz se está livre. Nunca devolve de quem é a reserva."""
    with conectar() as con:
        row = con.execute(
            "SELECT 1 FROM reservas WHERE area = ? AND data = ? AND status = 'ativa'",
            (area, data),
        ).fetchone()
    return row is None


def criar_reserva(apartamento: str, area: str, data: str) -> str | None:
    """Grava a reserva. Devolve o código, ou None se a data já estiver ocupada.

    Não há "conferir e depois gravar": o INSERT é a própria conferência. Se outra
    reserva ativa entrou antes, o índice único ux_reserva_ativa recusa a gravação.
    """
    with conectar() as con:
        while True:
            codigo = f"RSV-{secrets.token_hex(4).upper()}"
            try:
                con.execute(
                    "INSERT INTO reservas(codigo, apartamento, area, data) VALUES (?, ?, ?, ?)",
                    (codigo, apartamento, area, data),
                )
                return codigo
            except sqlite3.IntegrityError as e:
                if "reservas.codigo" in str(e):
                    continue  # código já usado (inclusive por reserva cancelada): gera outro
                return None  # violou ux_reserva_ativa: data ocupada


def cancelar_reserva(apartamento: str, area: str, data: str) -> str | None:
    """Cancela a reserva ativa do PRÓPRIO apartamento. Devolve o código cancelado ou None."""
    with conectar() as con:
        row = con.execute(
            "UPDATE reservas SET status = 'cancelada' "
            "WHERE apartamento = ? AND area = ? AND data = ? AND status = 'ativa' "
            "RETURNING codigo",
            (apartamento, area, data),
        ).fetchone()
    return row["codigo"] if row else None


# ---------- visitantes ----------

def visitantes_do_apartamento(apartamento: str) -> list[dict]:
    with conectar() as con:
        rows = con.execute(
            "SELECT nome, data FROM visitantes WHERE apartamento = ? ORDER BY data, id",
            (apartamento,),
        )
        return [dict(r) for r in rows]


def autorizar_visitante(apartamento: str, nome: str, data: str):
    with conectar() as con:
        con.execute(
            "INSERT INTO visitantes(apartamento, nome, data) VALUES (?, ?, ?)",
            (apartamento, nome, data),
        )
