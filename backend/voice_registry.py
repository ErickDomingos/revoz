"""Item 8 + Fase 5 (item 20): registro de vozes, isolado e criptografado.

Cada voz fica em voice_models/<voice_id>/ com os arquivos CRIPTOGRAFADOS:
    model.pth.enc    model.index.enc (opcional)
O banco guarda quem é o dono. A API nunca aceita caminho vindo do cliente: o
caminho é sempre derivado do voice_id (UUID), e a pasta voice_models/ não é
servida pela API.

Só é possível cadastrar uma voz para um usuário que tenha consentimento válido
(ver db.consentimento_valido). Sem consentimento, não há modelo.
"""
import shutil
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import cripto
import db

BASE_DIR = (Path(__file__).parent / "voice_models").resolve()


class VoiceNotFound(Exception):
    pass


class SemConsentimento(Exception):
    pass


def _contexto(voice_id: str, arquivo: str) -> str:
    # amarra o arquivo cifrado à voz: o .enc de uma voz não abre na pasta de outra
    return f"voz:{voice_id}:{arquivo}"


def _pasta(voice_id: str) -> Path:
    try:
        voice_id = str(uuid.UUID(str(voice_id)))  # rejeita qualquer coisa que não seja UUID
    except (ValueError, AttributeError, TypeError):
        raise VoiceNotFound("voice_id inválido")
    pasta = (BASE_DIR / voice_id).resolve()
    if pasta.parent != BASE_DIR:  # barreira extra contra path traversal
        raise VoiceNotFound("voice_id inválido")
    return pasta


def criar_voz(usuario_id: int, pth_origem: str, index_origem: str | None = None,
              nome: str = "Minha voz", voz_base: str = "feminina") -> str:
    """Criptografa o modelo para voice_models/<voice_id>/ e registra o dono no banco.

    voz_base: voz genérica que o RVC vai converter ("feminina" ou "masculina").
    Use a do mesmo gênero da voz treinada: o tom fica certo sem ajuste.
    """
    if not db.tem_consentimento(usuario_id):
        raise SemConsentimento("o dono da voz não tem consentimento válido registrado")
    pth = Path(pth_origem)
    if not pth.is_file():
        raise FileNotFoundError(f".pth não encontrado: {pth}")
    index = Path(index_origem) if index_origem else None
    if index is not None and not index.is_file():
        raise FileNotFoundError(f".index não encontrado: {index}")

    voice_id = str(uuid.uuid4())
    pasta = BASE_DIR / voice_id
    pasta.mkdir(parents=True)
    try:
        cripto.gravar_cifrado(pasta / "model.pth.enc", pth.read_bytes(), _contexto(voice_id, "model.pth"))
        if index is not None:
            cripto.gravar_cifrado(pasta / "model.index.enc", index.read_bytes(),
                                  _contexto(voice_id, "model.index"))
        db.cadastrar_voz(usuario_id, voice_id, nome=nome, voz_base=voz_base)
    except Exception:
        shutil.rmtree(pasta, ignore_errors=True)  # não deixa modelo órfão sem dono
        raise
    db.auditar("criar_voz", usuario_id, voice_id)
    return voice_id


@contextmanager
def voz_aberta(voice_id: str):
    """Abre (descriptografa) o modelo só enquanto o bloco 'with' durar.

    Uso:  with voz_aberta(vid) as (pth, index): convert_voice(..., pth, index)
    index é '' se a voz não tiver .index. Ao sair, os arquivos abertos são apagados.
    Quem chama deve garantir uma abertura por vez (o main.py usa um lock).
    """
    pasta = _pasta(voice_id)
    pth_enc, index_enc = pasta / "model.pth.enc", pasta / "model.index.enc"
    if not pth_enc.is_file():
        raise VoiceNotFound("modelo não encontrado")

    arquivos = {"model.pth": (pth_enc, _contexto(pasta.name, "model.pth"))}
    if index_enc.is_file():
        arquivos["model.index"] = (index_enc, _contexto(pasta.name, "model.index"))

    # nome de pasta fixo por versão do arquivo: o rvc_service reconhece o mesmo
    # modelo e não recarrega; se o .enc for trocado, o nome muda e ele recarrega.
    versao = pth_enc.stat().st_mtime_ns
    with cripto.arquivos_abertos(arquivos, nome_pasta=f"appvoice_{pasta.name}_{versao}") as abertos:
        yield abertos["model.pth"], abertos.get("model.index", "")


def apagar_arquivos(voice_id: str) -> None:
    shutil.rmtree(_pasta(voice_id), ignore_errors=True)


def criptografar_existentes() -> int:
    """Migração: cifra os model.pth / model.index antigos (em texto puro) e apaga os originais."""
    feitas = 0
    for pasta in BASE_DIR.iterdir() if BASE_DIR.exists() else []:
        if not pasta.is_dir():
            continue
        for nome in ("model.pth", "model.index"):
            aberto = pasta / nome
            if aberto.is_file():
                cripto.gravar_cifrado(pasta / f"{nome}.enc", aberto.read_bytes(), _contexto(pasta.name, nome))
                aberto.unlink()
                feitas += 1
    return feitas


if __name__ == "__main__":
    db.iniciar_banco()
    if len(sys.argv) == 2 and sys.argv[1] == "criptografar":
        print(f"arquivos criptografados: {criptografar_existentes()}")
        sys.exit(0)

    # uso: python voice_registry.py <email> <arquivo.pth> [arquivo.index] [--base masculina] [--nome "Minha voz"]
    import argparse

    p = argparse.ArgumentParser(description="Cadastra (criptografado) um modelo de voz treinado.")
    p.add_argument("email")
    p.add_argument("pth")
    p.add_argument("index", nargs="?")
    p.add_argument("--base", choices=db.VOZES_GENERICAS, default="feminina",
                   help="voz genérica que o RVC converte: use o mesmo gênero da voz treinada")
    p.add_argument("--nome", default="Minha voz", help="nome que aparece na aba Vozes")
    if len(sys.argv) < 3:
        p.print_help()
        print("\n     python voice_registry.py criptografar   (migra modelos antigos)")
        sys.exit(1)
    args = p.parse_args()
    usuario = db.usuario_por_email(args.email)
    if usuario is None:
        print("Usuário não encontrado. Cadastre-se antes (POST /auth/cadastro em /docs).")
        sys.exit(1)
    try:
        vid = criar_voz(usuario["id"], args.pth, args.index, nome=args.nome, voz_base=args.base)
    except SemConsentimento:
        print("Este usuário ainda não registrou o consentimento (aba Consentimento do app).")
        sys.exit(1)
    print(f"voz cadastrada (criptografada): usuario={usuario['email']} voice_id={vid}")
