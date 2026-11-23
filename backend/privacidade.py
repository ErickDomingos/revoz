"""Fase 5: rotas de privacidade e segurança.

- Vínculo cuidador <-> paciente (pedido, aprovação, revogação)
- Amostras de áudio (upload criptografado, listagem, exclusão)
- Consentimento em duas camadas (registro, consulta, revogação)
- Apagar uma voz
- Auditoria: o usuário vê o que foi feito com a conta e com as vozes dele

Regra geral: QUEM pede vem sempre do token. Quando um cuidador age em nome de
um paciente, ele manda paciente_id e o servidor confere se há vínculo ATIVO.

Consentimento em duas camadas (para o relatório):
  Camada 1 - identidade de quem autoriza: a pessoa confirma a SENHA de novo,
             informa o nome completo e diz se é a própria dona da voz ou o
             responsável legal (neste caso precisa ser cuidador com vínculo
             ativo aprovado pelo paciente).
  Camada 2 - autorização de uso do áudio: marca, item por item, para que os
             áudios podem ser usados. O servidor grava a versão do texto aceito
             e o SHA-256 de cada áudio autorizado, então fica provado exatamente
             quais arquivos foram autorizados, mesmo depois que eles forem apagados.
  Sem consentimento válido: não se cadastra voz e a geração cai na voz genérica.
  Revogar: a voz clonada para de ser usada na hora; opcionalmente apaga tudo.
"""
import hashlib
import io
import wave
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

import cripto
import db
import voice_registry
from auth import confirmar_senha, usuario_atual

PASTA_AMOSTRAS = (Path(__file__).parent / "amostras").resolve()
MAX_AMOSTRA_BYTES = 25 * 1024 * 1024  # 25 MB por arquivo

VERSAO_CONSENTIMENTO = "2026-11-v1"
TEXTO_CONSENTIMENTO = {
    "versao": VERSAO_CONSENTIMENTO,
    "camada_identidade": (
        "Declaro que sou a pessoa dona da voz contida nestes áudios, ou o seu "
        "responsável legal, e que as informações de identificação acima são verdadeiras."
    ),
    "camada_uso": [
        "Autorizo o uso destes áudios somente para treinar um modelo da minha voz "
        "(ou da voz da pessoa que represento) dentro deste aplicativo.",
        "Autorizo que o modelo seja usado somente para falar as frases que a dona da "
        "voz, ou cuidadores aprovados por ela, pedirem no aplicativo.",
        "Estou ciente de que todo áudio gerado com a voz clonada leva uma marca d'água "
        "e que cada uso fica registrado (sem o texto da frase).",
        "Estou ciente de que posso revogar este consentimento a qualquer momento, "
        "e pedir a exclusão dos áudios e do modelo.",
    ],
}

# Formatos aceitos, conferidos pelos primeiros bytes (não confiamos só no Content-Type).
_ASSINATURAS = {
    "wav": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WAVE",
    "mp3": lambda b: b[:3] == b"ID3" or (len(b) > 1 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0),
    "ogg": lambda b: b[:4] == b"OggS",
    "flac": lambda b: b[:4] == b"fLaC",
    "webm": lambda b: b[:4] == b"\x1a\x45\xdf\xa3",
    "m4a": lambda b: b[4:8] == b"ftyp",
}

router = APIRouter(tags=["privacidade"])


# ---------------------------------------------------------------- helpers
def dono_permitido(usuario: dict, paciente_id: int | None, acao: str) -> int:
    """Devolve de quem são os dados: do próprio usuário ou de um paciente vinculado (403 se não puder)."""
    if paciente_id is None or paciente_id == usuario["id"]:
        return usuario["id"]
    if not db.cuidador_pode_acessar(usuario["id"], paciente_id):
        db.auditar(acao, usuario["id"], resultado="negado")
        raise HTTPException(403, "Sem permissão para acessar os dados deste usuário.")
    return paciente_id


def _ip(req: Request) -> str:
    return req.client.host if req.client else "?"


def _arquivo_amostra(amostra_id: str) -> Path:
    return PASTA_AMOSTRAS / f"{amostra_id}.enc"


def _apagar_amostra(amostra_id: str) -> None:
    _arquivo_amostra(amostra_id).unlink(missing_ok=True)
    db.marcar_amostra_apagada(amostra_id)


def _duracao_wav(dados: bytes):
    try:
        with wave.open(io.BytesIO(dados)) as w:
            return round(w.getnframes() / float(w.getframerate()), 2)
    except (wave.Error, EOFError, ZeroDivisionError):
        return None


# ---------------------------------------------------------------- vínculos
class PedidoVinculo(BaseModel):
    paciente_email: str = Field(max_length=254)


class MudancaVinculo(BaseModel):
    cuidador_id: int
    paciente_id: int
    status: str  # 'ativo' ou 'revogado'


