import { DWELL_MS } from "./config.js";

// apontar: "olhos" (WebGazer) ou "cabeca" (o nariz vira o cursor). sensibilidade: % do movimento da cabeça.
// emergencia: mostra o botão de emergência (vem ligado: quem mais precisa pode não conseguir ligar sozinho).
// tema: "revoz" (grafite e verde) ou "classico" (azul).
// texto: tamanho das letras do app todo. velocidade: velocidade da fala (o tom não muda).
const PADROES = {
  dwell: DWELL_MS, mostrarPonto: true, apontar: "olhos", sensibilidade: 100, emergencia: true, tema: "revoz",
  texto: "normal", velocidade: 1,
};
const PREFIXO = "ajuste:";
const ouvintes = [];

export function obter(chave) {
  try {
    const salvo = localStorage.getItem(PREFIXO + chave);
    if (salvo !== null) return JSON.parse(salvo);
  } catch { /* sem armazenamento: usa o padrão */ }
  return PADROES[chave];
}

function definir(chave, valor) {
  try {
    localStorage.setItem(PREFIXO + chave, JSON.stringify(valor));
  } catch { /* vale só nesta sessão */ }
  ouvintes.forEach((f) => f(chave, valor));
}

// O modo Olhar escuta as mudanças (trocar olhos/cabeça, esconder o ponto) sem recarregar.
export function aoMudarAjuste(funcao) {
  ouvintes.push(funcao);
}

const emSegundos = (ms) => (ms / 1000).toFixed(1).replace(".", ",") + " s";

export function iniciarAjustes() {
  const $dwell = document.getElementById("ajuste-dwell");
  const $saida = document.getElementById("saida-dwell");
  const $ponto = document.getElementById("ajuste-ponto");
  const $sens = document.getElementById("ajuste-sensibilidade");
  const $saidaSens = document.getElementById("saida-sensibilidade");
  const $grupoSens = document.getElementById("grupo-sensibilidade");

  $dwell.value = obter("dwell");
  $saida.textContent = emSegundos(Number($dwell.value));
  $dwell.addEventListener("input", () => {
    const ms = Number($dwell.value);
    definir("dwell", ms);
    $saida.textContent = emSegundos(ms);
  });

  $ponto.checked = obter("mostrarPonto");
  $ponto.addEventListener("change", () => definir("mostrarPonto", $ponto.checked));

  const $emerg = document.getElementById("ajuste-emergencia");
  $emerg.checked = obter("emergencia");
  $emerg.addEventListener("change", () => definir("emergencia", $emerg.checked));

  document.querySelectorAll('input[name="ajuste-tema"]').forEach((r) => {
    r.checked = r.value === obter("tema");
    r.addEventListener("change", () => {
      if (!r.checked) return;
      definir("tema", r.value);
      document.documentElement.dataset.tema = r.value;
    });
  });

  document.querySelectorAll('input[name="ajuste-texto"]').forEach((r) => {
    r.checked = r.value === obter("texto");
    r.addEventListener("change", () => {
      if (!r.checked) return;
      definir("texto", r.value);
      document.documentElement.dataset.texto = r.value;
    });
  });

  document.querySelectorAll('input[name="ajuste-velocidade"]').forEach((r) => {
    r.checked = Number(r.value) === Number(obter("velocidade"));
    r.addEventListener("change", () => { if (r.checked) definir("velocidade", Number(r.value)); });
  });

  const radios = [...document.querySelectorAll('input[name="ajuste-apontar"]')];
  const mostrarSens = () => { $grupoSens.hidden = obter("apontar") !== "cabeca"; };
  radios.forEach((r) => {
    r.checked = r.value === obter("apontar");
    r.addEventListener("change", () => { if (r.checked) { definir("apontar", r.value); mostrarSens(); } });
  });
  mostrarSens();

  $sens.value = obter("sensibilidade");
  $saidaSens.textContent = `${$sens.value}%`;
  $sens.addEventListener("input", () => {
    definir("sensibilidade", Number($sens.value));
    $saidaSens.textContent = `${$sens.value}%`;
  });
}
