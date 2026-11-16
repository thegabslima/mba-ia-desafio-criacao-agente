"""Tools dos especialistas.

Nenhuma tool recebe apartamento como parâmetro: o apartamento vem sempre do
state da sessão, gravado uma única vez na criação (Garantia 2).
"""

import re
import unicodedata
from datetime import date

from google.adk.tools import ToolContext

from . import db, regulamento


def _apartamento(tool_context: ToolContext) -> str:
    apartamento = tool_context.state.get("apartamento")
    if not apartamento:
        raise RuntimeError("Sessão sem apartamento definido.")
    return apartamento


def _slug(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-")


def _resolver_area(area: str) -> dict | None:
    alvo = _slug(area)
    for a in db.listar_areas():
        if alvo in (a["id"], _slug(a["nome"])) or alvo in a["id"] or a["id"] in alvo:
            return a
    return None


def _data_valida(data: str) -> bool:
    try:
        date.fromisoformat(data)
        return len(data) == 10
    except ValueError:
        return False


def _erro_area(area: str) -> dict:
    ids = ", ".join(a["id"] for a in db.listar_areas())
    return {"status": "erro", "mensagem": f"Área '{area}' não existe. Áreas: {ids}."}


_ERRO_DATA = {"status": "erro", "mensagem": "Data inválida. Use o formato AAAA-MM-DD."}


# ---------------- reservas ----------------

def listar_areas() -> dict:
    """Lista as áreas comuns que podem ser reservadas, com id, nome e taxa em reais (0 = sem cobrança)."""
    return {"areas": db.listar_areas()}


def minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista as reservas ativas do apartamento do morador desta conversa."""
    return {"reservas": db.reservas_do_apartamento(_apartamento(tool_context))}


def verificar_disponibilidade(area: str, data: str) -> dict:
    """Informa se uma área está livre ou ocupada numa data (AAAA-MM-DD). Não informa de quem é a reserva."""
    a = _resolver_area(area)
    if not a:
        return _erro_area(area)
    if not _data_valida(data):
        return _ERRO_DATA
    return {"area": a["id"], "data": data, "disponivel": db.data_livre(a["id"], data)}


def reservar_area(area: str, data: str, tool_context: ToolContext) -> dict:
    """Reserva uma área comum para o apartamento do morador numa data (AAAA-MM-DD).

    Áreas com taxa geram cobrança e só são reservadas depois que o morador aprova
    pela rota de confirmações do sistema.
    """
    apartamento = _apartamento(tool_context)
    a = _resolver_area(area)
    if not a:
        return _erro_area(area)
    if not _data_valida(data):
        return _ERRO_DATA
    if not db.data_livre(a["id"], data):
        return {"status": "recusada", "mensagem": "A área já está reservada nessa data."}

    # Garantia 1: cobrança só com confirmação vinda do sistema (rota de confirmações).
    if a["taxa"] > 0:
        confirmacao = tool_context.tool_confirmation
        if confirmacao is None:
            tool_context.request_confirmation(
                hint=f"Reserva de {a['nome']} em {data} gera cobrança de R$ {a['taxa']:.2f}.",
                payload={"area": a["id"], "data": data, "taxa": a["taxa"]},
            )
            return {
                "status": "aguardando_confirmacao",
                "mensagem": "A reserva gera cobrança e aguarda a aprovação do morador no aplicativo.",
            }
        if not confirmacao.confirmed:
            return {"status": "negada", "mensagem": "O morador negou a cobrança. Nada foi reservado."}

    # Garantia 5: a exclusividade é decidida no INSERT (índice único), não na conferência acima.
    codigo = db.criar_reserva(apartamento, a["id"], data)
    if codigo is None:
        return {"status": "recusada", "mensagem": "A área já está reservada nessa data."}
    return {
        "status": "reservada",
        "codigo": codigo,
        "area": a["id"],
        "data": data,
        "cobranca": a["taxa"],
    }


def cancelar_reserva(area: str, data: str, tool_context: ToolContext) -> dict:
    """Cancela uma reserva do próprio apartamento, identificada pela área e data (AAAA-MM-DD)."""
    a = _resolver_area(area)
    if not a:
        return _erro_area(area)
    codigo = db.cancelar_reserva(_apartamento(tool_context), a["id"], data)
    if codigo is None:
        return {
            "status": "nao_encontrada",
            "mensagem": "Não há reserva dessa área nessa data entre as reservas do seu apartamento.",
        }
    return {"status": "cancelada", "codigo": codigo, "area": a["id"], "data": data}


# ---------------- visitantes ----------------

def meus_visitantes(tool_context: ToolContext) -> dict:
    """Lista os visitantes autorizados do apartamento do morador desta conversa."""
    return {"visitantes": db.visitantes_do_apartamento(_apartamento(tool_context))}


def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """Autoriza a entrada de um visitante (nome completo) no prédio numa data (AAAA-MM-DD).

    Libera acesso, então só é gravada depois que o morador aprova pela rota de
    confirmações do sistema. Mensagens na conversa não contam como aprovação.
    """
    apartamento = _apartamento(tool_context)
    nome = nome.strip()
    if not nome:
        return {"status": "erro", "mensagem": "Informe o nome do visitante."}
    if not _data_valida(data):
        return _ERRO_DATA

    # Garantia 1: acesso só com confirmação vinda do sistema.
    confirmacao = tool_context.tool_confirmation
    if confirmacao is None:
        tool_context.request_confirmation(
            hint=f"Liberar a entrada de {nome} em {data}.",
            payload={"nome": nome, "data": data},
        )
        return {
            "status": "aguardando_confirmacao",
            "mensagem": "A autorização aguarda a aprovação do morador no aplicativo.",
        }
    if not confirmacao.confirmed:
        return {"status": "negada", "mensagem": "O morador negou a autorização. Nada foi gravado."}

    db.autorizar_visitante(apartamento, nome, data)
    return {"status": "autorizado", "nome": nome, "data": data}


# ---------------- regulamento ----------------

def buscar_no_regulamento(assunto: str) -> dict:
    """Busca no regulamento interno e devolve apenas o capítulo que trata do assunto (ex.: 'piscina horário domingo')."""
    return regulamento.buscar(assunto)
