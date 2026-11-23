// Modo Olhar: a pessoa escolhe frases sem as mãos, de dois jeitos (Ajustes > Como apontar):
//  - "olhos":  o WebGazer estima para onde a pessoa olha (precisa de calibração);
//  - "cabeca": o nariz vira o cursor (mais preciso; serve para quem ainda mexe um pouco a cabeça).
// A grade tem dois níveis: categorias -> frases da categoria (com "Voltar").
// Poucos botões grandes por tela = muito mais fácil de acertar com o olhar.
import { DWELL_MS, CALIB_ESPERA_MS, CALIB_GRAVACAO_MS, CALIB_VALIDACAO_MS } from "./config.js";
import { falar, estaFalando } from "./falar.js";
import { obter, aoMudarAjuste } from "./ajustes.js";
import { aoMudarFrases } from "./frases.js";
import { acionarEmergencia, pararEmergencia, emergenciaAtiva, botaoParar, aoMudarEmergencia, emergenciaHabilitada } from "./emergencia.js";

const $grade = document.getElementById("grade");
const $titulo = document.getElementById("titulo-olhar");
const $calib = document.getElementById("calibracao");
const $calibTexto = document.getElementById("calibracao-texto");
const $ponto = document.getElementById("ponto-olhar");
const $aviso = document.getElementById("aviso-olhar");
const $precisao = document.getElementById("precisao-olhar");

const GRACA_MS = 300;          // o olhar precisa ficar esse tempo num botão novo para "valer" (ignora saltos)
const IMA = 0.25;              // o ponto perto de um botão (fora dele, até 25% do tamanho) conta como nele
const FICA = 0.45;             // depois de escolhido, o botão "segura" o olhar até 45% para fora da borda
const JANELA = { olhos: 10, cabeca: 5 };  // pontos usados na mediana (suavização)

// Calibração dos olhos: 3 x 3 + 4 internos, cobrindo a área da grade (frações da área)
const PONTOS_OLHOS = [[0, 0], [0.5, 0], [1, 0], [0, 0.5], [0.5, 0.5], [1, 0.5], [0, 1], [0.5, 1], [1, 1],
  [0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]];
const PONTOS_TESTE = [[0.3, 0.3], [0.7, 0.3], [0.3, 0.7], [0.7, 0.7]];
// Calibração da cabeça: centro e os quatro extremos
const PONTOS_CABECA = { centro: [0.5, 0.5], direita: [1, 0.5], esquerda: [0, 0.5], baixo: [0.5, 1], cima: [0.5, 0] };

let categorias = [];
let nivel = null;        // null = tela das categorias; número = categoria aberta
let tiles = [];

let iniciado = false;
let iniciando = false;   // begin() em andamento (a pessoa pode aceitar a câmera devagar)
let ativo = false;
let calibrando = false;
let validando = null;    // lista que recebe os pontos durante o teste de precisão
let calibradoPara = null; // "olhos" | "cabeca": para qual modo a calibração atual vale
let pontos = [];
let ultimoPonto = null;  // último ponto suavizado {x, y}
let ultimoDado = 0;      // última vez que chegou um dado da câmera

// seleção por tempo (dwell)
let confirmado = null;   // botão em que o olhar está (já passou da GRACA_MS)
let candidato = null;    // botão para onde o olhar acabou de ir
let candidatoDesde = 0;
let atual = null;        // botão que está enchendo a barra
let inicio = 0;
let quadroAnterior = 0;
let ultimo = null;       // último escolhido: só repete depois de olhar para outro lugar

// cabeça
let mapaCabeca = null;   // { uC, vC, kx, ky, xC, yC }
let amostrasCabeca = null;
let posAnterior = null;

const modo = () => obter("apontar");
const mediana = (v) => {
  const o = [...v].sort((a, b) => a - b);
  const m = o.length >> 1;
  return o.length % 2 ? o[m] : (o[m - 1] + o[m]) / 2;
};
const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- a grade
function botaoGrade(texto, tipo, extra = {}) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = `frase tipo-${tipo}`;
  b.dataset.tipo = tipo;
  Object.assign(b.dataset, extra);
  const barra = document.createElement("span");
  barra.className = "barra";
  b.append(texto, barra);
  b.addEventListener("click", () => selecionar(b)); // o cuidador também pode tocar/clicar
  return b;
}

