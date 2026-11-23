import logging
import os
import tempfile
import threading
import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from gtts import gTTS
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

import armazenamento
import db
import tts
from auth import router as rota_auth, usuario_atual
from conta import router as rota_conta
from privacidade import dono_permitido, router as rota_privacidade
from voice_registry import VoiceNotFound, voz_aberta

# Item 7 (conversão RVC): quando o rvc_service.py existir nesta pasta, ele é usado sozinho.
# Num computador sem o RVC instalado, o rvc_service.py falha ao abrir a pasta do RVC:
# nesse caso o servidor sobe mesmo assim, só sem a voz clonada.
try:
    from rvc_service import convert_voice
except (ImportError, OSError) as erro:
    if not isinstance(erro, ImportError):
        logging.getLogger("appvoice").warning("RVC indisponível neste computador: %s", erro)
    convert_voice = None

# Fase 5, item 22: marca d'água (precisa de numpy + soundfile, que vêm com o RVC).
try:
    import watermark
except ImportError:
    watermark = None

log = logging.getLogger("appvoice")
db.iniciar_banco()
# Fase 6: se o servidor caiu no meio de uma conversão, o modelo aberto e os áudios
# temporários ficaram na pasta temporária. Apaga essas sobras antes de atender.
_sobras = armazenamento.limpar_temporarios()
if _sobras:
    log.warning("apagadas %d sobras de conversões interrompidas", _sobras)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Voz", "X-Voz-Base"],
)
app.include_router(rota_auth)
app.include_router(rota_privacidade)
app.include_router(rota_conta)

# Uma conversão por vez: o modelo descriptografado fica numa pasta temporária
# de nome fixo, e o RVC também só converte uma frase por vez.
_lock_conversao = threading.Lock()
PASTA_TMP = tempfile.gettempdir()  # áudios temporários fora da pasta do projeto


class DadosDoAudio(BaseModel):
    texto: str = Field(max_length=db.MAX_TEXTO)
    voice_id: str | None = None      # opcional: uma das vozes do próprio usuário
    paciente_id: int | None = None   # opcional: cuidador falando com a voz de um paciente vinculado
    generica: bool = False           # Fase 6: força a voz genérica (ex.: botão "Ouvir" da voz genérica)
    historico: bool = False          # Fase 6: guarda a frase nas "Recentes" de quem pediu
    base: str | None = None          # "feminina" | "masculina": qual voz genérica (ex.: "Ouvir")


def _apagar(*caminhos: str) -> None:
    for c in caminhos:
        try:
            os.remove(c)
        except FileNotFoundError:
            pass


def _tmp(extensao: str) -> str:
    # nome único por requisição, para um usuário nunca receber o áudio de outro
    return os.path.join(PASTA_TMP, f"appvoice_{uuid.uuid4().hex}.{extensao}")


@app.get("/")
def teste_inicial():
    return {"status": "A API está viva e rodando!"}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/vozes")
def vozes(usuario: dict = Depends(usuario_atual)):
    """Só as vozes do próprio usuário."""
    return db.listar_vozes(usuario["id"])


