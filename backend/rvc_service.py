"""
rvc_service.py - etapa 2 do pipeline: voz genérica (gTTS) -> voz clonada (RVC).

Cumpre o contrato do main.py do backend:
    convert_voice(input_audio_path, output_audio_path, pth_path, index_path)

ONDE COLOCAR: na pasta do backend, ao lado do main.py (o nome PRECISA ser
rvc_service.py, o main.py detecta o arquivo sozinho).

COMO RODAR: com o python do .venv do RVC, a partir da pasta do backend:
    C:\\...\\Retrieval-based-Voice-Conversion-WebUI\\.venv\\Scripts\\python.exe -m uvicorn main:app --port 8080
(sem --reload: ele recarregaria o RVC a cada alteração de arquivo).
Antes, no .venv do RVC:  python -m pip install gTTS   (sem --upgrade)

O objeto VC, o modelo e o Hubert ficam carregados em memória entre as
requisições. O modelo só é recarregado quando a requisição pede outro .pth
(ou quando o arquivo do .pth muda).
"""

import os
import sys
import threading

import soundfile as sf

# ------------------------------------------------------------------
# Configuração - editem aqui
# ------------------------------------------------------------------
# Pasta raiz do RVC (a que tem webui.py, assets/, infer/ e o ffmpeg.exe).
# Pode ser sobrescrita pela variável de ambiente RVC_DIR.
RVC_DIR = os.environ.get(
    "RVC_DIR",
    r"C:\Users\leozi\PycharmProjects\PythonProject\poc-rvc\Retrieval-based-Voice-Conversion-WebUI",
)

TOM = 0  # use o valor que soou melhor no testar_rvc.py (ex.: -12)
INDEX_RATE = 0.75
RMS_MIX_RATE = 0.25
PROTECT = 0.33

# ------------------------------------------------------------------
# Ambiente do RVC
# ------------------------------------------------------------------
# O RVC procura ffmpeg.exe, assets/ etc. a partir da pasta atual, então o
# processo passa a rodar a partir da pasta do RVC. Os arquivos tmp_* do
# main.py são criados e lidos depois disso, então ficam consistentes.
os.chdir(RVC_DIR)
sys.path.insert(0, RVC_DIR)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

os.environ.setdefault("weight_root", "assets/weights")
os.environ.setdefault("index_root", "logs")
os.environ.setdefault("outside_index_root", "assets/indices")
os.environ.setdefault("rmvpe_root", "assets/rmvpe")

from configs.config import Config  # noqa: E402
from infer.vc.modules import VC  # noqa: E402

# O Config do RVC lê o sys.argv com argparse. Quando o uvicorn importa este
# módulo, o sys.argv tem os argumentos do uvicorn (main:app, --port...) e o
# Config reclamaria deles. Então esvaziamos o argv só durante a criação.
_argv_original = sys.argv
sys.argv = sys.argv[:1]
try:
    _vc = VC(Config())
finally:
    sys.argv = _argv_original

# O objeto VC guarda um modelo por vez e não é seguro para duas conversões
# simultâneas. O lock faz as requisições entrarem em fila.
_lock = threading.Lock()
_modelo_carregado = None  # (caminho do .pth, tamanho)


def convert_voice(
    input_audio_path: str,
    output_audio_path: str,
    pth_path: str,
    index_path: str,
) -> None:
    """Converte o áudio de entrada para a voz do modelo e grava um .wav.

    index_path pode ser '' (voz sem .index). Levanta exceção se falhar.
    """
    global _modelo_carregado

    pth_path = os.path.abspath(pth_path)
    # Fase 5: o modelo chega descriptografado numa pasta temporária recriada a
    # cada requisição (a data do arquivo muda sempre). O nome da pasta já muda
    # quando o modelo muda, então a chave usa caminho + tamanho, não a data.
    chave = (pth_path, os.path.getsize(pth_path))

    with _lock:
        if _modelo_carregado != chave:
            # O get_vc() monta o caminho como f"{weight_root}/{nome}". Como o
            # voice_registry já entrega o caminho completo, apontamos o
            # weight_root para a pasta do modelo e passamos só o nome do arquivo.
            os.environ["weight_root"] = os.path.dirname(pth_path)
            _vc.get_vc(os.path.basename(pth_path))
            _modelo_carregado = chave

        # sid=0: id do falante dentro do modelo (modelo de uma voz só)
        info, resultado = _vc.vc_single(
            0,
            os.path.abspath(input_audio_path),
            TOM,
            "rmvpe",
            index_path,
            INDEX_RATE,
            0,
            RMS_MIX_RATE,
            PROTECT,
        )

        tgt_sr, audio = resultado
        if audio is None:
            raise RuntimeError(f"RVC falhou: {info}")

        sf.write(os.path.abspath(output_audio_path), audio, tgt_sr)
