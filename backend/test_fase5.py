"""Testes da Fase 5 (segurança e privacidade), de ponta a ponta na API.

Rodar na pasta do backend, com o python do .venv do RVC (tem numpy e soundfile):
    python test_fase5.py

Usa banco, chave e pastas TEMPORÁRIOS: não mexe nos seus dados nem nos seus modelos.
Não precisa de internet nem do RVC: o gTTS e a conversão são trocados por versões falsas.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# --- ambiente isolado (antes de importar o backend) ---
TMP = Path(tempfile.mkdtemp(prefix="teste_fase5_"))
os.environ["APPVOICE_DB"] = str(TMP / "data" / "teste.db")
os.environ.pop("APPVOICE_MODEL_KEY", None)
os.environ.pop("APPVOICE_SECRET", None)

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

import cripto  # noqa: E402
import db  # noqa: E402
import privacidade  # noqa: E402
import voice_registry  # noqa: E402
import watermark  # noqa: E402

voice_registry.BASE_DIR = (TMP / "voice_models").resolve()
privacidade.PASTA_AMOSTRAS = (TMP / "amostras").resolve()

sys.modules["rvc_service"] = None  # não carrega o RVC de verdade (lento); a conversão é falsa
import main  # noqa: E402

SR = 40000


class GttsFalso:
    def __init__(self, text, **_):
        self.text = text

    def save(self, caminho):
        Path(caminho).write_bytes(b"ID3" + b"\0" * 100)


def conversao_falsa(entrada, saida, pth, index):
    assert Path(pth).read_bytes() == b"PESOS-DO-MODELO", "o RVC deveria receber o modelo já aberto"
    assert Path(pth).parent.name.startswith("appvoice_")
    t = np.arange(SR) / SR
    sf.write(saida, 0.3 * np.sin(2 * np.pi * 200 * t), SR, subtype="PCM_16")


main.gTTS = GttsFalso
main.convert_voice = conversao_falsa


# --- cliente ASGI mínimo (não precisa de httpx) ---
def chamar(metodo, caminho, corpo=None, token=None, bruto=None, tipo="application/json"):
    if "?" in caminho:
        caminho, query = caminho.split("?", 1)
    else:
        query = ""
    dados = bruto if bruto is not None else (json.dumps(corpo).encode() if corpo is not None else b"")
    cab = [(b"content-type", tipo.encode()), (b"content-length", str(len(dados)).encode())]
    if token:
        cab.append((b"authorization", f"Bearer {token}".encode()))
    escopo = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": metodo,
              "scheme": "http", "path": caminho, "raw_path": caminho.encode(), "query_string": query.encode(),
              "headers": cab, "client": ("127.0.0.1", 1234), "server": ("teste", 80), "root_path": ""}
    resposta = {"corpo": b"", "cab": {}}

    async def rodar():
        enviado = False
        terminou = asyncio.Event()

        async def receive():
            nonlocal enviado
            if not enviado:
                enviado = True
                return {"type": "http.request", "body": dados, "more_body": False}
            await terminou.wait()  # o "cliente" só desconecta depois de receber a resposta inteira
            return {"type": "http.disconnect"}

        async def send(msg):
            if msg["type"] == "http.response.start":
                resposta["status"] = msg["status"]
                resposta["cab"] = {k.decode().lower(): v.decode() for k, v in msg.get("headers", [])}
            elif msg["type"] == "http.response.body":
                resposta["corpo"] += msg.get("body", b"")
                if not msg.get("more_body", False):
                    terminou.set()

        await main.app(escopo, receive, send)

    asyncio.run(rodar())
    try:
        resposta["json"] = json.loads(resposta["corpo"])
    except (ValueError, UnicodeDecodeError):
        resposta["json"] = None
    return resposta


def ok(cond, msg):
    if not cond:
        raise SystemExit(f"FALHOU: {msg}")
    print(f"  ok - {msg}")


def conta(email, papel):
    r = chamar("POST", "/auth/cadastro", {"email": email, "senha": "senha-forte-123", "papel": papel})
    assert r["status"] == 201, r
    r = chamar("POST", "/auth/login", {"email": email, "senha": "senha-forte-123"})
    return r["json"]["token"], r["json"]["usuario"]["id"]


def wav_bytes(segundos=1.0):
    caminho = TMP / "amostra.wav"
    t = np.arange(int(16000 * segundos)) / 16000
    sf.write(caminho, 0.2 * np.sin(2 * np.pi * 150 * t), 16000, subtype="PCM_16")
    return caminho.read_bytes()


def consentir(token, amostras, relacao="propria", paciente_id=None, senha="senha-forte-123", aceites=None):
    texto = chamar("GET", "/consentimento/texto")["json"]
    return chamar("POST", "/consentimento", {
        "versao": texto["versao"], "senha": senha, "nome_completo": "Pessoa de Teste",
        "relacao": relacao, "paciente_id": paciente_id, "aceite_identidade": True,
        "aceites_uso": aceites if aceites is not None else [True] * len(texto["camada_uso"]),
        "amostras": amostras,
    }, token)


try:
    print("1) autenticação e vínculo token <-> voz")
    ana_t, ana = conta("ana@teste.com", "paciente")
    bia_t, bia = conta("bia@teste.com", "cuidador")
    eve_t, eve = conta("eve@teste.com", "paciente")
    ok(chamar("POST", "/gerar-audio", {"texto": "oi"})["status"] == 401, "sem token: 401")
    ok(chamar("POST", "/gerar-audio", {"texto": "oi"}, "token.falso")["status"] == 401, "token falso: 401")

    print("2) amostras criptografadas")
    r = chamar("POST", "/amostras", bruto=b"isto nao e audio", tipo="audio/wav", token=ana_t)
    ok(r["status"] == 415, "arquivo que não é áudio é recusado")
    audio = wav_bytes()
    r = chamar("POST", "/amostras", bruto=audio, tipo="audio/wav", token=ana_t)
    ok(r["status"] == 201 and r["json"]["formato"] == "wav", "upload de WAV aceito")
    amostra = r["json"]["id"]
    no_disco = (privacidade.PASTA_AMOSTRAS / f"{amostra}.enc").read_bytes()
    ok(no_disco.startswith(cripto.MAGICO) and audio not in no_disco, "amostra gravada cifrada (sem o áudio puro)")
    ok(cripto.decifrar(no_disco, f"amostra:{amostra}") == audio, "amostra decifra de volta igual")
    ok(chamar("GET", "/amostras", token=eve_t)["json"] == [], "outra pessoa não vê as amostras da Ana")
    ok(chamar("DELETE", f"/amostras/{amostra}", token=eve_t)["status"] == 404, "outra pessoa não apaga amostra")

    print("3) consentimento em duas camadas")
    ok(consentir(ana_t, [amostra], senha="errada")["status"] == 403, "camada 1: senha errada recusa")
    ok(consentir(ana_t, [amostra], aceites=[True, False, True, True])["status"] == 400,
       "camada 2: precisa aceitar todos os usos")
    ok(consentir(eve_t, [amostra])["status"] == 404, "não dá para autorizar amostra de outra pessoa")
    ok(consentir(bia_t, [amostra], "responsavel_legal", ana)["status"] == 403,
       "cuidador sem vínculo ativo não assina pelo paciente")
    try:
        voice_registry.criar_voz(ana, __file__)
        ok(False, "criou voz sem consentimento")
    except voice_registry.SemConsentimento:
        ok(True, "sem consentimento não se cadastra voz")
    r = consentir(ana_t, [amostra])
    ok(r["status"] == 201 and r["json"]["amostras_autorizadas"] == 1, "consentimento próprio registrado")
    c = db.consentimento_valido(ana)
    ok(c["sha256_amostras"] == [db.listar_amostras(ana)[0]["sha256"]], "hash do áudio autorizado gravado")

    print("4) modelo .pth criptografado e isolado")
    pth = TMP / "modelo.pth"
    pth.write_bytes(b"PESOS-DO-MODELO")
    vid = voice_registry.criar_voz(ana, str(pth))
    pasta = voice_registry.BASE_DIR / vid
    ok(not (pasta / "model.pth").exists() and (pasta / "model.pth.enc").exists(), "só existe o .enc em disco")
    ok(b"PESOS-DO-MODELO" not in (pasta / "model.pth.enc").read_bytes(), "conteúdo do .enc está cifrado")
    vid2 = str(__import__("uuid").uuid4())
    (voice_registry.BASE_DIR / vid2).mkdir()
    shutil.copy(pasta / "model.pth.enc", voice_registry.BASE_DIR / vid2 / "model.pth.enc")
    try:
        with voice_registry.voz_aberta(vid2):
            pass
        ok(False, ".enc copiado para outra voz abriu")
    except Exception:
        ok(True, ".enc copiado para a pasta de outra voz não abre (AAD)")
    with voice_registry.voz_aberta(vid) as (aberto, _):
        pasta_aberta = Path(aberto).parent
    ok(not pasta_aberta.exists(), "a cópia aberta do modelo é apagada depois do uso")

    print("5) geração com voz clonada + marca d'água + auditoria")
    r = chamar("POST", "/gerar-audio", {"texto": "Estou com sede"}, ana_t)
    ok(r["status"] == 200 and r["cab"].get("x-voz") == "clonada", "Ana fala com a voz clonada")
    saida = TMP / "saida.wav"
    saida.write_bytes(r["corpo"])
    registro = watermark.detectar_arquivo(str(saida))
    ok(registro is not None, f"áudio gerado tem marca d'água (registro #{registro})")
    reg = db.registro_auditoria(registro)
    ok(reg["usuario_id"] == ana and reg["voice_id"] == vid, "a marca aponta para o registro certo da auditoria")
    with db.conexao() as con:
        textos = [tuple(l) for l in con.execute("SELECT * FROM auditoria").fetchall()]
    ok(not any("sede" in str(l) for l in textos), "o texto da frase não vai para a auditoria")
    r = chamar("POST", "/gerar-audio", {"texto": "oi", "voice_id": vid}, eve_t)
    ok(r["status"] == 404, "outra pessoa não usa a voz da Ana pelo voice_id")
    r = chamar("POST", "/gerar-audio", {"texto": "oi", "paciente_id": ana}, bia_t)
    ok(r["status"] == 403, "cuidador sem vínculo não usa a voz da Ana")

    print("6) vínculo cuidador <-> paciente")
    r = chamar("POST", "/vinculos", {"paciente_email": "naoexiste@teste.com"}, bia_t)
    r2 = chamar("POST", "/vinculos", {"paciente_email": "ana@teste.com"}, bia_t)
    ok(r["json"] == r2["json"], "resposta igual exista ou não a conta (não revela usuários)")
    ok(chamar("POST", "/vinculos", {"paciente_email": "ana@teste.com"}, eve_t)["status"] == 403,
       "paciente não pede vínculo")
    corpo = {"cuidador_id": bia, "paciente_id": ana, "status": "ativo"}
    ok(chamar("POST", "/vinculos/status", corpo, bia_t)["status"] == 403, "cuidador não aprova o próprio pedido")
    ok(chamar("POST", "/vinculos/status", corpo, ana_t)["status"] == 200, "paciente aprova")
    r = chamar("POST", "/gerar-audio", {"texto": "oi", "paciente_id": ana}, bia_t)
    ok(r["cab"].get("x-voz") == "clonada", "cuidador com vínculo ativo fala com a voz da paciente")
    log = chamar("GET", "/auditoria", token=ana_t)["json"]
    ok(any(l["quem"] == "bia@teste.com" and l["acao"] == "gerar_audio" for l in log),
       "a paciente vê na auditoria que a cuidadora usou a voz dela")

    print("7) revogação")
    ok(chamar("DELETE", "/consentimento", token=ana_t)["status"] == 200, "Ana revoga o consentimento")
    r = chamar("POST", "/gerar-audio", {"texto": "oi"}, ana_t)
    ok(r["cab"].get("x-voz") == "generica-sem-consentimento", "após revogar, a voz clonada não é mais usada")
    consentir(ana_t, [amostra])
    r = chamar("DELETE", "/consentimento?apagar_dados=true", token=ana_t)
    ok(r["json"]["arquivos_apagados"] == 2, "revogar com exclusão apaga amostra e modelo")
    ok(not pasta.exists() and not (privacidade.PASTA_AMOSTRAS / f"{amostra}.enc").exists(),
       "arquivos sumiram do disco")
    ok(db.listar_vozes(ana) == [], "voz removida do banco")

    print("\ntodos os testes da Fase 5 passaram")
finally:
    shutil.rmtree(TMP, ignore_errors=True)