@app.post("/gerar-audio")
def gerar_audio(dados: DadosDoAudio, usuario: dict = Depends(usuario_atual)):
    # Quem pede vem do token, nunca do corpo da requisição.
    if not dados.texto.strip():
        raise HTTPException(status_code=400, detail="O texto não pode estar vazio.")

    # De quem é a voz: do próprio usuário ou de um paciente com vínculo ativo.
    dono_id = dono_permitido(usuario, dados.paciente_id, "gerar_audio")

    # Qual voz: a genérica (se pedida), a pedida (se for do dono) ou a ativa do dono.
    if dados.generica:
        voice_id = None
    elif dados.voice_id:
        if not db.voz_pertence_ao_usuario(dono_id, dados.voice_id):
            db.auditar("gerar_audio", usuario["id"], resultado="negado")
            raise HTTPException(status_code=404, detail="Voz não encontrada.")
        voice_id = dados.voice_id
    else:
        voice_id = db.voz_ativa(dono_id)

    # Qual voz genérica: a pedida, a base da voz clonada (entrada do RVC) ou a escolhida na conta.
    if dados.base is not None and dados.base not in db.VOZES_GENERICAS:
        raise HTTPException(status_code=400, detail="Voz genérica inválida.")
    if voice_id is None:
        base = dados.base or db.voz_generica(dono_id)
    else:
        base = db.voz_base(voice_id)
    base_usada = base

    def responder(arquivo: str, tipo: str, voz: str, *apagar: str, auditar: bool = True) -> FileResponse:
        if auditar:
            db.auditar("gerar_audio", usuario["id"], voice_id, voz)  # só metadados, nunca o texto
        return FileResponse(
            arquivo,
            media_type=tipo,
            headers={"X-Voz": voz, "X-Voz-Base": base_usada},
            background=BackgroundTask(_apagar, *apagar),
        )

    arquivo_base = _tmp("mp3")
    try:
        # gTTS (feminina) ou edge-tts (masculina); se a masculina falhar, sai a feminina
        base_usada = tts.sintetizar(dados.texto, base, arquivo_base, gTTS)
    except Exception:
        log.exception("voz genérica falhou")
        _apagar(arquivo_base)
        db.auditar("gerar_audio", usuario["id"], voice_id, "erro")
        raise HTTPException(status_code=502, detail="Falha ao gerar o áudio. Tente de novo.")

    # Fase 6: "Recentes" de quem pediu (o app manda historico=true só no modo Digitar).
    # O texto fica só nesta tabela, que o usuário pode limpar; nunca na auditoria.
    if dados.historico:
        db.registrar_frase(usuario["id"], dados.texto)

    # 1) sem voz clonada: devolve a voz genérica (fallback)
    if voice_id is None:
        return responder(arquivo_base, "audio/mpeg", "generica", arquivo_base)

    # 2) Fase 5: sem consentimento válido (nunca dado ou revogado), a voz clonada não é usada
    if not db.tem_consentimento(dono_id):
        return responder(arquivo_base, "audio/mpeg", "generica-sem-consentimento", arquivo_base)

    # 3) conversão RVC ainda não integrada: voz genérica e aviso pelo header
    if convert_voice is None:
        return responder(arquivo_base, "audio/mpeg", "generica-rvc-pendente", arquivo_base)

    # 4) conversão real: o modelo só fica aberto (descriptografado) durante a conversão
    arquivo_clonado = _tmp("wav")
    try:
        with _lock_conversao, voz_aberta(voice_id) as (pth_path, index_path):
            convert_voice(arquivo_base, arquivo_clonado, pth_path, index_path)
    except VoiceNotFound:
        _apagar(arquivo_base, arquivo_clonado)
        db.auditar("gerar_audio", usuario["id"], voice_id, "erro")
        raise HTTPException(status_code=404, detail="Voz não encontrada.")
    except Exception:
        log.exception("conversão RVC falhou")
        _apagar(arquivo_base, arquivo_clonado)
        db.auditar("gerar_audio", usuario["id"], voice_id, "erro")
        raise HTTPException(status_code=500, detail="Falha na conversão de voz. Tente de novo.")

    # 5) marca d'água com o id do registro de auditoria desta geração.
    #    Falhou a marca? Não entrega a voz clonada sem marca: cai na genérica.
    registro = db.auditar("gerar_audio", usuario["id"], voice_id, "clonada")
    try:
        if watermark is None:
            raise RuntimeError("módulo watermark indisponível (numpy/soundfile)")
        watermark.marcar_arquivo(arquivo_clonado, registro)
    except Exception:
        log.exception("marca d'água falhou")
        db.definir_resultado_auditoria(registro, "erro_marca")
        _apagar(arquivo_clonado)
        return responder(arquivo_base, "audio/mpeg", "generica", arquivo_base)

    return responder(arquivo_clonado, "audio/wav", "clonada", arquivo_base, arquivo_clonado, auditar=False)
