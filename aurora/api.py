"""API HTTP do assistente do Residencial Aurora."""

import asyncio
import logging
from collections import defaultdict
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from google.adk.runners import Runner
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types
from pydantic import BaseModel

from . import db
from .agents import app as adk_app
from .config import APP_NAME, DB_SESSOES

logger = logging.getLogger("aurora")

# Nome da function call que o ADK usa para pedir confirmação de uma tool.
CONFIRMACAO = "adk_request_confirmation"

session_service = SqliteSessionService(str(DB_SESSOES))
runner = Runner(app=adk_app, session_service=session_service)
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.inicializar()
    yield


api = FastAPI(title="Residencial Aurora", lifespan=lifespan)


class NovaSessao(BaseModel):
    apartamento: str


class Mensagem(BaseModel):
    texto: str


class RespostaConfirmacao(BaseModel):
    id: str
    confirmado: bool


# ---------------- helpers ----------------

async def _sessao(session_id: str):
    apartamento = db.apartamento_da_sessao(session_id)
    if apartamento is None:
        raise HTTPException(404, "Sessão não encontrada.")
    sessao = await session_service.get_session(
        app_name=APP_NAME, user_id=apartamento, session_id=session_id
    )
    if sessao is None:
        raise HTTPException(404, "Sessão não encontrada.")
    return sessao


def _pendentes(sessao) -> list[dict]:
    """Confirmações pedidas pelo ADK (adk_request_confirmation) que ainda não foram respondidas.

    Derivadas dos eventos persistidos da sessão, então sobrevivem ao reinício.
    """
    pedidos: dict[str, dict] = {}
    for evento in sessao.events:
        for fc in evento.get_function_calls():
            if fc.name == CONFIRMACAO and fc.id:
                args = fc.args or {}
                original = args.get("originalFunctionCall") or {}
                conf = args.get("toolConfirmation") or {}
                detalhes = dict(original.get("args") or {})
                if isinstance(conf.get("payload"), dict):
                    detalhes.update(conf["payload"])
                pedidos[fc.id] = {
                    "id": fc.id,
                    "acao": original.get("name", ""),
                    "descricao": conf.get("hint", ""),
                    "detalhes": detalhes,
                }
        if evento.author == "user":
            for fr in evento.get_function_responses():
                pedidos.pop(fr.id, None)
    return list(pedidos.values())


async def _executar(sessao, mensagem: types.Content) -> dict:
    textos: list[str] = []
    async for evento in runner.run_async(
        user_id=sessao.user_id, session_id=sessao.id, new_message=mensagem
    ):
        if evento.author == "user" or not evento.content or evento.partial:
            continue
        texto = "".join(
            p.text for p in (evento.content.parts or []) if p.text and not p.thought
        ).strip()
        if texto:
            textos.append(texto)
    atual = await _sessao(sessao.id)
    return {"resposta": textos[-1] if textos else "", "confirmacoes_pendentes": _pendentes(atual)}


# ---------------- conversa ----------------

@api.post("/sessoes", status_code=201)
async def criar_sessao(body: NovaSessao):
    # Garantia 2: o apartamento é gravado uma única vez, no state da sessão,
    # e é dali que as tools o leem. Nenhuma rota ou tool altera esse valor depois.
    sessao = await session_service.create_session(
        app_name=APP_NAME, user_id=body.apartamento, state={"apartamento": body.apartamento}
    )
    db.registrar_sessao(sessao.id, body.apartamento)
    return {"session_id": sessao.id}


@api.post("/sessoes/{session_id}/mensagens")
async def enviar_mensagem(session_id: str, body: Mensagem):
    async with _locks[session_id]:
        sessao = await _sessao(session_id)
        msg = types.Content(role="user", parts=[types.Part(text=body.texto)])
        return await _executar(sessao, msg)


@api.post("/sessoes/{session_id}/confirmacoes")
async def responder_confirmacao(session_id: str, body: RespostaConfirmacao):
    async with _locks[session_id]:
        sessao = await _sessao(session_id)
        # Garantia 1: só aceita id pendente NESTA sessão; já respondida ou desconhecida -> 409.
        if body.id not in {p["id"] for p in _pendentes(sessao)}:
            raise HTTPException(409, "Não existe confirmação pendente com esse id nesta sessão.")
        # Resposta no formato que o ADK espera para retomar a tool que pediu a confirmação.
        msg = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=body.id,
                        name=CONFIRMACAO,
                        response={"confirmed": body.confirmado},
                    )
                )
            ],
        )
        return await _executar(sessao, msg)


@api.get("/sessoes/{session_id}/eventos")
async def eventos(session_id: str):
    sessao = await _sessao(session_id)
    return [e.model_dump(mode="json", exclude_none=True, by_alias=True) for e in sessao.events]


# ---------------- verificação (lê o banco direto, sem modelo) ----------------

@api.get("/apartamentos/{numero}/reservas")
async def reservas(numero: str):
    return db.reservas_do_apartamento(numero)


@api.get("/apartamentos/{numero}/visitantes")
async def visitantes(numero: str):
    return db.visitantes_do_apartamento(numero)


def main():
    uvicorn.run(api, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
