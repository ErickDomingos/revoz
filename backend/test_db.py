"""Testes da camada de dados. Rodar:  python test_db.py   (usa um banco temporário)"""
import json
import sqlite3
import tempfile
from pathlib import Path

import db

db.DB_PATH = Path(tempfile.mkdtemp()) / "teste.db"
db.iniciar_banco()

V1, V2 = "d4e33f6e-3ecc-47bb-810b-8e51007ccd2c", "910cb3be-3fb3-4eb0-b994-ceafdb86c451"

# usuários: e-mail único, sem diferenciar maiúsculas
ana = db.criar_usuario("Ana@Exemplo.com", "hash", "paciente")
bia = db.criar_usuario("bia@exemplo.com", "hash", "cuidador")
try:
    db.criar_usuario("ana@exemplo.com", "hash")
    raise SystemExit("FALHOU: aceitou e-mail repetido")
except db.EmailJaCadastrado:
    pass
assert db.usuario_por_email("ANA@exemplo.com")["id"] == ana
try:
    db.criar_usuario("x@x.com", "hash", "admin")
    raise SystemExit("FALHOU: aceitou papel inválido")
except sqlite3.IntegrityError:
    pass

# tokens
db.invalidar_tokens(ana)
assert db.usuario_por_id(ana)["token_version"] == 1

# vínculo só vale depois de aprovado
assert not db.cuidador_pode_acessar(bia, ana)
db.vincular(bia, ana)
assert not db.cuidador_pode_acessar(bia, ana)
db.definir_status_vinculo(bia, ana, "ativo")
assert db.cuidador_pode_acessar(bia, ana)
db.definir_status_vinculo(bia, ana, "revogado")
assert not db.cuidador_pode_acessar(bia, ana)

# vozes: uma ativa por usuário e checagem de posse
db.cadastrar_voz(ana, V1)
db.cadastrar_voz(ana, V2, nome="Segunda")
assert db.voz_ativa(ana) == V2
assert db.voz_pertence_ao_usuario(ana, V1)
assert not db.voz_pertence_ao_usuario(bia, V1), "bia não pode usar a voz da ana"
assert db.voz_ativa(bia) is None
assert db.definir_voz_ativa(ana, V1) and db.voz_ativa(ana) == V1
assert not db.definir_voz_ativa(bia, V1)
assert [v["id"] for v in db.listar_vozes(ana)] == [V1, V2]
try:
    db.cadastrar_voz(ana, "../../etc/passwd")
    raise SystemExit("FALHOU: aceitou voice_id que não é UUID")
except ValueError:
    pass
assert not db.apagar_voz(bia, V1), "bia não pode apagar a voz da ana"
assert db.apagar_voz(ana, V1)

# frases da grade
db.definir_frases(ana, ["Sim", " Não ", "", "Estou com sede"])
assert db.listar_frases(ana) == ["Sim", "Não", "Estou com sede"]

# histórico: sem repetição, limite e limpeza
for t in ["a", "b", "a", "c"]:
    db.registrar_frase(ana, t)
assert db.listar_recentes(ana) == ["c", "a", "b"]
for i in range(60):
    db.registrar_frase(ana, f"frase {i}")
assert len(db.listar_recentes(ana, 100)) == db.LIMITE_HISTORICO
db.limpar_historico(ana)
assert db.listar_recentes(ana) == []

# amostras e consentimento
assert not db.tem_consentimento(ana)
am = db.registrar_amostra(ana, "ab" * 32, 900.0, "wav")
db.registrar_consentimento(ana, ana, "propria", "v1", ["ab" * 32])
assert db.tem_consentimento(ana) and len(db.listar_amostras(ana)) == 1
db.marcar_amostra_apagada(am)
assert db.listar_amostras(ana) == []

# auditoria
db.auditar("conversao", ana, V2)

# apagar usuário leva junto vozes, frases etc. (chaves estrangeiras ligadas)
with db.conexao() as con:
    con.execute("DELETE FROM usuarios WHERE id = ?", (ana,))
    assert con.execute("SELECT COUNT(*) FROM vozes WHERE usuario_id = ?", (ana,)).fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM frases WHERE usuario_id = ?", (ana,)).fetchone()[0] == 0

# migração do registry.json antigo
reg = db.DB_PATH.parent / "registry.json"
reg.write_text(json.dumps({"teste1": "910cb3be-3fb3-4eb0-b994-ceafdb86c451"}), encoding="utf-8")
assert db.migrar_registry_json(reg) == 1
assert db.migrar_registry_json(reg) == 0, "rodar duas vezes não pode duplicar"
u = db.usuario_por_email("teste1@teste.local")
assert db.voz_ativa(u["id"]) == "910cb3be-3fb3-4eb0-b994-ceafdb86c451"

print("todos os testes passaram")