function montar() {
  limpar();
  const umaSo = categorias.length === 1;
  const botoes = [];
  if (nivel === null && !umaSo) {
    $titulo.textContent = "Escolha uma categoria";
    categorias.forEach((c, i) => botoes.push(botaoGrade(c.nome, "categoria", { indice: i })));
    if (emergenciaHabilitada()) botoes.push(botaoGrade("Emergência", "emergencia"));
  } else {
    const cat = categorias[umaSo ? 0 : nivel] || categorias[0];
    $titulo.textContent = cat.nome;
    if (!umaSo) botoes.push(botaoGrade("← Voltar", "voltar"));
    cat.frases.forEach((f) => botoes.push(botaoGrade(f, "frase", { texto: f })));
    if (umaSo && emergenciaHabilitada()) botoes.push(botaoGrade("Emergência", "emergencia"));
  }
  $grade.replaceChildren(...botoes);
  tiles = botoes;
  ajustarColunas();

  travarEmbaixo();
}

// Quando a tela muda (abriu categoria, voltou, alarme ligou/desligou), o olhar continua
// no mesmo lugar: o botão novo que ficou embaixo dele só pode ser escolhido depois que
// a pessoa olhar para outro lugar. Sem isso, olhar fixo escolheria em cascata.
function travarEmbaixo() {
  limpar();
  const embaixo = ultimoPonto ? escolherAlvo(ultimoPonto.x, ultimoPonto.y) : null;
  confirmado = embaixo;
  ultimo = embaixo;
  candidato = null;
}

function ajustarColunas() {
  const n = tiles.length;
  const estreita = matchMedia("(max-width: 640px)").matches;
  $grade.style.setProperty("--colunas", estreita || n <= 4 ? 2 : 3);
}

function abrir(indice) {
  nivel = indice;
  montar();
}

async function falarFrase(tile) {
  if (estaFalando()) return;
  tile.classList.add("falando");
  try {
    await falar(tile.dataset.texto);
  } finally {
    tile.classList.remove("falando");
  }
}

function selecionar(tile) {
  if (tile === botaoParar()) return pararEmergencia();
  switch (tile.dataset.tipo) {
    case "categoria": return abrir(Number(tile.dataset.indice));
    case "voltar": return abrir(null);
    case "emergencia": return acionarEmergencia();
    default: return falarFrase(tile);
  }
}

// Emergência e "Parar alarme" pedem 50% mais tempo: evita acionar (ou parar) sem querer.
function tempoPara(tile) {
  const base = obter("dwell") || DWELL_MS;
  return tile === botaoParar() || tile.dataset.tipo === "emergencia" ? base * 1.5 : base;
}

// ------------------------------------------------- do ponto ao botão escolhido
const alvos = () => (emergenciaAtiva() ? [botaoParar()] : tiles);

function distanciaAte(x, y, el) {
  const r = el.getBoundingClientRect();
  const dx = Math.max(r.left - x, 0, x - r.right);
  const dy = Math.max(r.top - y, 0, y - r.bottom);
  return { d: Math.hypot(dx, dy), lado: Math.min(r.width, r.height) };
}

// O botão mais perto do ponto, se estiver dentro dele ou "quase" (efeito ímã).
// Botão já em uso segura o olhar com uma margem maior (histerese): o ponto tremendo
// na borda não fica trocando de botão.
function escolherAlvo(x, y) {
  const lista = alvos();
  if (confirmado && lista.includes(confirmado)) {
    const { d, lado } = distanciaAte(x, y, confirmado);
    if (d <= lado * FICA) return confirmado;
  }
  let melhor = null;
  let menor = Infinity;
  for (const el of lista) {
    const { d, lado } = distanciaAte(x, y, el);
    if (d <= lado * IMA && d < menor) { melhor = el; menor = d; }
  }
  return melhor;
}

function limpar() {
  if (atual) {
    atual.classList.remove("olhando");
    atual.style.removeProperty("--p");
  }
  atual = null;
}

