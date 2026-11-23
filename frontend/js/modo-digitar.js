import { falar } from "./falar.js";
import { listarRecentes, limparRecentes } from "./api.js";
import { aoMudarFrases } from "./frases.js";

const $recentes = document.getElementById("recentes");
const $lista = document.getElementById("lista-recentes");

// Fase 6: as frases recentes ficam na conta (GET /historico), não no navegador.
export async function atualizarRecentes() {
  let frases = [];
  try {
    frases = await listarRecentes(8);
  } catch {
    /* sem login ou servidor fora: só esconde a lista */
  }
  $lista.replaceChildren(...frases.map((texto) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = texto;
    chip.addEventListener("click", () => falarEAnotar(texto));
    return chip;
  }));
  $recentes.hidden = frases.length === 0;
}

export function esconderRecentes() {
  $lista.replaceChildren();
  $recentes.hidden = true;
}

async function falarEAnotar(texto) {
  if (await falar(texto, { historico: true })) atualizarRecentes();
}

// ---------- Frases prontas por categoria (um toque fala) ----------
const $cats = document.getElementById("prontas-categorias");
const $prontas = document.getElementById("prontas-frases");
let categorias = [];
let aberta = 0;

function chip(texto, aoClicar, classe = "chip") {
  const b = document.createElement("button");
  b.type = "button";
  b.className = classe;
  b.textContent = texto;
  b.addEventListener("click", aoClicar);
  return b;
}

function mostrarProntas() {
  $cats.replaceChildren(...categorias.map((c, i) => {
    const b = chip(c.nome, () => { aberta = i; mostrarProntas(); }, "chip categoria");
    b.setAttribute("aria-pressed", i === aberta);
    return b;
  }));
  const cat = categorias[aberta] || categorias[0];
  $prontas.replaceChildren(...(cat ? cat.frases : []).map((f) => chip(f, () => falar(f))));
}

export function iniciarDigitar() {
  aoMudarFrases((cats) => {
    categorias = cats;
    if (aberta >= cats.length) aberta = 0;
    mostrarProntas();
  });

  const campo = document.getElementById("campo-texto");
  const enviar = () => falarEAnotar(campo.value);

  document.getElementById("btn-falar").addEventListener("click", enviar);
  campo.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault(); // Shift+Enter quebra linha
      enviar();
    }
  });

  document.getElementById("btn-limpar-recentes").addEventListener("click", async () => {
    try {
      await limparRecentes();
    } catch { /* a lista some de qualquer jeito na próxima atualização */ }
    atualizarRecentes();
  });
}
