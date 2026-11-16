"""Busca no regulamento: devolve só o capítulo que trata do assunto perguntado."""

import re
import unicodedata
from functools import lru_cache

from .config import DADOS


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def _termos(texto: str) -> set[str]:
    termos = set()
    for palavra in re.findall(r"[a-z0-9]+", _normalizar(texto)):
        if len(palavra) < 4:
            continue
        termos.add(palavra[:-1] if palavra.endswith("s") else palavra)
    return termos


@lru_cache
def capitulos() -> list[tuple[str, str]]:
    texto = (DADOS / "regulamento.md").read_text(encoding="utf-8")
    partes = re.split(r"(?m)^## ", texto)[1:]
    resultado = []
    for parte in partes:
        titulo, _, corpo = parte.partition("\n")
        resultado.append((titulo.strip(), corpo.strip()))
    return resultado


def buscar(pergunta: str) -> dict:
    termos = _termos(pergunta)
    melhor, melhor_pontos = None, 0
    for titulo, corpo in capitulos():
        palavras_titulo = _termos(titulo)
        palavras_corpo = [
            p[:-1] if p.endswith("s") else p
            for p in re.findall(r"[a-z0-9]+", _normalizar(corpo))
        ]
        pontos = sum(10 for t in termos if t in palavras_titulo)
        pontos += sum(palavras_corpo.count(t) for t in termos)
        if pontos > melhor_pontos:
            melhor, melhor_pontos = (titulo, corpo), pontos
    if not melhor:
        return {"encontrado": False, "mensagem": "Nenhum capítulo do regulamento trata desse assunto."}
    return {"encontrado": True, "capitulo": melhor[0], "texto": melhor[1]}
