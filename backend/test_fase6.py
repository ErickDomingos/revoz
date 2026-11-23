"""Testes da Fase 6 (banco de dados e armazenamento), de ponta a ponta na API.

Rodar na pasta do backend, com o python do .venv do RVC (tem numpy e soundfile):
    python test_fase6.py

Mesmo esquema do test_fase5.py: banco, chave e pastas TEMPORÁRIOS, sem internet
e sem o RVC (o gTTS e a conversão são trocados por versões falsas).
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# --- ambiente isolado (antes de importar o backend) ---
TMP = Path(tempfile.mkdtemp(prefix="teste_fase6_"))
os.environ["APPVOICE_DB"] = str(TMP / "data" / "teste.db")
os.environ.pop("APPVOICE_MODEL_KEY", None)
os.environ.pop("APPVOICE_SECRET", None)

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

import armazenamento  # noqa: E402
import db  # noqa: E402
import privacidade  # noqa: E402
import voice_registry  # noqa: E402

voice_registry.BASE_DIR = (TMP / "voice_models").resolve()
privacidade.PASTA_AMOSTRAS = (TMP / "amostras").resolve()

sys.modules["rvc_service"] = None  # não carrega o RVC de verdade
import main  # noqa: E402

SR = 40000
SENHA = "senha-forte-123"


class GttsFalso:
    def __init__(self, text, **_):
        self.text = text

    def save(self, caminho):
        Path(caminho).write_bytes(b"ID3" + b"\0" * 100)


def conversao_falsa(entrada, saida, pth, index):
    t = np.arange(SR) / SR
    sf.write(saida, 0.3 * np.sin(2 * np.pi * 200 * t), SR, subtype="PCM_16")


main.gTTS = GttsFalso
main.convert_voice = conversao_falsa


# --- cliente ASGI mínimo (o mesmo do test_fase5.py) ---
def chamar(metodo, caminho, corpo=None, token=None, bruto=None, tipo="application/json"):
    caminho, _, query = caminho.partition("?")
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
            await terminou.wait()
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


def conta(email, papel="paciente"):
    r = chamar("POST", "/auth/cadastro", {"email": email, "senha": SENHA, "papel": papel})
    assert r["status"] == 201, r
    r = chamar("POST", "/auth/login", {"email": email, "senha": SENHA})
    return r["json"]["token"], r["json"]["usuario"]["id"]


def wav_bytes():
    caminho = TMP / "amostra.wav"
    t = np.arange(16000) / 16000
    sf.write(caminho, 0.2 * np.sin(2 * np.pi * 150 * t), 16000, subtype="PCM_16")
    return caminho.read_bytes()


def consentir(token, amostras, relacao="propria", paciente_id=None):
    texto = chamar("GET", "/consentimento/texto")["json"]
    return chamar("POST", "/consentimento", {
        "versao": texto["versao"], "senha": SENHA, "nome_completo": "Pessoa de Teste",
        "relacao": relacao, "paciente_id": paciente_id, "aceite_identidade": True,
        "aceites_uso": [True] * len(texto["camada_uso"]), "amostras": amostras,
    }, token)


def voz_pronta(token, usuario_id, nome):
    """Amostra + consentimento + modelo (falso) cadastrado: devolve o voice_id."""
    amostra = chamar("POST", "/amostras", bruto=wav_bytes(), tipo="audio/wav", token=token)["json"]["id"]
    if not db.tem_consentimento(usuario_id):
        consentir(token, [amostra])
    pth = TMP / f"{nome}.pth"
    pth.write_bytes(b"PESOS-" + nome.encode())
    return voice_registry.criar_voz(usuario_id, str(pth), nome=nome)


try:
    ana_t, ana = conta("ana@teste.com")
    eve_t, eve = conta("eve@teste.com")

    print("1) consentimento sem áudio é recusado (correção da Fase 5)")
    ok(consentir(ana_t, [])["status"] == 400, "lista de amostras vazia: 400")

    print("2) frases do modo Olhar por usuário")
    r = chamar("GET", "/frases", token=ana_t)
    ok(r["status"] == 200 and "Sim" in r["json"]["frases"], "sem frases salvas, vem a grade padrão")
    ok(chamar("PUT", "/frases", {"frases": []}, ana_t)["status"] == 400, "lista vazia: 400")
    ok(chamar("PUT", "/frases", {"frases": [f"f{i}" for i in range(13)]}, ana_t)["status"] == 400,
       "mais de 12 frases: 400")
    ok(chamar("PUT", "/frases", {"frases": ["x" * 301]}, ana_t)["status"] == 400, "frase longa demais: 400")
    r = chamar("PUT", "/frases", {"frases": [" Água ", "", "Quero dormir"]}, ana_t)
    ok(r["status"] == 200 and r["json"]["frases"] == ["Água", "Quero dormir"], "salva limpando espaços e vazias")
    ok(chamar("GET", "/frases", token=ana_t)["json"]["frases"] == ["Água", "Quero dormir"], "a grade salva volta")
    ok("Água" not in chamar("GET", "/frases", token=eve_t)["json"]["frases"], "outra conta não vê as frases da Ana")
    ok(chamar("GET", "/frases")["status"] == 401, "sem login: 401")

    print("3) frases recentes")
    chamar("POST", "/gerar-audio", {"texto": "Estou com frio", "historico": True}, ana_t)
    chamar("POST", "/gerar-audio", {"texto": "Frase da grade"}, ana_t)  # historico padrão = false
    recentes = chamar("GET", "/historico", token=ana_t)["json"]["frases"]
    ok(recentes == ["Estou com frio"], "só o que veio com historico=true entra nas recentes")
    chamar("POST", "/historico", {"texto": "Tocou do cache"}, ana_t)
    ok(chamar("GET", "/historico", token=ana_t)["json"]["frases"][0] == "Tocou do cache", "POST /historico anota")
    ok(chamar("GET", "/historico", token=eve_t)["json"]["frases"] == [], "outra conta não vê as recentes da Ana")
    with db.conexao() as con:
        linhas = [str(tuple(l)) for l in con.execute("SELECT * FROM auditoria").fetchall()]
    ok(not any("frio" in l or "Água" in l for l in linhas), "texto de frase não vai para a auditoria")
    ok(chamar("DELETE", "/historico", token=ana_t)["status"] == 200
       and chamar("GET", "/historico", token=ana_t)["json"]["frases"] == [], "limpar apaga as recentes")

    print("4) voz em uso guardada na conta")
    v1 = voz_pronta(ana_t, ana, "primeira")
    v2 = voz_pronta(ana_t, ana, "segunda")
    ativa = [v["id"] for v in chamar("GET", "/vozes", token=ana_t)["json"] if v["ativa"]]
    ok(ativa == [v2], "a voz cadastrada por último fica ativa")
    ok(chamar("PUT", "/vozes/ativa", {"voice_id": v1}, ana_t)["status"] == 200, "Ana escolhe a primeira voz")
    ativa = [v["id"] for v in chamar("GET", "/vozes", token=ana_t)["json"] if v["ativa"]]
    ok(ativa == [v1], "só uma voz ativa, a escolhida")
    ok(chamar("PUT", "/vozes/ativa", {"voice_id": v1}, eve_t)["status"] == 404, "outra conta não ativa a voz da Ana")
    ok(chamar("POST", "/gerar-audio", {"texto": "oi"}, ana_t)["cab"].get("x-voz") == "clonada",
       "com voz ativa, fala com a voz clonada")
    ok(chamar("POST", "/gerar-audio", {"texto": "oi", "generica": True}, ana_t)["cab"].get("x-voz") == "generica",
       "generica=true força a voz genérica")
    chamar("PUT", "/vozes/ativa", {"voice_id": None}, ana_t)
    ok(chamar("POST", "/gerar-audio", {"texto": "oi"}, ana_t)["cab"].get("x-voz") == "generica",
       "sem voz ativa, fala com a voz genérica")

    print("5) baixar meus dados")
    r = chamar("GET", "/conta/dados", token=ana_t)
    d = r["json"]
    ok(r["status"] == 200 and "attachment" in r["cab"].get("content-disposition", ""), "vem como arquivo para baixar")
    ok(d["conta"]["email"] == "ana@teste.com" and len(d["vozes"]) == 2 and d["frases"] == ["Água", "Quero dormir"],
       "tem conta, vozes e frases")
    ok("senha_hash" not in json.dumps(d) and "token_version" not in json.dumps(d), "não exporta hash nem token_version")
    ok(len(d["consentimentos"]) == 1 and len(d["amostras"]) == 2, "tem consentimentos e amostras (só metadados)")

    print("6) excluir minha conta")
    bia_t, bia = conta("bia@teste.com", "cuidador")
    chamar("POST", "/vinculos", {"paciente_email": "eve@teste.com"}, bia_t)
    chamar("POST", "/vinculos/status", {"cuidador_id": bia, "paciente_id": eve, "status": "ativo"}, eve_t)
    a_eve = chamar("POST", "/amostras?paciente_id=%d" % eve, bruto=wav_bytes(), tipo="audio/wav",
                   token=bia_t)["json"]["id"]
    ok(consentir(bia_t, [a_eve], "responsavel_legal", eve)["status"] == 201, "cuidadora assina pela paciente")

    pastas_ana = [voice_registry.BASE_DIR / v for v in (v1, v2)]
    amostras_ana = [privacidade.PASTA_AMOSTRAS / f"{a['id']}.enc" for a in db.listar_amostras(ana)]
    ok(all(p.exists() for p in pastas_ana + amostras_ana), "arquivos da Ana existem antes")
    r = chamar("POST", "/conta/excluir", {"senha": "errada"}, ana_t)
    ok(r["status"] == 403 and db.usuario_por_id(ana) is not None, "senha errada não apaga")
    r = chamar("POST", "/conta/excluir", {"senha": SENHA}, ana_t)
    ok(r["status"] == 200 and r["json"]["apagados"] == {"amostras": 2, "vozes": 2}, "conta excluída")
    ok(not any(p.exists() for p in pastas_ana + amostras_ana), "modelos e áudios sumiram do disco")
    ok(db.usuario_por_id(ana) is None and db.listar_vozes(ana) == [], "conta e vozes sumiram do banco")
    ok(chamar("GET", "/frases", token=ana_t)["status"] == 401, "o token antigo deixa de valer")
    ok(chamar("POST", "/auth/login", {"email": "ana@teste.com", "senha": SENHA})["status"] == 401,
       "não dá mais para entrar")
    with db.conexao() as con:
        resto = [dict(l) for l in con.execute("SELECT * FROM auditoria WHERE usuario_id = ?", (ana,))]
    ok(any(l["acao"] == "excluir_conta" for l in resto), "a auditoria guarda que a conta foi excluída")

    ok(chamar("POST", "/conta/excluir", {"senha": SENHA}, bia_t)["status"] == 200, "cuidadora exclui a conta")
    ok(not db.tem_consentimento(eve), "o consentimento que ela assinou como responsável deixa de valer")
    ok(db.listar_amostras(eve) != [], "os áudios da paciente continuam (são da paciente)")

    print("7) limpeza de temporários na subida")
    pasta_tmp = TMP / "tmp_sistema"
    (pasta_tmp / "appvoice_modelo_aberto").mkdir(parents=True)
    (pasta_tmp / "appvoice_modelo_aberto" / "model.pth").write_bytes(b"x")
    (pasta_tmp / "appvoice_abc.wav").write_bytes(b"x")
    (pasta_tmp / "outro_programa.txt").write_bytes(b"x")
    ok(armazenamento.limpar_temporarios(pasta_tmp) == 2, "apaga as duas sobras do app")
    ok([p.name for p in pasta_tmp.iterdir()] == ["outro_programa.txt"], "não mexe em arquivos de outros programas")

    print("8) vozes genéricas feminina e masculina")

    class EdgeFalso:  # no lugar do edge-tts (sem internet)
        class Communicate:
            def __init__(self, texto, voz):
                self.voz = voz

            async def save(self, caminho):
                Path(caminho).write_bytes(b"ID3" + self.voz.encode())

    main.tts.edge_tts = EdgeFalso
    leo_t, leo = conta("leo@teste.com")
    r = chamar("GET", "/vozes/generica", token=leo_t)["json"]
    ok(r["escolhida"] == "feminina" and r["opcoes"][1]["id"] == "masculina", "conta nova começa com a feminina")
    ok(chamar("PUT", "/vozes/ativa", {"voice_id": None, "generica": "robo"}, leo_t)["status"] == 400,
       "voz genérica inválida: 400")
    chamar("PUT", "/vozes/ativa", {"voice_id": None, "generica": "masculina"}, leo_t)
    r = chamar("POST", "/gerar-audio", {"texto": "oi"}, leo_t)
    ok(r["cab"].get("x-voz") == "generica" and r["cab"].get("x-voz-base") == "masculina",
       "com a masculina escolhida, a fala sai masculina")
    r = chamar("POST", "/gerar-audio", {"texto": "oi", "generica": True, "base": "feminina"}, leo_t)
    ok(r["cab"].get("x-voz-base") == "feminina", "'Ouvir' pode pedir a outra genérica sem trocar a escolha")
    ok(chamar("POST", "/gerar-audio", {"texto": "oi", "base": "robo"}, leo_t)["status"] == 400, "base inválida: 400")
    main.tts.edge_tts = None
    r = chamar("POST", "/gerar-audio", {"texto": "oi"}, leo_t)
    ok(r["status"] == 200 and r["cab"].get("x-voz-base") == "feminina",
       "sem edge-tts no servidor, a masculina cai na feminina e o cabeçalho avisa")
    main.tts.edge_tts = EdgeFalso
    vid_leo = voz_pronta(leo_t, leo, "leo")
    with db.conexao() as con:
        con.execute("UPDATE vozes SET voz_base = 'masculina' WHERE voice_id = ?", (vid_leo,))
    r = chamar("POST", "/gerar-audio", {"texto": "oi"}, leo_t)
    ok(r["cab"].get("x-voz") == "clonada" and r["cab"].get("x-voz-base") == "masculina",
       "a voz clonada usa a voz base dela como entrada do RVC")

    print("9) frases por categoria e emergência")
    r = chamar("GET", "/frases", token=eve_t)["json"]
    ok(r["categorias"][0]["nome"] == "Respostas", "conta nova recebe as categorias padrão")
    cats = [{"nome": "Saúde", "frases": ["Dor", "Frio"]}, {"nome": "Respostas", "frases": ["Sim", "Não"]}]
    r = chamar("PUT", "/frases", {"categorias": cats}, eve_t)
    ok(r["status"] == 200 and r["json"]["categorias"] == cats, "salva as categorias na ordem")
    ok(chamar("PUT", "/frases", {"categorias": [{"nome": "X", "frases": []}]}, eve_t)["status"] == 400,
       "categoria sem frases: 400")
    ok(chamar("POST", "/emergencia")["status"] == 401, "emergência sem login: 401")
    ok(chamar("POST", "/emergencia", token=eve_t)["status"] == 201, "emergência registrada")
    ok(chamar("GET", "/auditoria", token=eve_t)["json"][0]["acao"] == "emergencia", "aparece na atividade")

    print("10) nome da pessoa")
    r = chamar("POST", "/auth/cadastro", {"nome": " Maria  Silva ", "email": "maria@t.com", "senha": SENHA})
    ok(r["status"] == 201 and r["json"]["nome"] == "Maria Silva", "cadastro guarda o nome")
    r = chamar("POST", "/auth/login", {"email": "maria@t.com", "senha": SENHA})
    ok(r["json"]["usuario"]["nome"] == "Maria Silva", "login devolve o nome")
    maria_t = r["json"]["token"]
    ok(chamar("GET", "/auth/eu", token=eve_t)["json"]["nome"] == "", "conta sem nome continua funcionando")
    ok(chamar("PUT", "/auth/nome", {"nome": "x"}, eve_t)["status"] == 400, "nome curto: 400")
    r = chamar("PUT", "/auth/nome", {"nome": "Eve Souza"}, eve_t)
    ok(r["status"] == 200 and chamar("GET", "/auth/eu", token=eve_t)["json"]["nome"] == "Eve Souza", "editar nome")
    ok(chamar("PUT", "/auth/nome", {"nome": "Outro"})["status"] == 401, "editar nome sem login: 401")

    print("\ntodos os testes da Fase 6 passaram")
finally:
    shutil.rmtree(TMP, ignore_errors=True)