@router.post("/vinculos", status_code=202)
def pedir_vinculo(dados: PedidoVinculo, usuario: dict = Depends(usuario_atual)):
    if usuario["papel"] != "cuidador":
        raise HTTPException(403, "Só contas de responsável podem pedir vínculo.")
    paciente = db.usuario_por_email(dados.paciente_email)
    if paciente and paciente["papel"] == "paciente" and paciente["id"] != usuario["id"]:
        db.vincular(usuario["id"], paciente["id"])
        db.auditar("pedir_vinculo", usuario["id"])
    # Mesma resposta exista ou não a conta: não revela quem usa o app.
    return {"mensagem": "Se houver uma conta de usuário com esse e-mail, o pedido foi enviado para aprovação."}


@router.get("/vinculos")
def meus_vinculos(usuario: dict = Depends(usuario_atual)):
    return db.listar_vinculos(usuario["id"])


@router.post("/vinculos/status")
def mudar_vinculo(dados: MudancaVinculo, usuario: dict = Depends(usuario_atual)):
    atual = db.status_vinculo(dados.cuidador_id, dados.paciente_id)
    if atual is None or usuario["id"] not in (dados.cuidador_id, dados.paciente_id):
        raise HTTPException(404, "Vínculo não encontrado.")
    if dados.status == "ativo":
        # só o PACIENTE aprova, e só um pedido pendente
        if usuario["id"] != dados.paciente_id or atual != "pendente":
            raise HTTPException(403, "Só o usuário dono da voz pode aprovar um pedido pendente.")
    elif dados.status != "revogado":
        raise HTTPException(400, "Status inválido.")
    db.definir_status_vinculo(dados.cuidador_id, dados.paciente_id, dados.status)
    db.auditar(f"vinculo_{dados.status}", usuario["id"])
    return {"ok": True}


# ---------------------------------------------------------------- amostras
@router.post("/amostras", status_code=201)
async def enviar_amostra(req: Request, paciente_id: int | None = Query(None),
                         usuario: dict = Depends(usuario_atual)):
    """Corpo da requisição = o arquivo de áudio puro (Content-Type: audio/...)."""
    dono_id = dono_permitido(usuario, paciente_id, "enviar_amostra")
    if not req.headers.get("content-type", "").startswith("audio/"):
        raise HTTPException(415, "Envie um arquivo de áudio.")

    partes, total = [], 0
    async for pedaco in req.stream():
        total += len(pedaco)
        if total > MAX_AMOSTRA_BYTES:
            raise HTTPException(413, "Arquivo grande demais (máximo 25 MB).")
        partes.append(pedaco)
    dados = b"".join(partes)

    formato = next((f for f, confere in _ASSINATURAS.items() if confere(dados[:16])), None)
    if formato is None:
        raise HTTPException(415, "Formato não reconhecido. Use WAV, MP3, OGG, FLAC, WEBM ou M4A.")

    sha = hashlib.sha256(dados).hexdigest()
    amostra_id = db.registrar_amostra(dono_id, sha, _duracao_wav(dados) if formato == "wav" else None, formato)
    try:
        PASTA_AMOSTRAS.mkdir(parents=True, exist_ok=True)
        cripto.gravar_cifrado(_arquivo_amostra(amostra_id), dados, f"amostra:{amostra_id}")
    except Exception:
        db.marcar_amostra_apagada(amostra_id)
        raise
    db.auditar("enviar_amostra", usuario["id"])
    return {"id": amostra_id, "formato": formato, "sha256": sha}


@router.get("/amostras")
def listar_amostras(paciente_id: int | None = Query(None), usuario: dict = Depends(usuario_atual)):
    dono_id = dono_permitido(usuario, paciente_id, "listar_amostras")
    return [{k: a[k] for k in ("id", "formato", "duracao_s", "criado_em", "sha256")}
            for a in db.listar_amostras(dono_id)]


@router.delete("/amostras/{amostra_id}")
def apagar_amostra(amostra_id: str, paciente_id: int | None = Query(None),
                   usuario: dict = Depends(usuario_atual)):
    dono_id = dono_permitido(usuario, paciente_id, "apagar_amostra")
    if db.amostra_do_usuario(dono_id, amostra_id) is None:
        raise HTTPException(404, "Amostra não encontrada.")
    _apagar_amostra(amostra_id)
    db.auditar("apagar_amostra", usuario["id"])
    return {"ok": True}


# ---------------------------------------------------------- consentimento
class Consentimento(BaseModel):
    versao: str
    senha: str = Field(max_length=128)                      # camada 1
    nome_completo: str = Field(min_length=3, max_length=120)  # camada 1
    relacao: str                                            # camada 1: 'propria' | 'responsavel_legal'
    paciente_id: int | None = None                          # obrigatório se responsavel_legal
    aceite_identidade: bool                                 # camada 1
    aceites_uso: list[bool]                                 # camada 2: um por item de TEXTO_CONSENTIMENTO
    amostras: list[str] = Field(min_length=1, max_length=50)  # camada 2: quais áudios


