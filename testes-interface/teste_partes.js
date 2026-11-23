const { chromium } = require("playwright");
const fs = require("fs");
const API = "http://127.0.0.1:8080";
const TEXTO = "Oi, tudo bem com vocês hoje? Eu acordei com bastante dor nas costas. Queria tomar o remédio agora. Pode chamar a enfermeira, por favor? Obrigado pela ajuda.";
(async () => {
  const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  const page = await browser.newPage();
  const erros = [];
  page.on("pageerror", (e) => erros.push(e.message));
  const fake = fs.readFileSync(__dirname + "/fake_webgazer.js", "utf8");
  await page.route("**/webgazer.js", (r) => r.fulfill({ body: fake, contentType: "text/javascript" }));
  await page.addInitScript(() => {
    window.__linha = [];
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      if (this.src.startsWith("blob:")) {
        window.__linha.push(["inicio", performance.now()]);
        this.addEventListener("ended", () => window.__linha.push(["fim", performance.now()]), { once: true });
      }
      return play.call(this);
    };
  });
  const ok = (c, m) => { if (!c) { console.log("FALHOU: " + m); process.exitCode = 1; } else console.log("  ok - " + m); };
  await page.goto("http://127.0.0.1:5500/index.html"); await page.waitForTimeout(1000);
  await page.fill("#login-email", "a@x.com"); await page.fill("#login-senha", "x"); await page.click("#login-enviar");
  await page.waitForTimeout(800);
  if (await page.isVisible("#boas-vindas")) await page.click("#btn-comecar");
  await page.waitForTimeout(500);

  for (const [rate, nome] of [[0.3, "GPU (mais rápido que a fala)"], [2.5, "CPU (2,5x mais lento que a fala)"]]) {
    await fetch(`${API}/_vel?r=${rate}`);
    await page.evaluate(() => (window.__linha = []));
    const t0 = await page.evaluate(() => performance.now());
    await page.fill("#campo-texto", TEXTO.replaceAll(".", ` ${rate}.`)); // texto diferente: sem cache
    await page.click("#btn-falar");
    await page.waitForFunction(() => document.body.dataset.estado === "pronto", null, { timeout: 90000 });
    const linha = await page.evaluate(() => window.__linha);
    const inicios = linha.filter((l) => l[0] === "inicio").map((l) => l[1]);
    const fins = linha.filter((l) => l[0] === "fim").map((l) => l[1]);
    const buracos = inicios.slice(1).map((t, i) => t - fins[i]);
    const total = fins.at(-1) - t0;
    const pedacos = inicios.length;
    const sequencial = (TEXTO.length + 16) * 0.06 * rate * 1000 + (TEXTO.length + 16) * 0.06 * 1000;
    console.log(`${nome}: ${pedacos} partes, começou a falar em ${((inicios[0] - t0) / 1000).toFixed(1)} s ` +
      `(antes: ~${((TEXTO.length + 16) * 0.06 * rate).toFixed(1)} s), maior pausa entre partes ${Math.round(Math.max(...buracos))} ms`);
    ok(pedacos >= 2, "falou em partes");
    ok(Math.max(...buracos) < 300, "sem buracos entre as partes");
    ok(total < sequencial + 1500, "não ficou mais lento que antes");
    await page.waitForSelector("#btn-baixar-fala", { state: "visible", timeout: 5000 });
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#btn-baixar-fala")]);
    const arq = fs.readFileSync(await dl.path());
    const taxa = arq.readUInt32LE(24), seg = (arq.length - 44) / 2 / taxa;
    ok(taxa === 40000 && Math.abs(seg - (TEXTO.length + 16) * 0.06) < 0.5, `Baixar junta tudo num WAV só (${seg.toFixed(1)} s a ${taxa} Hz)`);
  }
  const hist = (await (await fetch(API + "/_estado")).json()).hist;
  ok(hist[0] === TEXTO.replaceAll(".", " 2.5."), "a frase inteira vai para as Recentes (não as partes)");
  ok(!erros.length, "sem erros " + erros.join("|"));
  await browser.close();
})();
