"""
db.py - camada de dados do backend (SQLite, só biblioteca padrão).

Fica na pasta do backend, ao lado do main.py. Quem faz login/cadastro (Fase 5)
chama estas funções; nenhum outro arquivo deve escrever SQL.

Decisões (para o relatório):
- SQLite no protótipo: zero instalação e roda no mesmo ambiente do RVC. Em
  produção, troca-se por PostgreSQL mexendo só neste arquivo.
- O banco guarda só METADADOS. Os arquivos (modelos .pth, áudios) ficam no
  disco, em pastas que não são servidas pela API, e o caminho é sempre
  derivado do id (voice_id / amostra_id), nunca gravado nem vindo do cliente.
- Senha: o banco só recebe o HASH (quem gera é a camada de login).
- Texto das frases NUNCA vai para a tabela de auditoria (pode revelar saúde).
"""

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("APPVOICE_DB", Path(__file__).parent / "data" / "appvoice.db"))

LIMITE_HISTORICO = 50   # frases recentes guardadas por usuário
MAX_FRASES = 12         # frases da grade do modo Olhar (formato antigo, sem categorias)
MAX_CATEGORIAS = 8      # categorias de frases prontas
MAX_POR_CATEGORIA = 8   # frases em cada categoria (com "Voltar", a grade fica em até 3 x 3)
MAX_NOME_CATEGORIA = 40
CATEGORIA_PADRAO = "Frases"
MAX_TEXTO = 300         # tamanho máximo de uma frase

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    senha_hash    TEXT NOT NULL,
    papel         TEXT NOT NULL CHECK (papel IN ('paciente', 'cuidador')),
    token_version INTEGER NOT NULL DEFAULT 0,   -- sobe para invalidar todos os tokens
    voz_generica  TEXT NOT NULL DEFAULT 'feminina',  -- voz genérica escolhida (feminina|masculina)
    criado_em     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vinculos (           -- cuidador acompanha paciente
    cuidador_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    paciente_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'ativo', 'revogado')),
    criado_em   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (cuidador_id, paciente_id),
    CHECK (cuidador_id <> paciente_id)
);

