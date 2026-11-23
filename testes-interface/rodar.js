// Roda todos os testes de interface do Revoz no navegador (Chromium, sem janela).
// Usa uma cópia do frontend apontando para uma API FALSA (mock_api.py) e uma webcam
// FALSA (fake_webgazer.js): não precisa do RVC, do backend real nem de câmera.
// Antes: pare o backend real (porta 8080) e o servidor do frontend (porta 5500).
const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const PY = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const TESTES = ["teste_olhar.js", "teste_partes.js", "teste_visual.js", "teste_nome.js", "teste_ajustes2.js"];
const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

// 1) cópia do frontend com API_URL apontando para a API falsa
const origem = path.join(__dirname, "..", "frontend");
const copia = path.join(os.tmpdir(), "revoz-frontend-teste");
fs.rmSync(copia, { recursive: true, force: true });
fs.cpSync(origem, copia, { recursive: true });
const cfg = path.join(copia, "js", "config.js");
fs.writeFileSync(cfg, fs.readFileSync(cfg, "utf8").replace(/export const API_URL = .*/, 'export const API_URL = "http://127.0.0.1:8080";'));

(async () => {
  const front = spawn(PY, ["-m", "http.server", "5500", "--bind", "127.0.0.1"], { cwd: copia, stdio: "ignore" });
  await esperar(1500);
  let falhas = 0;
  for (const t of TESTES) {
    // API falsa nova a cada teste (ela guarda estado)
    const api = spawn(PY, [path.join(__dirname, "mock_api.py"), "8080"], { stdio: "ignore" });
    await esperar(1500);
    console.log(`\n=== ${t}`);
    const r = spawnSync("node", [path.join(__dirname, t)], { cwd: __dirname, encoding: "utf8", timeout: 300000 });
    process.stdout.write(r.stdout || "");
    if (r.status !== 0 || /FALHOU/.test(r.stdout || "")) falhas++;
    api.kill();
    await esperar(500);
  }
  front.kill();
  const total = (s) => (s.match(/^\s+ok - /gm) || []).length;
  console.log(falhas ? `\n${falhas} arquivo(s) com falha` : "\ntodos os testes de interface passaram");
  process.exit(falhas ? 1 : 0);
})();
