# Residencial Aurora — assistente virtual (Google ADK)

API em Python que expõe o assistente dos moradores: reservas de áreas comuns, autorização de visitantes e dúvidas sobre o regulamento. O modelo conduz a conversa; as regras críticas estão no código e no banco.

## Arquitetura

```
assistente_aurora (principal)
├── especialista_reservas    (sub-agente, via transferência)
├── especialista_visitantes  (sub-agente, via transferência)
└── especialista_regulamento (AgentTool)
```

| Agente | Responsabilidade | Como é acionado | Por quê |
|---|---|---|---|
| `assistente_aurora` | Entende o pedido e encaminha. Não tem tools de dados nem o regulamento nas instruções. | Raiz do `App` | Mantém o contexto do principal enxuto. |
| `especialista_reservas` | Listar áreas, ver disponibilidade, listar, reservar e cancelar reservas. | `transfer_to_agent` | A conversa pode ter várias trocas (ex.: confirmar cobrança); a tool que pede confirmação fica neste agente e o Runner devolve a resposta da confirmação a ele. |
| `especialista_visitantes` | Listar e autorizar visitantes. | `transfer_to_agent` | Mesmo motivo: autorizar exige confirmação e a retomada volta ao autor da chamada. |
| `especialista_regulamento` | Responde dúvidas consultando `dados/regulamento.md`. | `AgentTool` | Roda numa sessão própria em memória; só a resposta final volta para a sessão do morador, então o texto do regulamento não entra no histórico. |

Código: [aurora/agents.py](aurora/agents.py) (agentes), [aurora/tools.py](aurora/tools.py) (tools), [aurora/db.py](aurora/db.py) (SQLite), [aurora/api.py](aurora/api.py) (FastAPI + Runner).

Armazenamento: `var/condominio.db` (dados do condomínio) e `var/sessoes.db` (sessões do ADK via `SqliteSessionService`). Os arquivos de `dados/` são só o estado inicial.

## Garantias

**1. Cobrança ou acesso só com confirmação**
- [aurora/tools.py](aurora/tools.py) — `reservar_area` (quando `taxa > 0`) e `autorizar_visitante` chamam `tool_context.request_confirmation(...)` e só gravam quando `tool_context.tool_confirmation.confirmed` é verdadeiro. Esse valor só existe quando chega uma `FunctionResponse` de `adk_request_confirmation`; texto do morador ("já confirmei") não produz isso.
- [aurora/api.py](aurora/api.py) — `_pendentes` deriva as pendências dos eventos persistidos (pedidos `adk_request_confirmation` sem resposta). `responder_confirmacao` devolve `409` para qualquer `id` fora dessa lista (inexistente ou já respondido) e, se válido, envia a `FunctionResponse` ao Runner, que retoma a tool no agente que pediu.

**2. Cada sessão pertence a um apartamento**
- [aurora/api.py](aurora/api.py) — `criar_sessao` grava `state={"apartamento": ...}` uma única vez.
- [aurora/tools.py](aurora/tools.py) — `_apartamento(tool_context)` lê o apartamento do state. Nenhuma tool recebe apartamento como parâmetro.
- [aurora/db.py](aurora/db.py) — `cancelar_reserva` filtra por `apartamento = ?`; `data_livre` responde só livre/ocupada, sem dono nem código.

**3. Nada se perde no reinício**
- [aurora/api.py](aurora/api.py) — `SqliteSessionService(var/sessoes.db)` persiste sessões e eventos; pendências de confirmação são lidas desses eventos, então também sobrevivem.
- [aurora/db.py](aurora/db.py) — reservas e visitantes em `var/condominio.db`. Reservas canceladas ficam com `status = 'cancelada'` e `codigo` é `PRIMARY KEY`, então um código nunca se repete.

**4. O regulamento é consultado, não carregado**
- [aurora/regulamento.py](aurora/regulamento.py) — `buscar` devolve apenas o capítulo mais relevante para o assunto.
- [aurora/agents.py](aurora/agents.py) — `especialista_regulamento` é usado via `AgentTool` (sessão interna em memória); a instrução de `assistente_aurora` não contém o regulamento.

**5. Dois moradores, uma reserva**
- [aurora/db.py](aurora/db.py) — índice único parcial `ux_reserva_ativa ON reservas(area, data) WHERE status = 'ativa'`. Em `criar_reserva`, o próprio `INSERT` decide: se outra reserva entrou antes, o SQLite levanta `IntegrityError` e a tool devolve `"recusada"` (resposta normal, `200`).

## Como rodar

Pré-requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/) e uma chave do Google AI Studio.

```bash
cp .env.example .env   # preencha GOOGLE_API_KEY
uv sync
```

Variáveis do `.env`:

| Variável | Descrição |
|---|---|
| `GOOGLE_API_KEY` | Chave do Google AI Studio |
| `GOOGLE_GENAI_USE_VERTEXAI` | `FALSE` |
| `MODELO` | Opcional. Modelo Gemini dos agentes (padrão `gemini-flash-latest`) |

Restaurar os dados iniciais (reservas e visitantes de `dados/` e apaga as sessões):

```bash
uv run python -m aurora.restaurar
```

Subir a API em `http://localhost:8000`:

```bash
uv run python -m aurora.api
```

Não há serviços externos: tudo fica em arquivos SQLite em `var/`.
