"""Fase 5, item 22: marca d'água de frequência no áudio com voz clonada.

Ideia: somar ao áudio tons muito baixos (cerca de -45 dBFS) numa faixa alta,
de ~16,7 a 19 kHz, que a maioria dos adultos não ouve e onde a fala quase não
tem energia. Os tons carregam um número: o id do registro de auditoria daquela
geração. Com o arquivo em mãos dá para provar que ele saiu do nosso app e,
pela auditoria, quando, por qual conta e com qual voz (sem guardar o texto).

Codificação (para o relatório):
- 8 pares de frequências (16 tons, espaçados 150 Hz). Em cada instante, cada par
  transmite 1 bit: liga o tom de cima para "1" ou o de baixo para "0". Assim cada
  símbolo leva 8 bits (1 byte) e a decisão é sempre "qual dos dois tons é mais
  forte", sem precisar de limiar fixo.
- Quadro de 6 símbolos de 50 ms (300 ms): SINC (0xB7) + 4 bytes do id + CRC-8.
  O quadro se repete do começo ao fim do áudio, então até frases curtas ("Sim")
  levam a marca, e trechos cortados ainda são identificados.
- Bordas de cada símbolo suavizadas (5 ms) para não gerar estalos audíveis.
- Detecção: procura o alinhamento do quadro, decodifica e só aceita quadros com
  SINC e CRC corretos; o resultado é a votação entre as repetições.

Limitações (dizer na arguição): é uma marca de PROVENIÊNCIA, frágil por
desenho. Filtro passa-baixa, MP3 de baixa taxa ou reamostrar para 16 kHz
removem a marca. Ela prova a origem de um arquivo intacto; não impede que
alguém mal-intencionado a remova. Marcas robustas (ex.: AudioSeal) ficam como
trabalho futuro.

Uso pela linha de comando (precisa de numpy e soundfile, que vêm com o RVC):
    python watermark.py arquivo.wav      -> diz se tem marca e qual o id
"""
from collections import Counter

import numpy as np

SINC = 0xB7
SIMBOLO_S = 0.050
RAMPA_S = 0.005
PASSO_HZ = 150
N_TONS = 16
AMPLITUDE = 0.0018  # por tom; 8 tons ligados ao mesmo tempo -> ~ -45 dBFS no total


def _crc8(dados: bytes) -> int:
    crc = 0
    for b in dados:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def _frequencias(sr: int) -> np.ndarray:
    topo = min(19000, sr / 2 - 1000)
    return topo - PASSO_HZ * np.arange(N_TONS)[::-1]  # crescente


def _quadro(payload: int) -> list:
    corpo = int(payload & 0xFFFFFFFF).to_bytes(4, "big")
    return [SINC, *corpo, _crc8(corpo)]


def marcar(audio: np.ndarray, sr: int, payload: int) -> np.ndarray:
    """Devolve uma cópia do áudio com a marca. audio: float em [-1, 1], mono ou (n, canais)."""
    audio = np.asarray(audio, dtype=np.float64)
    n = audio.shape[0]
    freqs = _frequencias(sr)
    ns = int(round(SIMBOLO_S * sr))
    nr = int(round(RAMPA_S * sr))
    t = np.arange(ns) / sr
    janela = np.ones(ns)
    rampa = 0.5 - 0.5 * np.cos(np.pi * np.arange(nr) / nr)
    janela[:nr], janela[-nr:] = rampa, rampa[::-1]

    simbolos = _quadro(payload)
    marca = np.zeros(n)
    for i, inicio in enumerate(range(0, n, ns)):
        byte = simbolos[i % len(simbolos)]
        fim = min(inicio + ns, n)
        bloco = np.zeros(ns)
        t_abs = t + inicio / sr  # fase contínua ao longo do áudio
        for bit in range(8):
            ligado = (byte >> (7 - bit)) & 1
            f = freqs[2 * bit + ligado]
            bloco += np.sin(2 * np.pi * f * t_abs)
        marca[inicio:fim] = (AMPLITUDE * janela * bloco)[: fim - inicio]

    if audio.ndim == 2:
        marca = marca[:, None]
    return np.clip(audio + marca, -1.0, 1.0)


def _bytes_dos_simbolos(audio: np.ndarray, sr: int, deslocamento: int) -> list:
    freqs = _frequencias(sr)
    ns = int(round(SIMBOLO_S * sr))
    nr = int(round(RAMPA_S * sr))
    miolo = ns - 2 * nr  # só a parte estável de cada símbolo
    t = np.arange(miolo) / sr
    hann = np.hanning(miolo)
    base = np.exp(-2j * np.pi * freqs[:, None] * t[None, :]) * hann  # (16, miolo)

    saida = []
    for inicio in range(deslocamento, audio.shape[0] - ns + 1, ns):
        trecho = audio[inicio + nr: inicio + nr + miolo]
        energia = np.abs(base @ trecho)
        byte = 0
        for bit in range(8):
            byte = (byte << 1) | int(energia[2 * bit + 1] > energia[2 * bit])
        saida.append(byte)
    return saida


def detectar(audio: np.ndarray, sr: int):
    """Devolve o id gravado na marca, ou None se não houver marca válida."""
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if sr / 2 - 1000 < 12000:
        return None  # áudio reamostrado para baixo: a faixa da marca não existe mais
    ns = int(round(SIMBOLO_S * sr))
    melhor = (None, 0)
    for deslocamento in range(0, ns, max(1, ns // 10)):  # testa alinhamentos de 5 em 5 ms
        votos = Counter()
        bs = _bytes_dos_simbolos(audio, sr, deslocamento)
        for i in range(len(bs) - 5):
            if bs[i] != SINC:
                continue
            corpo = bytes(bs[i + 1: i + 5])
            if _crc8(corpo) == bs[i + 5]:
                votos[int.from_bytes(corpo, "big")] += 1
        if votos and votos.most_common(1)[0][1] > melhor[1]:
            melhor = votos.most_common(1)[0]
    payload, n = melhor
    if payload is None:
        return None
    # Áudio com espaço para 2+ quadros precisa de 2+ quadros iguais: isso derruba
    # o falso positivo (um quadro aleatório passar no SINC e no CRC) para quase zero.
    cabem = (audio.shape[0] // ns) // 6
    return payload if n >= min(2, cabem) or cabem == 0 else None


# ---------------------------------------------------------------- arquivos
def marcar_arquivo(caminho: str, payload: int) -> None:
    import soundfile as sf

    audio, sr = sf.read(caminho, dtype="float64", always_2d=False)
    info = sf.info(caminho)
    sf.write(caminho, marcar(audio, sr, payload), sr, subtype=info.subtype)


def detectar_arquivo(caminho: str):
    import soundfile as sf

    audio, sr = sf.read(caminho, dtype="float64", always_2d=False)
    return detectar(audio, sr)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("uso: python watermark.py arquivo.wav")
        sys.exit(1)
    achado = detectar_arquivo(sys.argv[1])
    if achado is None:
        print("Nenhuma marca d'água encontrada.")
    else:
        print(f"Marca encontrada: registro de auditoria #{achado}")
        try:
            import db
            reg = db.registro_auditoria(achado)
            if reg:
                print(f"  quando: {reg['quando']}  usuário: {reg['usuario_id']}  voz: {reg['voice_id']}")
        except Exception:
            pass