// Recebe cada ponto já suavizado (dos olhos ou da cabeça).
function aoPonto(x, y) {
  const agora = performance.now();
  const dt = quadroAnterior ? agora - quadroAnterior : 0;
  quadroAnterior = agora;
  ultimoPonto = { x, y };

  $ponto.style.left = x + "px";
  $ponto.style.top = y + "px";
  $ponto.hidden = !obter("mostrarPonto") && !calibrando;

  if (calibrando) return;
  if (estaFalando() && !emergenciaAtiva()) return limpar();

  const alvo = escolherAlvo(x, y);
  if (alvo !== confirmado) {
    if (candidato !== alvo) { candidato = alvo; candidatoDesde = agora; }
    if (agora - candidatoDesde < GRACA_MS) {
      inicio += dt; // ainda pode ser um salto do ponto: a barra só pausa, não zera
      return;
    }
    confirmado = alvo;
    candidato = null;
    if (confirmado !== ultimo) ultimo = null; // olhou para outro lugar: libera repetir
    limpar();
    if (confirmado && confirmado !== ultimo) {
      atual = confirmado;
      inicio = agora;
      atual.classList.add("olhando");
    }
  } else {
    candidato = null;
  }
  if (!atual) return;

  const progresso = Math.min(1, (agora - inicio) / tempoPara(atual));
  atual.style.setProperty("--p", progresso);
  if (progresso >= 1) {
    const escolhido = atual;
    ultimo = escolhido;
    limpar();
    selecionar(escolhido);
  }
}

function suavizar(x, y) {
  pontos.push({ x, y });
  const n = JANELA[modo()] || 8;
  while (pontos.length > n) pontos.shift();
  aoPonto(mediana(pontos.map((p) => p.x)), mediana(pontos.map((p) => p.y)));
}

// ------------------------------------------------------------- olhos (WebGazer)
function aoOlhar(dado) {
  if (!ativo || !dado || modo() !== "olhos") return;
  ultimoDado = performance.now();
  if (validando) validando.push(dado);
  if (calibradoPara !== "olhos") return;
  suavizar(dado.x, dado.y);
}

// Área que a calibração cobre: a da grade, um pouco maior (é onde a pessoa vai olhar).
function areaDaGrade() {
  const r = $grade.getBoundingClientRect();
  return {
    x0: Math.max(32, r.left - r.width * 0.1),
    x1: Math.min(innerWidth - 32, r.right + r.width * 0.1),
    y0: Math.max(32, r.top - r.height * 0.1),
    y1: Math.min(innerHeight - 32, r.bottom + r.height * 0.1),
  };
}

function criarAlvo() {
  $calib.querySelectorAll(".pt-auto").forEach((p) => p.remove());
  const $alvo = document.createElement("div");
  $alvo.className = "pt-auto";
  $alvo.setAttribute("aria-hidden", "true");
  $calib.append($alvo);
  return $alvo;
}

function moverAlvo($alvo, area, [fx, fy]) {
  const x = area.x0 + fx * (area.x1 - area.x0);
  const y = area.y0 + fy * (area.y1 - area.y0);
  $alvo.style.left = x + "px";
  $alvo.style.top = y + "px";
  return { x, y };
}

async function calibrarOlhos() {
  webgazer.clearData();
  $calibTexto.textContent = "Olhe para o ponto azul enquanto ele se move. Tente não mexer a cabeça.";
  const area = areaDaGrade();
  const $alvo = criarAlvo();

  for (const p of PONTOS_OLHOS) {
    if (!ativo) return false;
    const { x, y } = moverAlvo($alvo, area, p);
    await esperar(CALIB_ESPERA_MS);                 // o olhar chega no ponto
    for (let t = 0; t < CALIB_GRAVACAO_MS && ativo; t += 100) {
      webgazer.recordScreenPosition(x, y, "click"); // grava com o olhar parado nele
      await esperar(100);
    }
  }

  // Teste de precisão: o ponto passa por 4 lugares e o app mede o erro (sem treinar).
  $calibTexto.textContent = "Agora só um teste: continue olhando para o ponto.";
  $alvo.classList.add("teste");
  const erros = [];
  for (const p of PONTOS_TESTE) {
    if (!ativo) return false;
    const { x, y } = moverAlvo($alvo, area, p);
    await esperar(CALIB_ESPERA_MS);
    validando = [];
    await esperar(CALIB_VALIDACAO_MS);
    const vistos = validando;
    validando = null;
    if (vistos.length >= 3) {
      erros.push(Math.hypot(mediana(vistos.map((d) => d.x)) - x, mediana(vistos.map((d) => d.y)) - y));
    }
  }
  mostrarPrecisao(erros);
  return true;
}

