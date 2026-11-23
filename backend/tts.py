"""Etapa 1 do pipeline: texto -> voz genérica (feminina ou masculina).

- feminina: gTTS (a mesma de antes). Se o gTTS falhar, tenta a voz feminina do edge-tts.
- masculina: edge-tts, voz pt-BR-AntonioNeural (o gTTS só tem voz feminina em português).
  Se o edge-tts não estiver instalado ou falhar, cai na feminina do gTTS, e a
  resposta avisa qual voz saiu de fato.

As duas precisam de internet: o gTTS usa o Google Tradutor e o edge-tts usa o
serviço de leitura em voz alta do Microsoft Edge. Nenhum dos dois é uma API
oficial com garantia de funcionamento (limitação para o relatório).

A voz genérica também é a ENTRADA do RVC: uma voz clonada masculina soa melhor
quando o RVC converte a genérica masculina (o tom fica parecido e não precisa
de ajuste). Por isso cada voz clonada guarda a sua voz_base (ver db.py).

Instalação (no .venv do RVC, sem --upgrade):  python -m pip install edge-tts
"""
import asyncio
import logging

try:
    import edge_tts
except ImportError:
    edge_tts = None

log = logging.getLogger("appvoice")

VOZES_EDGE = {"feminina": "pt-BR-FranciscaNeural", "masculina": "pt-BR-AntonioNeural"}
TEMPO_MAX_S = 30


def edge_disponivel() -> bool:
    return edge_tts is not None


def _edge(texto: str, base: str, caminho: str) -> None:
    async def gerar():
        await asyncio.wait_for(edge_tts.Communicate(texto, VOZES_EDGE[base]).save(caminho), TEMPO_MAX_S)

    # a rota do FastAPI roda numa thread sem loop de eventos: asyncio.run funciona
    asyncio.run(gerar())


def sintetizar(texto: str, base: str, caminho: str, gtts_cls) -> str:
    """Grava o mp3 em `caminho` e devolve qual voz saiu ("feminina" ou "masculina").

    gtts_cls: a classe gTTS (passada pelo main.py, para os testes poderem trocar por uma falsa).
    Levanta exceção se nenhum motor conseguir gerar.
    """
    if base == "masculina":
        if edge_tts is not None:
            try:
                _edge(texto, "masculina", caminho)
                return "masculina"
            except Exception:
                log.exception("edge-tts falhou; usando a voz feminina do gTTS")
        else:
            log.warning("edge-tts não instalado; usando a voz feminina do gTTS")

    try:
        gtts_cls(text=texto, lang="pt", tld="com.br").save(caminho)
        return "feminina"
    except Exception:
        if edge_tts is None:
            raise
        log.exception("gTTS falhou; tentando a voz feminina do edge-tts")
        _edge(texto, "feminina", caminho)
        return "feminina"