@router.get("/consentimento/texto")
def texto_consentimento():
    return TEXTO_CONSENTIMENTO


@router.get("/consentimento")
def ver_consentimento(paciente_id: int | None = Query(None), usuario: dict = Depends(usuario_atual)):
    dono_id = dono_permitido(usuario, paciente_id, "ver_consentimento")
    c = db.consentimento_valido(dono_id)
    if c is None:
        return {"valido": False}
    return {"valido": True, "versao": c["versao_texto"], "relacao": c["relacao"],
            "nome_declarante": c["nome_declarante"], "criado_em": c["criado_em"],
            "amostras_autorizadas": len(c["sha256_amostras"])}


@router.post("/consentimento", status_code=201)
def registrar_consentimento(dados: Consentimento, req: Request, usuario: dict = Depends(usuario_atual)):
    # Camada 1: é mesmo o dono da conta? (senha de novo)
    confirmar_senha(usuario, dados.senha, _ip(req))

    if dados.versao != VERSAO_CONSENTIMENTO:
        raise HTTPException(409, "O texto do consentimento mudou. Recarregue e leia de novo.")
    if not dados.aceite_identidade:
        raise HTTPException(400, "É preciso confirmar a declaração de identidade.")
    if len(dados.aceites_uso) != len(TEXTO_CONSENTIMENTO["camada_uso"]) or not all(dados.aceites_uso):
        raise HTTPException(400, "É preciso aceitar todos os itens de uso do áudio.")
    # Conferido aqui porque o pydantic 1 (ambiente do RVC) ignora min_length/max_length
    # em listas: sem isto, dava para registrar um consentimento sem nenhum áudio.
    if not 1 <= len(dados.amostras) <= 50:
        raise HTTPException(400, "Escolha de 1 a 50 áudios para autorizar.")

    # Camada 1: em nome de quem?
    if dados.relacao == "propria":
        if dados.paciente_id not in (None, usuario["id"]):
            raise HTTPException(400, "Para outra pessoa, use a opção responsável legal.")
        dono_id = usuario["id"]
    elif dados.relacao == "responsavel_legal":
        if usuario["papel"] != "cuidador" or dados.paciente_id is None:
            raise HTTPException(400, "Para assinar como responsável legal, use uma conta de responsável e indique o usuário.")
        dono_id = dono_permitido(usuario, dados.paciente_id, "consentimento")
    else:
        raise HTTPException(400, "Relação inválida.")

    # Camada 2: quais áudios, exatamente (só do dono e ainda guardados)
    amostras = [db.amostra_do_usuario(dono_id, a) for a in dict.fromkeys(dados.amostras)]
    if any(a is None for a in amostras):
        raise HTTPException(404, "Alguma amostra não foi encontrada.")

    cid = db.registrar_consentimento(
        dono_id, usuario["id"], dados.relacao, VERSAO_CONSENTIMENTO,
        [a["sha256"] for a in amostras], nome_declarante=dados.nome_completo.strip(),
    )
    db.auditar("consentimento", usuario["id"])
    return {"id": cid, "amostras_autorizadas": len(amostras)}


@router.delete("/consentimento")
def revogar_consentimento(paciente_id: int | None = Query(None), apagar_dados: bool = Query(False),
                          usuario: dict = Depends(usuario_atual)):
    dono_id = dono_permitido(usuario, paciente_id, "revogar_consentimento")
    revogados = db.revogar_consentimento(dono_id)
    apagados = 0
    if apagar_dados:
        for a in db.listar_amostras(dono_id):
            _apagar_amostra(a["id"])
            apagados += 1
        for v in db.listar_vozes(dono_id):
            voice_registry.apagar_arquivos(v["id"])
            db.apagar_voz(dono_id, v["id"])
            apagados += 1
    db.auditar("revogar_consentimento", usuario["id"], resultado="apagou_dados" if apagar_dados else "ok")
    return {"revogados": revogados, "arquivos_apagados": apagados}


# ------------------------------------------------------------------ vozes
@router.delete("/vozes/{voice_id}")
def apagar_voz(voice_id: str, usuario: dict = Depends(usuario_atual)):
    """Só o dono apaga a própria voz (registro + arquivos criptografados)."""
    if not db.voz_pertence_ao_usuario(usuario["id"], voice_id):
        raise HTTPException(404, "Voz não encontrada.")
    db.auditar("apagar_voz", usuario["id"], voice_id)
    voice_registry.apagar_arquivos(voice_id)
    db.apagar_voz(usuario["id"], voice_id)
    return {"ok": True}


# -------------------------------------------------------------- auditoria
@router.get("/auditoria")
def minha_auditoria(usuario: dict = Depends(usuario_atual)):
    return db.listar_auditoria(usuario["id"])