function mostrarPrecisao(erros) {
  if (!erros.length) {
    $precisao.textContent = "Não consegui medir a precisão: a câmera não achou o rosto. Recalibre.";
    $precisao.dataset.nivel = "baixa";
    return;
  }
  const erro = mediana(erros);
  const lado = Math.min(...tiles.map((t) => Math.min(t.offsetWidth, t.offsetHeight)));
  const relativo = erro / lado;
  const nivelPrec = relativo < 0.35 ? "boa" : relativo < 0.6 ? "razoavel" : "baixa";
  const textos = {
    boa: "Precisão boa.",
    razoavel: "Precisão razoável. Se errar, aumente o tempo de olhar em Ajustes.",
    baixa: "Precisão baixa. Melhore a luz no rosto e recalibre, ou use \"Apontar com a cabeça\" em Ajustes.",
  };
  $precisao.textContent = `${textos[nivelPrec]} (erro de cerca de ${Math.round(erro)} px)`;
  $precisao.dataset.nivel = nivelPrec;
}

// ------------------------------------------------------- cabeça (nariz = cursor)
const xy = (p) => (Array.isArray(p) ? { x: p[0], y: p[1] } : p);

// Posição do nariz em relação ao rosto (não muda se a pessoa só se afastar ou
// se deslocar; muda quando ela vira o rosto). Pontos do MediaPipe Face Mesh:
// 1 = ponta do nariz, 234/454 = laterais do rosto, 10 = testa, 152 = queixo.
function relativoAoRosto(pos) {
  if (!pos || pos.length < 455) return null;
  const nariz = xy(pos[1]), esq = xy(pos[234]), dir = xy(pos[454]), testa = xy(pos[10]), queixo = xy(pos[152]);
  const largura = Math.hypot(dir.x - esq.x, dir.y - esq.y);
  const altura = Math.hypot(queixo.x - testa.x, queixo.y - testa.y);
  if (!largura || !altura) return null;
  return { u: (nariz.x - (esq.x + dir.x) / 2) / largura, v: (nariz.y - (testa.y + queixo.y) / 2) / altura };
}

function cicloCabeca() {
  if (!ativo || modo() !== "cabeca") return;
  requestAnimationFrame(cicloCabeca);
  let pos = null;
  try { pos = webgazer.getTracker().getPositions(); } catch { return; }
  if (!pos || pos === posAnterior) return; // nenhum quadro novo (ou rosto perdido)
  posAnterior = pos;
  const rel = relativoAoRosto(pos);
  if (!rel) return;
  ultimoDado = performance.now();
  if (amostrasCabeca) { amostrasCabeca.push(rel); return; }
  if (!mapaCabeca || calibradoPara !== "cabeca") return;

  const s = (obter("sensibilidade") || 100) / 100;
  const m = mapaCabeca;
  const x = Math.min(innerWidth, Math.max(0, m.xC + (rel.u - m.uC) * m.kx * s));
  const y = Math.min(innerHeight, Math.max(0, m.yC + (rel.v - m.vC) * m.ky * s));
  suavizar(x, y);
}

// A pessoa aponta o nariz para 5 pontos. Com isso o app descobre, para ESSA pessoa,
// quanto ela consegue virar o rosto e em que sentido (não precisa adivinhar ganho nem espelho).
async function calibrarCabeca() {
  $calibTexto.textContent = "Vire o rosto devagar e aponte o nariz para o ponto azul.";
  const area = areaDaGrade();
  const $alvo = criarAlvo();
  const medido = {};
  for (const [nome, p] of Object.entries(PONTOS_CABECA)) {
    if (!ativo) return false;
    const alvo = moverAlvo($alvo, area, p);
    await esperar(1100); // a cabeça é mais lenta que os olhos
    amostrasCabeca = [];
    await esperar(900);
    const am = amostrasCabeca;
    amostrasCabeca = null;
    if (am.length < 3) {
      $precisao.textContent = "A câmera não achou o rosto. Ajuste a luz e recalibre.";
      $precisao.dataset.nivel = "baixa";
      return false;
    }
    medido[nome] = { ...alvo, u: mediana(am.map((a) => a.u)), v: mediana(am.map((a) => a.v)) };
  }

  const { centro, direita, esquerda, baixo, cima } = medido;
  const du = direita.u - esquerda.u;
  const dv = baixo.v - cima.v;
  const pouco = Math.abs(du) < 0.03 || Math.abs(dv) < 0.02;
  mapaCabeca = {
    uC: centro.u, vC: centro.v, xC: centro.x, yC: centro.y,
    // se a pessoa quase não virou, usa um ganho padrão (o sinal vem da medição)
    kx: Math.abs(du) >= 0.03 ? (direita.x - esquerda.x) / du : -(area.x1 - area.x0) / 0.2,
    ky: Math.abs(dv) >= 0.02 ? (baixo.y - cima.y) / dv : (area.y1 - area.y0) / 0.15,
  };
  $precisao.textContent = pouco
    ? "Pronto. O movimento foi pequeno: se o ponto não alcançar as bordas, aumente a sensibilidade em Ajustes."
    : "Pronto. Mova o rosto para levar o ponto até a frase.";
  $precisao.dataset.nivel = pouco ? "razoavel" : "boa";
  return true;
}

