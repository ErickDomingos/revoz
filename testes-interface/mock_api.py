"""API falsa (só para testar o front): imita as rotas usadas pela página."""
import io, json, wave, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

CATS = [{"nome": "Respostas", "frases": ["Sim", "Não"]}, {"nome": "Saúde", "frases": ["Estou com dor", "Estou com frio", "Chame a enfermagem"]}, {"nome": "Família", "frases": ["Cadê a Maria?"]}]
estado = {"categorias": CATS, "frases": ["Água", "Quero dormir", "Obrigado"], "hist": [], "ativa": None,
          "vozes": [{"id": "11111111-1111-1111-1111-111111111111", "nome": "Minha voz", "detalhe": "Pronta"}],
          "log": [], "excluida": False, "generica": "feminina"}

import time, math
def wav(seg=0.1):
    b = io.BytesIO()
    n = int(40000 * seg)
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(40000)
        w.writeframes(b"".join(int(3000 * math.sin(i / 20)).to_bytes(2, "little", signed=True) for i in range(n)))
    return b.getvalue()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE")
        self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type")
        self.send_header("Access-Control-Expose-Headers", "X-Voz, X-Voz-Base")
    def do_OPTIONS(self):
        self.send_response(204); self.cors(); self.end_headers()
    def resp(self, code, obj=None, raw=None, tipo="application/json", extra=None):
        corpo = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code); self.cors()
        self.send_header("Content-Type", tipo); self.send_header("Content-Length", str(len(corpo)))
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(corpo)
    def corpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")
    def logado(self):
        return self.headers.get("Authorization") == "Bearer tok" and not estado["excluida"]
    def rota(self, m):
        u = urlparse(self.path); p = u.path
        estado["log"].append(f"{m} {p}")
        if p == "/health": return self.resp(200, {"ok": True})
        if p == "/_vel": estado["rate"] = float(parse_qs(u.query)["r"][0]); return self.resp(200, {"ok": True})
        if p == "/_estado": return self.resp(200, estado)
        if p == "/auth/cadastro" and m == "POST":
            c = self.corpo(); estado["nome"] = " ".join(c.get("nome", "").split()); estado["cadastros"] = estado.get("cadastros", 0) + 1
            return self.resp(201, {"id": 1})
        if p == "/auth/login" and m == "POST":
            estado["excluida"] = False
            return self.resp(200, {"token": "tok", "usuario": {"id": 1, "nome": estado.get("nome", ""), "email": "ana@x.com", "papel": "paciente"}})
        if p == "/consentimento/texto": return self.resp(200, {"versao": "v", "camada_identidade": "x", "camada_uso": ["a"]})
        if not self.logado(): return self.resp(401, {"detail": "Faça login"})
        if p == "/auth/eu": return self.resp(200, {"id": 1, "nome": estado.get("nome", ""), "email": "ana@x.com", "papel": "paciente"})
        if p == "/auth/nome" and m == "PUT":
            estado["nome"] = self.corpo()["nome"]
            return self.resp(200, {"id": 1, "nome": estado["nome"], "email": "ana@x.com", "papel": "paciente"})
        if p == "/frases" and m == "GET": return self.resp(200, {"categorias": estado["categorias"]})
        if p == "/frases" and m == "PUT":
            estado["categorias"] = self.corpo()["categorias"]; return self.resp(200, {"categorias": estado["categorias"]})
        if p == "/emergencia": estado["emergencias"] = estado.get("emergencias", 0) + 1; return self.resp(201, {"ok": True})
        if p == "/historico" and m == "GET": return self.resp(200, {"frases": estado["hist"][:int(parse_qs(u.query).get("n", [10])[0])]})
        if p == "/historico" and m == "POST":
            t = self.corpo()["texto"]; estado["hist"] = [t] + [x for x in estado["hist"] if x != t]; return self.resp(201, {"ok": True})
        if p == "/historico" and m == "DELETE": estado["hist"] = []; return self.resp(200, {"ok": True})
        if p == "/vozes" and m == "GET":
            return self.resp(200, [dict(v, ativa=v["id"] == estado["ativa"]) for v in estado["vozes"]])
        if p == "/vozes/ativa" and m == "PUT":
            c = self.corpo(); estado["ativa"] = c["voice_id"]; estado.setdefault("puts", []).append(c)
            if c.get("generica"): estado["generica"] = c["generica"]
            return self.resp(200, {"ok": True})
        if p == "/vozes/generica":
            return self.resp(200, {"escolhida": estado["generica"], "opcoes": [
                {"id": "feminina", "nome": "Voz genérica feminina", "disponivel": True},
                {"id": "masculina", "nome": "Voz genérica masculina", "disponivel": True}]})
        if p == "/gerar-audio":
            c = self.corpo(); estado.setdefault("pedidos", []).append(c)
            if c.get("historico"):
                estado["hist"] = [c["texto"]] + [x for x in estado["hist"] if x != c["texto"]]
            voz = "generica" if c.get("generica") or not (c.get("voice_id") or estado["ativa"]) else "clonada"
            base = c.get("base") or (estado["generica"] if voz == "generica" else "masculina")
            seg = len(c["texto"]) * 0.06 if estado.get("rate") else 0.1
            if estado.get("rate"): time.sleep(seg * estado["rate"])
            return self.resp(200, raw=wav(seg), tipo="audio/wav", extra={"X-Voz": voz, "X-Voz-Base": base})
        if p == "/conta/dados":
            return self.resp(200, {"conta": {"email": "ana@x.com"}, "frases": estado["frases"]},
                             extra={"Content-Disposition": 'attachment; filename="meus-dados-appvoice.json"'})
        if p == "/conta/excluir":
            if self.corpo().get("senha") != "certa": return self.resp(403, {"detail": "Senha incorreta."})
            estado["excluida"] = True; return self.resp(200, {"ok": True, "apagados": {"amostras": 0, "vozes": 1}})
        if p in ("/vinculos", "/amostras", "/auditoria"): return self.resp(200, [])
        if p == "/consentimento": return self.resp(200, {"valido": False})
        return self.resp(404, {"detail": "rota falsa não existe"})
    def do_GET(self): self.rota("GET")
    def do_POST(self): self.rota("POST")
    def do_PUT(self): self.rota("PUT")
    def do_DELETE(self): self.rota("DELETE")

ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
