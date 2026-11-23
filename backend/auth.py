"""Fase 5, item 19: autenticação (cadastro, login e token JWT).

Fica na pasta do backend, ao lado do main.py. Usa as funções do db.py.

Decisões (para o relatório):
- Senha: só o HASH (argon2) vai para o banco; a senha em si nunca é gravada.
- Token JWT assinado (HS256) com validade de 8 h. O token carrega a
  token_version do usuário: "sair de todos os dispositivos" sobe a versão e
  todos os tokens antigos deixam de valer.
- Login com mensagem única ("e-mail ou senha incorretos") e tempo parecido
  para e-mail existente e inexistente, para não revelar quem tem conta.
- Bloqueio temporário após 5 falhas seguidas (por IP + e-mail).
- O segredo vem da variável APPVOICE_SECRET; se não existir, é gerado uma vez
  em data/secret.key (a pasta data/ está no .gitignore).
"""
import os
import re
import secrets
import time

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

import db

ALGORITMO = "HS256"
DURACAO_TOKEN_S = 8 * 3600
MAX_TENTATIVAS = 5
BLOQUEIO_S = 300
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _carregar_segredo() -> str:
    segredo = os.environ.get("APPVOICE_SECRET")
    if segredo:
        return segredo
    arquivo = db.DB_PATH.parent / "secret.key"
    if not arquivo.exists():
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return arquivo.read_text(encoding="utf-8").strip()


SEGREDO = _carregar_segredo()
_ph = PasswordHasher()
_HASH_FALSO = _ph.hash("senha-falsa-para-igualar-o-tempo")
_bearer = HTTPBearer(auto_error=False)
_falhas: dict = {}  # "ip|email" -> instantes das falhas recentes


def _bloqueado(chave: str) -> bool:
    agora = time.time()
    recentes = [t for t in _falhas.get(chave, []) if agora - t < BLOQUEIO_S]
    _falhas[chave] = recentes
    return len(recentes) >= MAX_TENTATIVAS


def _publico(usuario: dict) -> dict:
    return {"id": usuario["id"], "nome": usuario.get("nome") or "", "email": usuario["email"], "papel": usuario["papel"]}


def _criar_token(usuario: dict) -> str:
    agora = int(time.time())
    carga = {
        "sub": str(usuario["id"]),
        "tv": usuario["token_version"],
        "iat": agora,
        "exp": agora + DURACAO_TOKEN_S,
    }
    return jwt.encode(carga, SEGREDO, algorithm=ALGORITMO)


def usuario_atual(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    """Dependência: devolve o usuário do token ou responde 401."""
    erro = HTTPException(401, "Faça login para continuar.", headers={"WWW-Authenticate": "Bearer"})
    if cred is None:
        raise erro
    try:
        dados = jwt.decode(cred.credentials, SEGREDO, algorithms=[ALGORITMO])
        usuario = db.usuario_por_id(int(dados["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise erro
    if usuario is None or usuario["token_version"] != dados.get("tv"):
        raise erro
    return usuario


def confirmar_senha(usuario: dict, senha: str, ip: str) -> None:
    """Reautenticação para ações sensíveis (ex.: consentimento). Responde 403/429 se falhar.

    Prova que quem está assinando é o dono da conta, e não alguém que só pegou
    o celular com a sessão aberta.
    """
    chave = f"{ip}|confirmar|{usuario['id']}"
    if _bloqueado(chave):
        db.auditar("confirmar_senha", usuario["id"], resultado="bloqueado")
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.")
    try:
        _ph.verify(usuario["senha_hash"], senha)
    except (VerificationError, InvalidHashError):
        _falhas.setdefault(chave, []).append(time.time())
        db.auditar("confirmar_senha", usuario["id"], resultado="falha")
        raise HTTPException(403, "Senha incorreta.")  # 403, não 401: a sessão continua válida
    _falhas.pop(chave, None)


class Cadastro(BaseModel):
    nome: str = Field("", max_length=200)  # o app pede o nome; vazio só para clientes antigos
    email: str = Field(max_length=254)
    senha: str = Field(min_length=8, max_length=128)
    papel: str = "paciente"


class Nome(BaseModel):
    nome: str = Field(max_length=200)


class Login(BaseModel):
    email: str = Field(max_length=254)
    senha: str = Field(max_length=128)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/cadastro", status_code=201)
def cadastro(dados: Cadastro):
    email = dados.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "E-mail inválido.")
    if dados.papel not in ("paciente", "cuidador"):
        raise HTTPException(400, "Papel inválido.")
    try:
        usuario_id = db.criar_usuario(email, _ph.hash(dados.senha), dados.papel, dados.nome)
    except db.EmailJaCadastrado:
        raise HTTPException(409, "Este e-mail já está cadastrado.")
    db.auditar("cadastro", usuario_id)
    return {"id": usuario_id, "nome": db.limpar_nome(dados.nome), "email": email, "papel": dados.papel}


@router.post("/login")
def login(dados: Login, req: Request):
    email = dados.email.strip().lower()
    chave = f"{req.client.host if req.client else '?'}|{email}"
    if _bloqueado(chave):
        db.auditar("login", resultado="bloqueado")
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.")

    usuario = db.usuario_por_email(email)
    try:
        _ph.verify(usuario["senha_hash"] if usuario else _HASH_FALSO, dados.senha)
        ok = usuario is not None
    except (VerificationError, InvalidHashError):
        ok = False

    if not ok:
        _falhas.setdefault(chave, []).append(time.time())
        db.auditar("login", usuario["id"] if usuario else None, resultado="falha")
        raise HTTPException(401, "E-mail ou senha incorretos.")

    _falhas.pop(chave, None)
    db.auditar("login", usuario["id"])
    return {"token": _criar_token(usuario), "usuario": _publico(usuario)}


@router.get("/eu")
def eu(usuario: dict = Depends(usuario_atual)):
    return _publico(usuario)


@router.put("/nome")
def editar_nome(dados: Nome, usuario: dict = Depends(usuario_atual)):
    nome = db.limpar_nome(dados.nome)
    if len(nome) < 2:
        raise HTTPException(400, "Escreva o seu nome.")
    db.definir_nome(usuario["id"], nome)
    db.auditar("editar_nome", usuario["id"])  # só que mudou; o nome em si não vai para a auditoria
    return {**_publico(usuario), "nome": nome}


@router.post("/sair-todos")
def sair_todos(usuario: dict = Depends(usuario_atual)):
    db.invalidar_tokens(usuario["id"])
    db.auditar("sair_todos", usuario["id"])
    return {"ok": True}