// ------------------------------------------------------------------ calibração
async function calibrar() {
  if (calibrando || !iniciado) return;
  calibrando = true;
  pontos = [];
  limpar();
  $precisao.textContent = "";
  $calib.hidden = false;
  const qual = modo();
  let deuCerto = false;
  try {
    deuCerto = qual === "cabeca" ? await calibrarCabeca() : await calibrarOlhos();
  } finally {
    $calib.querySelectorAll(".pt-auto").forEach((p) => p.remove());
    $calib.hidden = true;
    calibrando = false;
    validando = null;
    amostrasCabeca = null;
  }
  if (deuCerto) calibradoPara = qual;
}

// ------------------------------------------------------------------- liga/desliga
export function iniciarOlhar() {
  aoMudarFrases((cats) => {
    categorias = cats;
    if (nivel !== null && nivel >= cats.length) nivel = null;
    montar();
  });
  document.getElementById("btn-recalibrar").addEventListener("click", calibrar);
  addEventListener("resize", ajustarColunas);
  // alarme ligou ou desligou: o olhar parado não pode desligar o alarme que acabou de ligar
  aoMudarEmergencia(() => travarEmbaixo());
  aoMudarAjuste((chave) => {
    if (chave === "mostrarPonto") $ponto.hidden = !obter("mostrarPonto");
    if (chave === "emergencia") montar();
  });

  // Avisa quando a câmera perde o rosto
  setInterval(() => {
    if (!ativo || !iniciado || calibrando) return;
    const perdeu = performance.now() - ultimoDado > 3000;
    $aviso.textContent = perdeu ? "Não encontro o rosto. Ajuste a luz e a posição." : "";
  }, 1000);
}

function carregarWebGazer() {
  if (window.webgazer) return Promise.resolve();
  return new Promise((ok, erro) => {
    const script = document.createElement("script");
    script.src = "https://webgazer.cs.brown.edu/webgazer.js";
    script.onload = ok;
    script.onerror = () => erro(new Error("WebGazer não carregou"));
    document.head.append(script);
  });
}

// A câmera só liga quando a pessoa abre o modo Olhar.
export function ativar() {
  ativo = true;
  ultimoDado = performance.now();
  pontos = [];
  const comecar = () => {
    if (modo() === "cabeca") requestAnimationFrame(cicloCabeca);
    if (calibradoPara !== modo()) calibrar(); // trocou olhos/cabeça em Ajustes: calibra de novo
  };

  if (iniciando) return; // a primeira abertura ainda está esperando a câmera
  if (!iniciado) {
    iniciando = true;
        carregarWebGazer()
      .then(() => {
        webgazer.saveDataAcrossSessions(false); // não reaproveita calibração antiga
        webgazer.setRegression("ridge");
        webgazer.applyKalmanFilter(true);
        webgazer.showPredictionPoints(false);
        webgazer.setGazeListener(aoOlhar);
        return webgazer.begin();
      })
      .then(() => {
        iniciado = true;
        // O WebGazer aprende com o mouse por padrão. Aqui quem mexe o mouse é o cuidador,
        // não o olhar do paciente: isso estragava a calibração.
        webgazer.removeMouseEventListeners();
        return esperar(500);
      })
      .then(() => { if (ativo) comecar(); else desativar(); })
      .catch(() => {
        $aviso.textContent = "Não foi possível abrir a câmera. Verifique a permissão do navegador.";
      })
      .finally(() => { iniciando = false; });
  } else {
    webgazer.resume();
    webgazer.showVideoPreview(true);
    comecar();
  }
}

export function desativar() {
  ativo = false;
  if (iniciado) {
    webgazer.pause();
    webgazer.showVideoPreview(false);
  }
  $ponto.hidden = true;
  limpar();
}

// Ao sair da conta, a grade volta para as categorias.
export function voltarAoInicio() {
  nivel = null;
  montar();
}
