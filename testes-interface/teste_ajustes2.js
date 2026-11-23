const { chromium } = require("playwright");
const fs = require("fs");
(async () => {
  const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  const fake = fs.readFileSync(__dirname + "/fake_webgazer.js", "utf8");
  const ok = (c, m) => { if (!c) { console.log("FALHOU: " + m); process.exitCode = 1; } else console.log("  ok - " + m); };
  const erros = [];
  async function abrir(w, h) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    page.on("pageerror", (e) => erros.push(e.message));
    await page.route("**/webgazer.js", (r) => r.fulfill({ body: fake, contentType: "text/javascript" }));
    await page.route("**/fonts.googleapis.com/**", (r) => r.abort());
    await page.addInitScript(() => {
      window.__taxas = [];
      const play = HTMLMediaElement.prototype.play;
      HTMLMediaElement.prototype.play = function () { if (this.src.startsWith("blob:")) window.__taxas.push(this.playbackRate); return play.call(this); };
    });
    await page.goto("http://127.0.0.1:5500/index.html"); await page.waitForTimeout(1300);
    await page.fill("#login-email", "ana@x.com"); await page.fill("#login-senha", "x"); await page.click("#login-enviar");
    await page.waitForTimeout(700);
    if (await page.isVisible("#boas-vindas")) await page.click("#btn-comecar");
    return page;
  }
  const page = await abrir(1280, 820);
  const abas = await page.$$eval('[role="tab"]', (a) => a.map((x) => x.dataset.modo));
  ok(JSON.stringify(abas) === JSON.stringify(["digitar", "olhar", "vozes", "conta", "ajustes", "guia"]), "abas: " + abas);
  await page.click("#aba-vozes"); await page.waitForTimeout(300);
  await page.click("text=Usar a minha própria voz");
  ok(await page.isVisible("#painel-consentimento") && await page.isHidden("#painel-vozes"), "abre a tela da voz própria");
  ok(await page.getAttribute("#aba-vozes", "aria-selected") === "true", "a aba Vozes continua marcada");
  await page.screenshot({ path: "voz-propria.png" });
  await page.click(".voltar-tela");
  ok(await page.isVisible("#painel-vozes"), "← Vozes volta");
  await page.click("#aba-guia"); await page.click("#painel-guia >> text=Usar a minha própria voz >> nth=0");
  ok(await page.isVisible("#painel-consentimento"), "atalho do Guia leva à voz própria");
  // tamanho do texto
  await page.click("#aba-ajustes");
  const base = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));
  await page.click("label:has(input[name=ajuste-texto][value=muito-grande])");
  const grande = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));
  ok(Math.abs(grande / base - 1.3) < 0.01, `muito grande: ${base}px -> ${grande}px`);
  await page.screenshot({ path: "ajustes-grande.png" });
  // velocidade
  await page.click("label:has(input[name=ajuste-velocidade][value='0.85'])");
  await page.reload(); await page.waitForTimeout(1500);
  ok(await page.evaluate(() => document.documentElement.dataset.texto) === "muito-grande", "tamanho do texto fica salvo");
  await page.fill("#campo-texto", "Teste de velocidade");
  await page.click("#btn-falar");
  await page.waitForFunction(() => document.body.dataset.estado === "pronto");
  ok((await page.evaluate(() => window.__taxas)).at(-1) === 0.85, "fala toca a 0,85x");
  await page.screenshot({ path: "digitar-grande.png" });
  // celular com texto muito grande
  const cel = await abrir(375, 740);
  const larg = await cel.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
  ok(larg[0] <= larg[1], "celular com texto muito grande sem rolagem horizontal " + larg);
  await cel.screenshot({ path: "celular-grande.png" });
  await cel.click("#aba-ajustes"); await cel.waitForTimeout(800); await cel.screenshot({ path: "celular-ajustes-grande.png", fullPage: true });
  ok(!erros.length, "sem erros " + erros.join("|"));
  await browser.close();
})();
