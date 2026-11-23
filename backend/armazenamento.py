"""Fase 6, item 25: armazenamento dos arquivos.

Onde fica cada arquivo (todos fora de qualquer pasta servida pela API):
    amostras/<amostra_id>.enc              áudio de referência, criptografado (privacidade.py)
    voice_models/<voice_id>/model.pth.enc  modelo de voz, criptografado (voice_registry.py)
    voice_models/<voice_id>/model.index.enc
    data/appvoice.db                       banco (só metadados; nunca os arquivos)
    pasta temporária do sistema            áudios gerados e o modelo aberto durante uma conversão

O caminho de um arquivo sai SEMPRE do id (UUID gerado no servidor), nunca de
algo enviado pelo cliente. O banco diz de quem é cada id.

Este módulo junta duas tarefas que antes não tinham dono:
- limpar_temporarios(): se o servidor cair no meio de uma conversão, o modelo
  aberto (descriptografado) e os áudios temporários ficariam esquecidos na pasta
  temporária. Na subida do servidor eles são apagados.
- apagar_arquivos_do_usuario(): apaga do disco todos os áudios e modelos de uma
  pessoa (usado em "excluir minha conta").
"""
import shutil
import tempfile
from pathlib import Path

import db
import privacidade
import voice_registry

PREFIXO_TMP = "appvoice_"  # main.py e cripto.py criam os temporários com este prefixo


def limpar_temporarios(pasta: Path = None) -> int:
    """Apaga sobras de conversões interrompidas. Chamar só na subida do servidor."""
    pasta = Path(pasta or tempfile.gettempdir())
    apagados = 0
    for item in pasta.glob(f"{PREFIXO_TMP}*"):
        try:
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink()
            apagados += 1
        except OSError:
            pass  # arquivo em uso ou sem permissão: tenta na próxima subida
    return apagados


def apagar_arquivos_do_usuario(usuario_id: int) -> dict:
    """Apaga do disco os áudios de referência e os modelos de voz do usuário.

    Apaga só arquivos; os registros no banco saem depois, com db.apagar_usuario().
    """
    amostras = 0
    for a in db.listar_amostras(usuario_id):
        privacidade._apagar_amostra(a["id"])  # apaga o .enc e marca no banco
        amostras += 1
    vozes = 0
    for v in db.listar_vozes(usuario_id):
        voice_registry.apagar_arquivos(v["id"])
        vozes += 1
    return {"amostras": amostras, "vozes": vozes}


def uso_em_disco() -> dict:
    """Quanto as pastas de dados ocupam (para o relatório e para monitorar o servidor)."""
    def tamanho(p: Path) -> int:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0

    return {
        "amostras_bytes": tamanho(privacidade.PASTA_AMOSTRAS),
        "modelos_bytes": tamanho(voice_registry.BASE_DIR),
        "banco_bytes": db.DB_PATH.stat().st_size if db.DB_PATH.exists() else 0,
    }
