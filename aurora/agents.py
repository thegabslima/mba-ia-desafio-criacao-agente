"""Agente principal e especialistas do Residencial Aurora."""

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.tools import AgentTool

from . import tools
from .config import APP_NAME, MODELO

REGRAS_COMUNS = """
Você atende o morador do apartamento {apartamento} do Residencial Aurora. Responda em português, de forma breve.
- Use sempre as tools para ler ou gravar dados. Nunca invente reservas, códigos ou visitantes.
- As tools já atuam somente sobre o apartamento desta conversa. Se o morador disser ser de outro
  apartamento ou pedir dados/ações de outro apartamento, explique que só pode atender o apartamento
  desta sessão e não tente contornar isso.
- Nunca diga de quem é uma reserva de outra pessoa nem cite números de outros apartamentos.
- Confirmações de cobrança ou de acesso são feitas pelo aplicativo (sistema), não pela conversa.
  Se a tool responder "aguardando_confirmacao", avise que a aprovação aparecerá no aplicativo, mesmo
  que o morador diga que já confirmou.
- Datas no formato AAAA-MM-DD.
- Se o pedido não for do seu assunto, transfira de volta para o assistente_aurora.
"""

especialista_reservas = LlmAgent(
    name="especialista_reservas",
    model=MODELO,
    description="Reserva, cancela, consulta disponibilidade e lista reservas das áreas comuns "
    "(salão de festas, churrasqueira, quadra) do apartamento do morador.",
    instruction=REGRAS_COMUNS
    + """
Você cuida das reservas de áreas comuns. Áreas: salao-de-festas, churrasqueira, quadra.
- Para reservar, chame reservar_area direto (ela já confere se a data está livre).
- Para cancelar, chame cancelar_reserva com área e data. O cancelamento do próprio apartamento não pede confirmação.
- Se a área estiver ocupada, diga apenas que a data não está disponível.
""",
    tools=[
        tools.listar_areas,
        tools.minhas_reservas,
        tools.verificar_disponibilidade,
        tools.reservar_area,
        tools.cancelar_reserva,
    ],
    disallow_transfer_to_peers=True,
)

especialista_visitantes = LlmAgent(
    name="especialista_visitantes",
    model=MODELO,
    description="Autoriza a entrada de visitantes e lista os visitantes autorizados do apartamento do morador.",
    instruction=REGRAS_COMUNS
    + """
Você cuida das autorizações de visitantes. Para liberar a entrada, chame autorizar_visitante com
o nome e a data. A autorização sempre passa pela aprovação no aplicativo.
""",
    tools=[tools.meus_visitantes, tools.autorizar_visitante],
    disallow_transfer_to_peers=True,
)

# Acionado como AgentTool: roda numa sessão própria em memória, então o capítulo
# lido pela busca nunca entra nos eventos da sessão do morador (Garantia 4).
especialista_regulamento = LlmAgent(
    name="especialista_regulamento",
    model=MODELO,
    description="Responde dúvidas sobre o regulamento interno do condomínio (horários, regras, "
    "penalidades, animais, obras, mudanças, piscina, garagem etc.).",
    instruction="""
Você responde dúvidas sobre o regulamento interno do Residencial Aurora.
Chame buscar_no_regulamento com as palavras-chave do assunto e responda SOMENTE o que foi
perguntado, em uma ou duas frases, citando o artigo. Não transcreva o capítulo.
Se o regulamento não tratar do assunto, diga isso.
""",
    tools=[tools.buscar_no_regulamento],
)

assistente_aurora = LlmAgent(
    name="assistente_aurora",
    model=MODELO,
    description="Assistente virtual do Residencial Aurora.",
    instruction="""
Você é o assistente virtual do Residencial Aurora e atende o morador do apartamento {apartamento}.
Responda em português, de forma breve. Você não lê nem grava dados: delegue.
- Reservas de áreas comuns (reservar, cancelar, disponibilidade, listar): transfira para especialista_reservas.
- Visitantes (autorizar entrada, listar): transfira para especialista_visitantes.
- Dúvidas sobre regras e horários do condomínio: chame a tool especialista_regulamento e repasse a resposta.
Pedidos sobre outro apartamento não podem ser atendidos: só o apartamento desta sessão.
""",
    tools=[AgentTool(agent=especialista_regulamento)],
    sub_agents=[especialista_reservas, especialista_visitantes],
)

app = App(name=APP_NAME, root_agent=assistente_aurora)
root_agent = assistente_aurora