CREATE TABLE IF NOT EXISTS vozes (              -- arquivos em voice_models/<voice_id>/
    voice_id   TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    nome       TEXT NOT NULL DEFAULT 'Minha voz',
    status     TEXT NOT NULL DEFAULT 'pronta' CHECK (status IN ('treinando', 'pronta', 'erro')),
    ativa      INTEGER NOT NULL DEFAULT 0,
    voz_base   TEXT NOT NULL DEFAULT 'feminina',  -- voz genérica que o RVC converte (feminina|masculina)
    criado_em  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uma_voz_ativa ON vozes(usuario_id) WHERE ativa = 1;

CREATE TABLE IF NOT EXISTS amostras_audio (     -- áudios de referência (arquivos em disco)
    id         TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    sha256     TEXT NOT NULL,
    duracao_s  REAL,
    formato    TEXT,
    criado_em  TEXT NOT NULL DEFAULT (datetime('now')),
    apagado_em TEXT                             -- preenchido quando o arquivo é removido
);

CREATE TABLE IF NOT EXISTS consentimentos (     -- Fase 5, item 21
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id      INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,  -- dono da voz
    declarante_id   INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,  -- quem declarou
    relacao         TEXT NOT NULL CHECK (relacao IN ('propria', 'responsavel_legal')),
    nome_declarante TEXT,                       -- camada 1: identidade de quem assina
    versao_texto    TEXT NOT NULL,
    sha256_amostras TEXT NOT NULL,              -- camada 2: lista JSON dos hashes dos áudios autorizados
    criado_em       TEXT NOT NULL DEFAULT (datetime('now')),
    revogado_em     TEXT                        -- preenchido quando o dono revoga
);

CREATE TABLE IF NOT EXISTS auditoria (          -- Fase 5, item 23: só metadados, nunca o texto
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    quando     TEXT NOT NULL DEFAULT (datetime('now')),
    usuario_id INTEGER,
    voice_id   TEXT,
    acao       TEXT NOT NULL,
    resultado  TEXT NOT NULL DEFAULT 'ok'
);

CREATE TABLE IF NOT EXISTS frases (             -- grade do modo Olhar, por usuário
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    posicao    INTEGER NOT NULL,
    texto      TEXT NOT NULL,
    PRIMARY KEY (usuario_id, posicao)
);

CREATE TABLE IF NOT EXISTS historico (          -- frases recentes (o usuário pode limpar)
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    texto      TEXT NOT NULL,
    criado_em  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_historico_usuario ON historico(usuario_id, id);
"""


class EmailJaCadastrado(Exception):
    pass


@contextmanager
def conexao():
    """Uma conexão por operação (o FastAPI atende requisições em threads diferentes)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")  # no SQLite isso vem desligado por padrão
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# Colunas novas em tabelas que já existiam em bancos antigos (CREATE TABLE IF NOT
# EXISTS não altera tabela existente, então elas são adicionadas aqui).
_COLUNAS_NOVAS = {
    "consentimentos": {"nome_declarante": "TEXT", "revogado_em": "TEXT"},
    "usuarios": {"voz_generica": "TEXT NOT NULL DEFAULT 'feminina'"},
    "vozes": {"voz_base": "TEXT NOT NULL DEFAULT 'feminina'"},
    "frases": {"categoria": "TEXT NOT NULL DEFAULT 'Frases'"},
    "usuarios": {"nome": "TEXT NOT NULL DEFAULT ''"},  # contas antigas ficam sem nome até a pessoa preencher
}

VOZES_GENERICAS = ("feminina", "masculina")


def iniciar_banco() -> None:
    """Cria as tabelas se não existirem. Chamar uma vez, na subida do servidor."""
    with conexao() as con:
        con.execute("PRAGMA journal_mode = WAL")  # leituras não travam durante uma escrita
        con.executescript(SCHEMA)
        for tabela, colunas in _COLUNAS_NOVAS.items():
            existentes = {l["name"] for l in con.execute(f"PRAGMA table_info({tabela})")}
            for nome, tipo in colunas.items():
                if nome not in existentes:
                    con.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")


def _um(con, sql, params=()):
    linha = con.execute(sql, params).fetchone()
    return dict(linha) if linha else None


# ------------------------------------------------------------------ usuários
MAX_NOME = 80


def limpar_nome(nome: str) -> str:
    """Tira espaços repetidos e caracteres de controle; corta em MAX_NOME."""
    nome = "".join(c for c in (nome or "") if c.isprintable())
    return " ".join(nome.split())[:MAX_NOME]


def criar_usuario(email: str, senha_hash: str, papel: str = "paciente", nome: str = "") -> int:
    try:
        with conexao() as con:
            cur = con.execute(
                "INSERT INTO usuarios (email, senha_hash, papel, nome) VALUES (?, ?, ?, ?)",
                (email.strip().lower(), senha_hash, papel, limpar_nome(nome)),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError as erro:
        if "usuarios.email" in str(erro):
            raise EmailJaCadastrado(email) from erro
        raise


def usuario_por_email(email: str):
    with conexao() as con:
        return _um(con, "SELECT * FROM usuarios WHERE email = ?", (email.strip().lower(),))


def usuario_por_id(usuario_id: int):
    with conexao() as con:
        return _um(con, "SELECT * FROM usuarios WHERE id = ?", (usuario_id,))


def definir_nome(usuario_id: int, nome: str) -> str:
    nome = limpar_nome(nome)
    with conexao() as con:
        con.execute("UPDATE usuarios SET nome = ? WHERE id = ?", (nome, usuario_id))
    return nome


def invalidar_tokens(usuario_id: int) -> None:
    """'Sair de todos os dispositivos': tokens com a versão antiga deixam de valer."""
    with conexao() as con:
        con.execute("UPDATE usuarios SET token_version = token_version + 1 WHERE id = ?", (usuario_id,))


# ------------------------------------------------------------ vínculos
def vincular(cuidador_id: int, paciente_id: int) -> None:
    """Cria o pedido de vínculo (fica 'pendente' até o paciente aprovar).

    Um vínculo revogado pode ser pedido de novo: volta para 'pendente'.
    """
    with conexao() as con:
        con.execute(
            "INSERT INTO vinculos (cuidador_id, paciente_id) VALUES (?, ?) "
            "ON CONFLICT (cuidador_id, paciente_id) DO UPDATE SET status = 'pendente' "
            "WHERE vinculos.status = 'revogado'",
            (cuidador_id, paciente_id),
        )


def status_vinculo(cuidador_id: int, paciente_id: int):
    with conexao() as con:
        linha = _um(con, "SELECT status FROM vinculos WHERE cuidador_id = ? AND paciente_id = ?",
                    (cuidador_id, paciente_id))
        return linha["status"] if linha else None


def listar_vinculos(usuario_id: int) -> list:
    """Vínculos em que o usuário aparece (como cuidador ou como paciente), com o e-mail do outro lado."""
    with conexao() as con:
        linhas = con.execute(
            """SELECT v.cuidador_id, v.paciente_id, v.status, v.criado_em,
                      c.email AS cuidador_email, p.email AS paciente_email,
                      c.nome AS cuidador_nome, p.nome AS paciente_nome
                 FROM vinculos v
                 JOIN usuarios c ON c.id = v.cuidador_id
                 JOIN usuarios p ON p.id = v.paciente_id
                WHERE v.cuidador_id = ? OR v.paciente_id = ?
                ORDER BY v.criado_em""",
            (usuario_id, usuario_id),
        ).fetchall()
    return [dict(l) for l in linhas]


def definir_status_vinculo(cuidador_id: int, paciente_id: int, status: str) -> None:
    with conexao() as con:
        con.execute(
            "UPDATE vinculos SET status = ? WHERE cuidador_id = ? AND paciente_id = ?",
            (status, cuidador_id, paciente_id),
        )


def cuidador_pode_acessar(cuidador_id: int, paciente_id: int) -> bool:
    with conexao() as con:
        return _um(
            con,
            "SELECT 1 AS ok FROM vinculos WHERE cuidador_id = ? AND paciente_id = ? AND status = 'ativo'",
            (cuidador_id, paciente_id),
        ) is not None


# --------------------------------------------------------------- vozes
def cadastrar_voz(usuario_id: int, voice_id: str, nome: str = "Minha voz",
                  ativa: bool = True, status: str = "pronta", voz_base: str = "feminina") -> str:
    voice_id = str(uuid.UUID(voice_id))  # só UUID válido entra
    if voz_base not in VOZES_GENERICAS:
        raise ValueError(f"voz_base precisa ser uma de {VOZES_GENERICAS}")
    with conexao() as con:
        if ativa:
            con.execute("UPDATE vozes SET ativa = 0 WHERE usuario_id = ?", (usuario_id,))
        con.execute(
            "INSERT INTO vozes (voice_id, usuario_id, nome, status, ativa, voz_base) VALUES (?, ?, ?, ?, ?, ?)",
            (voice_id, usuario_id, nome, status, 1 if ativa else 0, voz_base),
        )
    return voice_id


def voz_base(voice_id: str) -> str:
    """Qual voz genérica serve de entrada para o RVC ao falar com esta voz clonada."""
    with conexao() as con:
        linha = _um(con, "SELECT voz_base FROM vozes WHERE voice_id = ?", (voice_id,))
    return linha["voz_base"] if linha else "feminina"


def voz_generica(usuario_id: int) -> str:
    with conexao() as con:
        linha = _um(con, "SELECT voz_generica FROM usuarios WHERE id = ?", (usuario_id,))
    return linha["voz_generica"] if linha else "feminina"


def definir_voz_generica(usuario_id: int, base: str) -> None:
    if base not in VOZES_GENERICAS:
        raise ValueError(f"voz genérica precisa ser uma de {VOZES_GENERICAS}")
    with conexao() as con:
        con.execute("UPDATE usuarios SET voz_generica = ? WHERE id = ?", (base, usuario_id))


def voz_ativa(usuario_id: int):
    with conexao() as con:
        linha = _um(
            con,
            "SELECT voice_id FROM vozes WHERE usuario_id = ? AND ativa = 1 AND status = 'pronta'",
            (usuario_id,),
        )
        return linha["voice_id"] if linha else None


def voz_pertence_ao_usuario(usuario_id: int, voice_id: str) -> bool:
    """Checagem de posse: use sempre que o cliente mandar um voice_id."""
    with conexao() as con:
        return _um(
            con,
            "SELECT 1 AS ok FROM vozes WHERE voice_id = ? AND usuario_id = ? AND status = 'pronta'",
            (voice_id, usuario_id),
        ) is not None


def definir_voz_ativa(usuario_id: int, voice_id: str) -> bool:
    if not voz_pertence_ao_usuario(usuario_id, voice_id):
        return False
    with conexao() as con:
        con.execute("UPDATE vozes SET ativa = 0 WHERE usuario_id = ?", (usuario_id,))
        con.execute("UPDATE vozes SET ativa = 1 WHERE voice_id = ?", (voice_id,))
    return True


def desativar_vozes(usuario_id: int) -> None:
    """Fase 6: nenhuma voz clonada ativa -> o app fala com a voz genérica."""
    with conexao() as con:
        con.execute("UPDATE vozes SET ativa = 0 WHERE usuario_id = ?", (usuario_id,))


def listar_vozes(usuario_id: int) -> list:
    """No formato que o front-end espera de GET /vozes: [{id, nome, detalhe, ativa}]."""
    with conexao() as con:
        linhas = con.execute(
            "SELECT voice_id, nome, status, ativa, voz_base FROM vozes WHERE usuario_id = ? ORDER BY criado_em",
            (usuario_id,),
        ).fetchall()
    return [{"id": l["voice_id"], "nome": l["nome"], "detalhe": l["status"].capitalize(),
             "ativa": bool(l["ativa"]), "base": l["voz_base"]} for l in linhas]


def apagar_voz(usuario_id: int, voice_id: str) -> bool:
    """Remove o registro. QUEM CHAMA deve apagar também a pasta voice_models/<voice_id>/."""
    with conexao() as con:
        cur = con.execute("DELETE FROM vozes WHERE voice_id = ? AND usuario_id = ?", (voice_id, usuario_id))
        return cur.rowcount > 0


# ------------------------------------------------- amostras e consentimento
def registrar_amostra(usuario_id: int, sha256: str, duracao_s: float = None, formato: str = None) -> str:
    amostra_id = str(uuid.uuid4())
    with conexao() as con:
        con.execute(
            "INSERT INTO amostras_audio (id, usuario_id, sha256, duracao_s, formato) VALUES (?, ?, ?, ?, ?)",
            (amostra_id, usuario_id, sha256, duracao_s, formato),
        )
    return amostra_id


def amostra_do_usuario(usuario_id: int, amostra_id: str):
    """A amostra, se for deste usuário e não tiver sido apagada (checagem de posse)."""
    with conexao() as con:
        return _um(con, "SELECT * FROM amostras_audio WHERE id = ? AND usuario_id = ? AND apagado_em IS NULL",
                   (amostra_id, usuario_id))


def listar_amostras(usuario_id: int) -> list:
    with conexao() as con:
        return [dict(l) for l in con.execute(
            "SELECT * FROM amostras_audio WHERE usuario_id = ? AND apagado_em IS NULL ORDER BY criado_em",
            (usuario_id,),
        ).fetchall()]


def marcar_amostra_apagada(amostra_id: str) -> None:
    with conexao() as con:
        con.execute("UPDATE amostras_audio SET apagado_em = datetime('now') WHERE id = ?", (amostra_id,))


def registrar_consentimento(usuario_id: int, declarante_id: int, relacao: str,
                            versao_texto: str, sha256_amostras: list,
                            nome_declarante: str = None) -> int:
    """Grava um consentimento novo. Consentimentos antigos ficam como histórico."""
    with conexao() as con:
        cur = con.execute(
            "INSERT INTO consentimentos (usuario_id, declarante_id, relacao, nome_declarante, "
            "versao_texto, sha256_amostras) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, declarante_id, relacao, nome_declarante, versao_texto,
             json.dumps(sorted(sha256_amostras))),
        )
        return cur.lastrowid


def consentimento_valido(usuario_id: int):
    """O consentimento mais recente que não foi revogado, ou None."""
    with conexao() as con:
        linha = _um(
            con,
            "SELECT * FROM consentimentos WHERE usuario_id = ? AND revogado_em IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (usuario_id,),
        )
    if linha:
        linha["sha256_amostras"] = json.loads(linha["sha256_amostras"])
    return linha


def tem_consentimento(usuario_id: int) -> bool:
    return consentimento_valido(usuario_id) is not None


def revogar_consentimento(usuario_id: int) -> int:
    """Revoga todos os consentimentos ativos do dono da voz. Devolve quantos foram revogados."""
    with conexao() as con:
        cur = con.execute(
            "UPDATE consentimentos SET revogado_em = datetime('now') "
            "WHERE usuario_id = ? AND revogado_em IS NULL",
            (usuario_id,),
        )
        return cur.rowcount


# ------------------------------------------------------------ auditoria
def auditar(acao: str, usuario_id: int = None, voice_id: str = None, resultado: str = "ok") -> int:
    """Registra QUE algo aconteceu. Nunca passe o texto da frase aqui. Devolve o id do registro."""
    with conexao() as con:
        cur = con.execute(
            "INSERT INTO auditoria (usuario_id, voice_id, acao, resultado) VALUES (?, ?, ?, ?)",
            (usuario_id, voice_id, acao, resultado),
        )
        return cur.lastrowid


def definir_resultado_auditoria(registro_id: int, resultado: str) -> None:
    with conexao() as con:
        con.execute("UPDATE auditoria SET resultado = ? WHERE id = ?", (resultado, registro_id))


def registro_auditoria(registro_id: int):
    with conexao() as con:
        return _um(con, "SELECT * FROM auditoria WHERE id = ?", (registro_id,))


def listar_auditoria(usuario_id: int, n: int = 50) -> list:
    """O que o usuário fez E o que outros fizeram com as vozes dele (ex.: um cuidador)."""
    with conexao() as con:
        linhas = con.execute(
            """SELECT a.id, a.quando, a.acao, a.resultado, a.voice_id,
                      a.usuario_id, u.email AS quem
                 FROM auditoria a
                 LEFT JOIN usuarios u ON u.id = a.usuario_id
                WHERE a.usuario_id = ?
                   OR a.voice_id IN (SELECT voice_id FROM vozes WHERE usuario_id = ?)
                ORDER BY a.id DESC LIMIT ?""",
            (usuario_id, usuario_id, n),
        ).fetchall()
    return [dict(l) for l in linhas]


# ---------------------------------------------------- frases e histórico
def definir_frases(usuario_id: int, frases: list) -> None:
    """Formato antigo: uma lista simples vira uma categoria só."""
    limpas = [f.strip()[:MAX_TEXTO] for f in frases if f and f.strip()][:MAX_FRASES]
    definir_categorias(usuario_id, [{"nome": CATEGORIA_PADRAO, "frases": limpas}])


def definir_categorias(usuario_id: int, categorias: list) -> None:
    """categorias: [{"nome": "Saúde", "frases": ["Estou com dor", ...]}, ...], na ordem da tela."""
    linhas = []
    for cat in categorias[:MAX_CATEGORIAS]:
        nome = (cat.get("nome") or "").strip()[:MAX_NOME_CATEGORIA] or CATEGORIA_PADRAO
        frases = [f.strip()[:MAX_TEXTO] for f in cat.get("frases", []) if f and f.strip()]
        linhas += [(nome, f) for f in frases[:MAX_POR_CATEGORIA]]
    with conexao() as con:
        con.execute("DELETE FROM frases WHERE usuario_id = ?", (usuario_id,))
        con.executemany(
            "INSERT INTO frases (usuario_id, posicao, categoria, texto) VALUES (?, ?, ?, ?)",
            [(usuario_id, i, nome, texto) for i, (nome, texto) in enumerate(linhas)],
        )


def listar_frases(usuario_id: int) -> list:
    with conexao() as con:
        return [l["texto"] for l in con.execute(
            "SELECT texto FROM frases WHERE usuario_id = ? ORDER BY posicao", (usuario_id,)
        ).fetchall()]


def listar_categorias(usuario_id: int) -> list:
    """As frases agrupadas por categoria, na ordem em que foram salvas."""
    with conexao() as con:
        linhas = con.execute(
            "SELECT categoria, texto FROM frases WHERE usuario_id = ? ORDER BY posicao", (usuario_id,)
        ).fetchall()
    categorias = []
    for l in linhas:
        if not categorias or categorias[-1]["nome"] != l["categoria"]:
            categorias.append({"nome": l["categoria"], "frases": []})
        categorias[-1]["frases"].append(l["texto"])
    return categorias


def registrar_frase(usuario_id: int, texto: str, limite: int = LIMITE_HISTORICO) -> None:
    texto = (texto or "").strip()[:MAX_TEXTO]
    if not texto:
        return
    with conexao() as con:
        con.execute("DELETE FROM historico WHERE usuario_id = ? AND texto = ?", (usuario_id, texto))
        con.execute("INSERT INTO historico (usuario_id, texto) VALUES (?, ?)", (usuario_id, texto))
        con.execute(
            "DELETE FROM historico WHERE usuario_id = ? AND id NOT IN "
            "(SELECT id FROM historico WHERE usuario_id = ? ORDER BY id DESC LIMIT ?)",
            (usuario_id, usuario_id, limite),
        )


def listar_recentes(usuario_id: int, n: int = 10) -> list:
    with conexao() as con:
        return [l["texto"] for l in con.execute(
            "SELECT texto FROM historico WHERE usuario_id = ? ORDER BY id DESC LIMIT ?", (usuario_id, n)
        ).fetchall()]


def limpar_historico(usuario_id: int) -> None:
    with conexao() as con:
        con.execute("DELETE FROM historico WHERE usuario_id = ?", (usuario_id,))


# ------------------------------------------------- Fase 6: direitos do titular (LGPD)
def exportar_dados(usuario_id: int) -> dict:
    """Tudo o que o banco guarda sobre o usuário (portabilidade, LGPD art. 18).

    Ficam de fora o hash da senha e a token_version, que são controles internos.
    Os arquivos (áudios e modelos) não entram: são grandes e ficam criptografados.
    """
    usuario = usuario_por_id(usuario_id)
    if usuario is None:
        return {}
    with conexao() as con:
        def todos(sql, *params):
            return [dict(l) for l in con.execute(sql, params).fetchall()]

        consentimentos = todos(
            "SELECT id, usuario_id AS dono_id, declarante_id, relacao, nome_declarante, versao_texto, "
            "sha256_amostras, criado_em, revogado_em FROM consentimentos "
            "WHERE usuario_id = ? OR declarante_id = ? ORDER BY id", usuario_id, usuario_id)
        for c in consentimentos:
            c["sha256_amostras"] = json.loads(c["sha256_amostras"])
        dados = {
            "conta": {k: usuario[k] for k in ("id", "nome", "email", "papel", "voz_generica", "criado_em")},
            "vozes": todos("SELECT voice_id, nome, status, ativa, voz_base, criado_em FROM vozes "
                           "WHERE usuario_id = ? ORDER BY criado_em", usuario_id),
            "amostras": todos("SELECT id, sha256, duracao_s, formato, criado_em, apagado_em "
                              "FROM amostras_audio WHERE usuario_id = ? ORDER BY criado_em", usuario_id),
            "consentimentos": consentimentos,
            "vinculos": todos("SELECT cuidador_id, paciente_id, status, criado_em FROM vinculos "
                              "WHERE cuidador_id = ? OR paciente_id = ?", usuario_id, usuario_id),
            "frases": [l["texto"] for l in todos(
                "SELECT texto FROM frases WHERE usuario_id = ? ORDER BY posicao", usuario_id)],
            "categorias": listar_categorias(usuario_id),
            "historico": todos("SELECT texto, criado_em FROM historico WHERE usuario_id = ? "
                               "ORDER BY id DESC", usuario_id),
        }
    dados["auditoria"] = listar_auditoria(usuario_id, n=1000)
    return dados


def apagar_usuario(usuario_id: int) -> bool:
    """Apaga a conta e, em cascata, vozes, amostras, consentimentos, vínculos, frases e histórico.

    QUEM CHAMA deve apagar antes os ARQUIVOS (amostras/ e voice_models/).
    A auditoria fica (sem e-mail, só o número do usuário): é ela que liga a marca
    d'água de um áudio já gerado ao registro de quando ele foi gerado.
    """
    with conexao() as con:
        # Bancos criados com a versão antiga do schema não têm ON DELETE CASCADE
        # nesta coluna; apagando antes, funciona nos dois casos. Consentimentos que
        # esta pessoa assinou como responsável legal deixam de valer junto.
        con.execute("DELETE FROM consentimentos WHERE declarante_id = ?", (usuario_id,))
        cur = con.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
        return cur.rowcount > 0


# ------------------------------------------------ migração do registry.json
def migrar_registry_json(caminho_json) -> int:
    """Passa o voice_models/registry.json antigo ({"teste1": "<voice_id>"}) para o banco.

    Só para desenvolvimento: cada nome do JSON vira um usuário de teste
    (<nome>@teste.local) com senha inutilizável, dono da voz correspondente.
    """
    registro = json.loads(Path(caminho_json).read_text(encoding="utf-8"))
    migradas = 0
    for nome, voice_id in registro.items():
        usuario = usuario_por_email(f"{nome}@teste.local")
        usuario_id = usuario["id"] if usuario else criar_usuario(f"{nome}@teste.local", "!", "paciente")
        try:
            cadastrar_voz(usuario_id, voice_id, nome=f"Voz de {nome}")
            migradas += 1
        except sqlite3.IntegrityError:
            pass  # já migrada
    return migradas


if __name__ == "__main__":
    iniciar_banco()
    print(f"banco pronto em: {DB_PATH}")