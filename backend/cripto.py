"""Fase 5, item 20: criptografia dos arquivos sensíveis em disco.

O que é criptografado: modelos de voz (model.pth, model.index) e os áudios de
referência enviados pelo usuário. Todos são dados biométricos (LGPD, art. 5º, II).

Decisões (para o relatório):
- AES-256-GCM (biblioteca cryptography). O GCM também AUTENTICA o arquivo:
  se alguém alterar um byte, a leitura falha em vez de entregar lixo.
- Cada arquivo é "amarrado" ao seu id pelo associated data (AAD). Copiar o
  model.pth.enc da voz A para a pasta da voz B não funciona: a descriptografia
  falha porque o id não confere.
- A chave é diferente do segredo do JWT. Vem da variável APPVOICE_MODEL_KEY
  (base64, 32 bytes) ou é gerada uma vez em data/model.key (fora do git).
  Em produção a chave fica só na variável de ambiente do servidor.
- O modelo só existe aberto (descriptografado) durante a conversão, numa
  pasta temporária que é apagada logo depois (ver arquivo_aberto()).

Formato do arquivo: b"AVZ1" + nonce (12 bytes) + texto cifrado + tag (16 bytes).
"""
import base64
import os
import secrets
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGICO = b"AVZ1"
_PASTA_DADOS = Path(os.environ.get("APPVOICE_DB", Path(__file__).parent / "data" / "appvoice.db")).parent


def _carregar_chave() -> bytes:
    texto = os.environ.get("APPVOICE_MODEL_KEY")
    if not texto:
        arquivo = _PASTA_DADOS / "model.key"
        if not arquivo.exists():
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(), encoding="utf-8")
        texto = arquivo.read_text(encoding="utf-8").strip()
    chave = base64.urlsafe_b64decode(texto)
    if len(chave) != 32:
        raise RuntimeError("APPVOICE_MODEL_KEY precisa ter 32 bytes em base64.")
    return chave


_aes = AESGCM(_carregar_chave())


def cifrar(dados: bytes, contexto: str) -> bytes:
    nonce = secrets.token_bytes(12)  # nunca repete: sorteado a cada gravação
    return MAGICO + nonce + _aes.encrypt(nonce, dados, contexto.encode())


def decifrar(blob: bytes, contexto: str) -> bytes:
    """Levanta cryptography.exceptions.InvalidTag se o arquivo foi alterado ou é de outro id."""
    if not blob.startswith(MAGICO):
        raise ValueError("arquivo não está no formato criptografado")
    return _aes.decrypt(blob[4:16], blob[16:], contexto.encode())


def gravar_cifrado(destino: Path, dados: bytes, contexto: str) -> None:
    destino = Path(destino)
    tmp = destino.with_suffix(destino.suffix + ".parcial")
    tmp.write_bytes(cifrar(dados, contexto))
    os.replace(tmp, destino)  # nunca fica um arquivo pela metade com o nome final


def ler_cifrado(origem: Path, contexto: str) -> bytes:
    return decifrar(Path(origem).read_bytes(), contexto)


@contextmanager
def arquivos_abertos(arquivos: dict, nome_pasta: str | None = None):
    """Descriptografa arquivos para uma pasta temporária privada e apaga tudo ao sair.

    arquivos: {"nome_no_tmp": (caminho_cifrado, contexto)}
    nome_pasta: nome fixo da pasta (opcional). Com nome fixo o caminho do modelo
    se repete entre requisições e o rvc_service não recarrega o modelo à toa.
    Quem usa nome fixo precisa garantir que não há duas aberturas ao mesmo tempo.
    Devolve {"nome_no_tmp": caminho_do_arquivo_aberto}.
    """
    if nome_pasta:
        pasta = Path(tempfile.gettempdir()) / nome_pasta
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(mode=0o700)
    else:
        pasta = Path(tempfile.mkdtemp(prefix="appvoice_"))  # criada com permissão só do dono
    try:
        abertos = {}
        for nome, (origem, contexto) in arquivos.items():
            caminho = pasta / nome
            caminho.write_bytes(ler_cifrado(origem, contexto))
            abertos[nome] = str(caminho)
        yield abertos
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
