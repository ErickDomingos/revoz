const { chromium } = require("playwright");
const fs = require("fs");
const API = "http://127.0.0.1:8080";
(async () => {
  const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  const page = await ctx.newPage();
  const erros = [];
  page.on("pageerror", (e) => erros.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/i.test(m.text())) erros.push("console: " + m.text()); });
  const fake = fs.readFileSync(__dirname + "/fake_webgazer.js", "utf8");
  await page.route("**/webgazer.js", (r) => r.fulfill({ body: fake, contentType: "text/javascript" }));
  const estado = async () => (await (await fetch(API + "/_estado")).json());
  const ok = (c, m) => { if (!c) { console.log("FALHOU: " + m); process.exitCode = 1; } else console.log("  ok - " + m); };
  const centro = (sel) => page.$eval(sel, (e) => { const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
  const olharPara = async (sel, dx = 0) => { const c = await centro(sel); await page.evaluate(([x, y]) => (window.__alvo = { x, y }), [c.x + dx, c.y]); };
  const titulo = () => page.textContent("#titulo-olhar");

  await page.goto("http://127.0.0.1:5500/index.html");
  await page.waitForTimeout(1200);
  await page.evaluate(() => { window.__falas = []; new MutationObserver(() => { const t = document.getElementById("status").textContent; if (t.startsWith("Falando")) window.__falas.push(t); }).observe(document.getElementById("status"), { childList: true, characterData: true, subtree: true }); });
  const falas = (txt) => page.evaluate((t) => window.__falas.filter((f) => f.includes(t)).length, txt);
  ok(await page.isHidden("#btn-sair-topo"), "sem login, o Sair do topo fica escondido");
  await page.fill("#login-email", "ana@x.com"); await page.fill("#login-senha", "x"); await page.click("#login-enviar");
  await page.waitForTimeout(800);
  if (await page.isVisible("#boas-vindas")) await page.click("#btn-comecar");
  ok(await page.isVisible("#btn-sair-topo") && await page.isVisible("#btn-emergencia"), "topo mostra Emergência e Sair");

  // Digitar: frases prontas
  const cats = await page.$$eval("#prontas-categorias .chip", (c) => c.map((x) => x.textContent));
  ok(JSON.stringify(cats) === JSON.stringify(["Respostas", "Saúde", "Família"]), "categorias da conta no Digitar: " + cats);
  await page.click("#prontas-categorias .chip:has-text('Saúde')");
  const fr = await page.$$eval("#prontas-frases .chip", (c) => c.map((x) => x.textContent));
  ok(fr[0] === "Estou com dor" && fr.length === 3, "tocar a categoria mostra as frases dela");
  await page.click("#prontas-frases .chip:has-text('Estou com frio')");
  await page.waitForFunction(() => document.body.dataset.estado === "pronto");
  await page.waitForTimeout(300);
  let st = await estado();
  ok(st.pedidos.some((p) => p.texto === "Estou com frio"), "tocar a frase pronta fala");
  ok(st.pedidos.some((p) => p.texto.startsWith("Preciso de ajuda")), "a frase de socorro foi gerada antes (cache)");
  await page.screenshot({ path: "digitar.png" });

  // Ajustes: editor
  await page.click("#aba-ajustes");
  ok(await page.$$eval(".cat-editor", (c) => c.length) === 3, "editor mostra as 3 categorias");
  await page.click("#btn-nova-categoria");
  await page.fill(".cat-editor:last-child .cat-nome", "Lazer");
  await page.fill(".cat-editor:last-child .cat-frases", "Quero ver TV\n\nQuero ouvir música");
  await page.click(".cat-editor:last-child button[aria-label='Subir categoria']");
  await page.click("#btn-salvar-frases"); await page.waitForTimeout(500);
  st = await estado();
  ok(JSON.stringify(st.categorias.map((c) => c.nome)) === JSON.stringify(["Respostas", "Saúde", "Lazer", "Família"]) &&
     st.categorias[2].frases.length === 2, "salvou com a nova categoria na posição certa");
  ok((await page.textContent("#frases-msg")) === "Frases salvas.", "mensagem de salvo");
  await page.fill(".cat-editor:first-child .cat-nome", "Saúde");
  await page.click("#btn-salvar-frases");
  ok((await page.textContent("#frases-msg")).includes("mesmo nome"), "nome repetido é recusado antes de enviar");
  await page.fill(".cat-editor:first-child .cat-nome", "Respostas");
  await page.screenshot({ path: "ajustes.png", fullPage: true });

  // Olhar com os olhos
  await page.click("#aba-olhar");
  await page.waitForSelector("#calibracao", { state: "visible", timeout: 3000 }).catch(() => {});
  ok(await page.isVisible("#calibracao"), "abre a calibração");
  await page.waitForSelector("#calibracao", { state: "hidden", timeout: 60000 });
  ok(await page.evaluate(() => window.__semMouse === true), "o mouse não treina o WebGazer");
  ok(await page.evaluate(() => window.__gravados) > 100, "gravou os 13 pontos: " + await page.evaluate(() => window.__gravados));
  const prec = await page.textContent("#precisao-olhar");
  ok(prec.startsWith("Precisão boa"), "teste de precisão: " + prec);
  const tiles = await page.$$eval("#grade .frase", (t) => t.map((x) => x.textContent));
  ok(JSON.stringify(tiles) === JSON.stringify(["Respostas", "Saúde", "Lazer", "Família", "Emergência"]), "nível 1: " + tiles);
  await olharPara("#grade .frase:nth-child(2)");
  await page.waitForTimeout(2300);
  ok(await titulo() === "Saúde", "olhar a categoria abre as frases dela");
  ok((await page.$$eval("#grade .frase", (t) => t.map((x) => x.textContent)))[0] === "← Voltar", "primeiro botão é Voltar");
  await page.waitForTimeout(2500);
  ok(await titulo() === "Saúde" && await falas("Estou com dor") === 0,
     "olhar parado no mesmo lugar não escolhe o botão novo que ficou embaixo");
  // botão 3 = "Estou com frio": ponto um pouco fora da borda (ímã)
  const box = await page.$eval("#grade .frase:nth-child(3)", (e) => { const r = e.getBoundingClientRect(); return { x: r.left - 15, y: r.top + r.height / 2 }; });
  await page.evaluate(([x, y]) => (window.__alvo = { x, y }), [box.x, box.y]);
  await page.waitForTimeout(2600);
  await page.waitForFunction(() => document.body.dataset.estado === "pronto");
  ok(await falas("Estou com frio") === 2, "ponto logo fora da borda ainda escolhe (ímã)");
  await page.screenshot({ path: "olhar-saude.png" });
  await olharPara("#grade .frase:nth-child(1)");
  await page.waitForTimeout(2300);
  ok(await titulo() === "Escolha uma categoria", "Voltar volta para as categorias");

  // emergência pelo olhar
  await olharPara("#grade .tipo-emergencia");
  await page.waitForTimeout(1500);
  ok(await page.isHidden("#emergencia"), "emergência pede mais tempo (1,5x)");
  await page.waitForTimeout(1300);
  ok(await page.isVisible("#emergencia"), "olhar a Emergência liga o alarme");
  await page.waitForTimeout(500);
  ok((await estado()).emergencias === 1, "emergência registrada no servidor");
  await page.screenshot({ path: "emergencia.png" });
  await olharPara("#btn-parar-emergencia");
  await page.waitForTimeout(3200);
  ok(await page.isHidden("#emergencia"), "olhar 'Parar alarme' desliga");

  // emergência pelo botão do topo + parar com clique
  await page.click("#btn-emergencia");
  ok(await page.isVisible("#emergencia"), "botão do topo liga o alarme");
  await page.waitForTimeout(3000); // o olhar está no lugar do Parar: não pode desligar sozinho
  ok(await page.isVisible("#emergencia"), "olhar parado em cima do Parar não desliga o alarme que acabou de ligar");
  await page.click("#btn-parar-emergencia");
  ok(await page.isHidden("#emergencia"), "clique no Parar desliga");

  // Modo cabeça
  await page.click("#aba-ajustes");
  await page.check("input[name='ajuste-apontar'][value='cabeca']");
  ok(await page.isVisible("#grupo-sensibilidade"), "sensibilidade aparece no modo cabeça");
  await page.click("#aba-olhar");
  ok(await page.isVisible("#calibracao"), "trocar para cabeça calibra de novo");
  ok((await page.textContent("#calibracao-texto")).includes("nariz"), "texto da calibração da cabeça");
  await page.waitForSelector("#calibracao", { state: "hidden", timeout: 30000 });
  ok((await page.textContent("#precisao-olhar")).startsWith("Pronto. Mova"), "cabeça calibrada: " + await page.textContent("#precisao-olhar"));
  await olharPara("#grade .frase:nth-child(4)");
  await page.waitForTimeout(400);
  const p = await page.$eval("#ponto-olhar", (e) => ({ x: parseFloat(e.style.left), y: parseFloat(e.style.top) }));
  const c4 = await centro("#grade .frase:nth-child(4)");
  ok(Math.hypot(p.x - c4.x, p.y - c4.y) < 40, `o nariz leva o ponto até o botão (erro ${Math.round(Math.hypot(p.x - c4.x, p.y - c4.y))} px)`);
  await page.waitForTimeout(2200);
  ok(await titulo() === "Família", "com a cabeça também abre a categoria");
  await page.evaluate(() => (window.__semRosto = true));
  await page.waitForTimeout(4200);
  ok((await page.textContent("#aviso-olhar")).includes("rosto"), "avisa quando perde o rosto no modo cabeça");
  await page.evaluate(() => (window.__semRosto = false));

  // Sair pelo topo
  await page.click("#btn-sair-topo"); await page.waitForTimeout(400);
  ok(await page.isVisible("#login") && await page.isHidden("#btn-sair-topo"), "Sair do topo volta ao login");
  ok(JSON.stringify(await page.$$eval("#prontas-categorias .chip", (c) => c.map((x) => x.textContent))) ===
     JSON.stringify(["Respostas", "Necessidades", "Saúde", "Sentimentos", "Conversa"]), "depois de sair, volta às categorias padrão");

  // celular
  const cel = await browser.newPage({ viewport: { width: 375, height: 740 } });
  await cel.route("**/webgazer.js", (r) => r.fulfill({ body: fake, contentType: "text/javascript" }));
  await cel.goto("http://127.0.0.1:5500/index.html"); await cel.waitForTimeout(1200);
  await cel.fill("#login-email", "ana@x.com"); await cel.fill("#login-senha", "x"); await cel.click("#login-enviar");
  await cel.waitForTimeout(800);
  if (await cel.isVisible("#boas-vindas")) await cel.click("#btn-comecar");
  const larg = await cel.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
  ok(larg[0] <= larg[1], "sem rolagem horizontal no celular " + larg);
  const topo = await cel.$eval(".topo", (e) => e.getBoundingClientRect().height);
  ok(topo < 80, "topo cabe numa linha no celular (" + Math.round(topo) + " px)");
  await cel.screenshot({ path: "celular.png" });
  await cel.click("#aba-ajustes"); await cel.screenshot({ path: "celular-ajustes.png", fullPage: true });

  ok(erros.length === 0, "sem erros de JavaScript " + erros.join(" | "));
  await browser.close();
})();
