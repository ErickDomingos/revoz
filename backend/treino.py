"""Ponte entre o app e o treino do modelo de voz (Fase 3), feito fora do servidor.

Os áudios enviados no app ficam criptografados. Para treinar, quem tem a GPU
precisa deles abertos. Este script abre SÓ os áudios que a pessoa autorizou
no consentimento (confere o SHA-256 de cada um) e registra a exportação na
auditoria.

Fluxo completo:
  1. A pessoa envia os áudios e assina o consentimento no app (aba Consentimento).
  2. No servidor:        python treino.py exportar <email> <pasta>
  3. A pasta vai para a máquina com GPU por um meio privado (pendrive, ou zip
     com senha). Nunca pelo git nem por link público.
  4. Na máquina com GPU: aba "Treinar" do RVC, apontando para essa pasta.
  5. De volta ao servidor, com o .pth e o .index gerados:
         python voice_registry.py <email> modelo.pth modelo.index --base masculina --nome "Minha voz"
  6. Apaguem as cópias abertas, aqui e na máquina com GPU:
         python treino.py apagar <pasta>

Rodar na pasta do backend, com o python do .venv do RVC (precisa do cryptography).
"""
import shutil
import sys
from pathlib import Path

import cripto
import db
import privacidade

AVISO = """ÁUDIOS ABERTOS PARA TREINO - DADO BIOMÉTRICO

Estes arquivos são a voz de uma pessoa, autorizada só para treinar o modelo
dela dentro do app (consentimento versão {versao}).
- Não compartilhem por link público nem coloquem no git.
- Apaguem esta pasta assim que o treino terminar (python treino.py apagar <pasta>).
"""


class SemConsentimento(Exception):
    pass


def exportar(email: str, destino: str) -> dict:
    """Descriptografa as amostras autorizadas do usuário para `destino` (pasta nova)."""
    usuario = db.usuario_por_email(email)
    if usuario is None:
        raise LookupError("usuário não encontrado")
    consentimento = db.consentimento_valido(usuario["id"])
    if consentimento is None:
        raise SemConsentimento("não há consentimento válido para esta voz")

    autorizados = set(consentimento["sha256_amostras"])
    amostras = [a for a in db.listar_amostras(usuario["id"]) if a["sha256"] in autorizados]
    if not amostras:
        raise LookupError("nenhum áudio autorizado ainda guardado (foram apagados?)")

    pasta = Path(destino)
    if pasta.exists() and any(pasta.iterdir()):
        raise FileExistsError("a pasta de destino precisa estar vazia ou não existir")
    pasta.mkdir(parents=True, exist_ok=True)

    duracao = 0.0
    for i, a in enumerate(amostras, 1):
        dados = cripto.ler_cifrado(privacidade.PASTA_AMOSTRAS / f"{a['id']}.enc", f"amostra:{a['id']}")
        (pasta / f"{i:02d}_{a['id'][:8]}.{a['formato']}").write_bytes(dados)
        duracao += a["duracao_s"] or 0
    (pasta / "LEIA-ME.txt").write_text(AVISO.format(versao=consentimento["versao_texto"]), encoding="utf-8")

    db.auditar("exportar_para_treino", usuario["id"], resultado=f"{len(amostras)}_arquivos")
    return {"arquivos": len(amostras), "duracao_wav_s": round(duracao, 1), "pasta": str(pasta.resolve())}


def apagar(pasta: str) -> None:
    alvo = Path(pasta)
    if not (alvo / "LEIA-ME.txt").is_file():
        raise ValueError("isto não parece uma pasta criada pelo 'treino.py exportar'")
    shutil.rmtree(alvo)


if __name__ == "__main__":
    db.iniciar_banco()
    if len(sys.argv) == 4 and sys.argv[1] == "exportar":
        try:
            r = exportar(sys.argv[2], sys.argv[3])
        except (LookupError, SemConsentimento, FileExistsError) as erro:
            print(f"Não exportado: {erro}.")
            sys.exit(1)
        print(f"{r['arquivos']} áudio(s) exportado(s) para {r['pasta']}")
        if r["duracao_wav_s"]:
            print(f"duração dos WAV: {r['duracao_wav_s'] / 60:.1f} min (o RVC recomenda pelo menos 10 min)")
        print("Apaguem a pasta depois do treino: python treino.py apagar <pasta>")
    elif len(sys.argv) == 3 and sys.argv[1] == "apagar":
        apagar(sys.argv[2])
        print("pasta apagada")
    else:
        print("uso: python treino.py exportar <email> <pasta>")
        print("     python treino.py apagar <pasta>")
        sys.exit(1)
