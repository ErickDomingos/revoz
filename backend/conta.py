"""Fase 6: rotas dos dados de cada usuário.

- Voz ativa guardada no servidor (antes ficava só no navegador)
- Frases prontas por categoria (modo Olhar e Digitar), por usuário
- Botão de emergência (fica registrado na atividade da conta)
- Histórico de frases recentes (o usuário pode limpar)
- Baixar meus dados e excluir minha conta (direitos do titular, LGPD art. 18)

Regra geral (a mesma da Fase 5): QUEM pede vem sempre do token.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import armazenamento
import db
import tts
from auth import confirmar_senha, usuario_atual

# Frases iniciais de quem ainda não personalizou as suas.
CATEGORIAS_PADRAO = [
    {"nome": "Respostas", "frases": ["Sim", "Não", "Talvez", "Não sei", "Obrigado"]},
    {"nome": "Necessidades", "frases": ["Estou com sede", "Estou com fome", "Quero ir ao banheiro",
                                        "Quero mudar de posição", "Quero dormir"]},
    {"nome": "Saúde", "frases": ["Estou com dor", "Estou com frio", "Estou com calor",
                                 "Estou com falta de ar", "Chame a enfermagem"]},
    {"nome": "Sentimentos", "frases": ["Estou bem", "Estou triste", "Estou com medo", "Eu te amo"]},
    {"nome": "Conversa", "frases": ["Bom dia", "Boa noite", "Pode repetir?", "Espere um pouco",
                                    "Quero conversar"]},
]
FRASES_PADRAO = [f for c in CATEGORIAS_PADRAO for f in c["frases"]]

router = APIRouter(tags=["conta"])


def _ip(req: Request) -> str:
    return req.client.host if req.client else "?"


# ------------------------------------------------------------- voz ativa
class VozAtiva(BaseModel):
    voice_id: str | None = None  # None = voz genérica (nenhuma voz clonada ativa)
    generica: str | None = None  # com voice_id None: "feminina" ou "masculina"


NOMES_GENERICAS = {"feminina": "Voz genérica feminina", "masculina": "Voz genérica masculina"}


@router.get("/vozes/generica")
def vozes_genericas(usuario: dict = Depends(usuario_atual)):
    """As vozes genéricas e qual delas a conta usa quando não há voz clonada ativa."""
    return {
        "escolhida": db.voz_generica(usuario["id"]),
        "opcoes": [
            {"id": "feminina", "nome": NOMES_GENERICAS["feminina"], "disponivel": True},
            # sem edge-tts no servidor, a masculina sai com a voz feminina do gTTS
            {"id": "masculina", "nome": NOMES_GENERICAS["masculina"], "disponivel": tts.edge_disponivel()},
        ],
    }


@router.put("/vozes/ativa")
def definir_voz_ativa(dados: VozAtiva, usuario: dict = Depends(usuario_atual)):
    if dados.voice_id is None:
        if dados.generica is not None:
            if dados.generica not in db.VOZES_GENERICAS:
                raise HTTPException(400, "Voz genérica inválida.")
            db.definir_voz_generica(usuario["id"], dados.generica)
        db.desativar_vozes(usuario["id"])
    elif not db.definir_voz_ativa(usuario["id"], dados.voice_id):  # confere a posse
        raise HTTPException(404, "Voz não encontrada.")
    db.auditar("definir_voz_ativa", usuario["id"], dados.voice_id, dados.generica or "ok")
    return {"ok": True, "voice_id": dados.voice_id, "generica": db.voz_generica(usuario["id"])}


# ----------------------------------------------------------------- frases
class Categoria(BaseModel):
    nome: str = ""
    frases: list[str] = []


class Frases(BaseModel):
    frases: list[str] | None = None            # formato antigo: lista simples
    categorias: list[Categoria] | None = None  # formato novo: frases agrupadas


def _resposta_frases(uid: int) -> dict:
    categorias = db.listar_categorias(uid) or CATEGORIAS_PADRAO
    return {"frases": [f for c in categorias for f in c["frases"]], "categorias": categorias}


@router.get("/frases")
def obter_frases(usuario: dict = Depends(usuario_atual)):
    return _resposta_frases(usuario["id"])


def _validar_categorias(categorias: list[Categoria]) -> list[dict]:
    limpas = []
    for c in categorias:
        frases = [f.strip() for f in c.frases if f and f.strip()]
        nome = c.nome.strip()
        if not frases and not nome:
            continue  # categoria em branco: ignora
        if not nome:
            raise HTTPException(400, "Dê um nome para cada categoria.")
        if len(nome) > db.MAX_NOME_CATEGORIA:
            raise HTTPException(400, f"O nome da categoria pode ter até {db.MAX_NOME_CATEGORIA} caracteres.")
        if not 1 <= len(frases) <= db.MAX_POR_CATEGORIA:
            raise HTTPException(400, f'A categoria "{nome}" precisa ter de 1 a {db.MAX_POR_CATEGORIA} frases.')
        if any(len(f) > db.MAX_TEXTO for f in frases):
            raise HTTPException(400, f"Cada frase pode ter até {db.MAX_TEXTO} caracteres.")
        limpas.append({"nome": nome, "frases": frases})
    if not 1 <= len(limpas) <= db.MAX_CATEGORIAS:
        raise HTTPException(400, f"Use de 1 a {db.MAX_CATEGORIAS} categorias.")
    if len({c["nome"].lower() for c in limpas}) != len(limpas):
        raise HTTPException(400, "Há duas categorias com o mesmo nome.")
    return limpas


@router.put("/frases")
def salvar_frases(dados: Frases, usuario: dict = Depends(usuario_atual)):
    # Validação feita aqui, e não no Field: o pydantic 1 (o do ambiente do RVC)
    # ignora min_length/max_length em listas sem avisar.
    if dados.categorias is not None:
        db.definir_categorias(usuario["id"], _validar_categorias(dados.categorias))
    else:
        limpas = [f.strip() for f in (dados.frases or []) if f and f.strip()]
        if not 1 <= len(limpas) <= db.MAX_FRASES:
            raise HTTPException(400, f"Use de 1 a {db.MAX_FRASES} frases.")
        if any(len(f) > db.MAX_TEXTO for f in limpas):
            raise HTTPException(400, f"Cada frase pode ter até {db.MAX_TEXTO} caracteres.")
        db.definir_frases(usuario["id"], limpas)
    db.auditar("salvar_frases", usuario["id"])  # só metadados: o texto não vai para a auditoria
    return _resposta_frases(usuario["id"])


# --------------------------------------------------------------- emergência
@router.post("/emergencia", status_code=201)
def emergencia(usuario: dict = Depends(usuario_atual)):
    """O alarme toca no aparelho (funciona até sem servidor). Aqui só fica o registro."""
    db.auditar("emergencia", usuario["id"])
    return {"ok": True}


# --------------------------------------------------------------- histórico
@router.get("/historico")
def recentes(n: int = Query(10, ge=1, le=db.LIMITE_HISTORICO), usuario: dict = Depends(usuario_atual)):
    return {"frases": db.listar_recentes(usuario["id"], n)}


class FraseRecente(BaseModel):
    texto: str = Field(max_length=db.MAX_TEXTO)


@router.post("/historico", status_code=201)
def guardar_recente(dados: FraseRecente, usuario: dict = Depends(usuario_atual)):
    """Para frases que o app tocou do cache, sem chamar /gerar-audio de novo."""
    db.registrar_frase(usuario["id"], dados.texto)
    return {"ok": True}


@router.delete("/historico")
def limpar_recentes(usuario: dict = Depends(usuario_atual)):
    db.limpar_historico(usuario["id"])
    db.auditar("limpar_historico", usuario["id"])
    return {"ok": True}


# ------------------------------------------------------ direitos do titular
@router.get("/conta/dados")
def baixar_meus_dados(usuario: dict = Depends(usuario_atual)):
    """Exporta em JSON tudo o que o banco guarda sobre a pessoa."""
    db.auditar("exportar_dados", usuario["id"])
    return JSONResponse(
        db.exportar_dados(usuario["id"]),
        headers={"Content-Disposition": 'attachment; filename="meus-dados-appvoice.json"'},
    )


class ExcluirConta(BaseModel):
    senha: str = Field(max_length=128)


@router.post("/conta/excluir")
def excluir_conta(dados: ExcluirConta, req: Request, usuario: dict = Depends(usuario_atual)):
    """Apaga a conta, os áudios e os modelos. Pede a senha de novo: não dá para desfazer."""
    confirmar_senha(usuario, dados.senha, _ip(req))  # 403 se errar, 429 se insistir
    arquivos = armazenamento.apagar_arquivos_do_usuario(usuario["id"])
    db.apagar_usuario(usuario["id"])
    # a auditoria fica com o número do usuário (sem e-mail): a marca d'água dos áudios
    # já gerados aponta para registros dela, então ela continua provando a origem
    db.auditar("excluir_conta", usuario["id"])
    return {"ok": True, "apagados": arquivos}
