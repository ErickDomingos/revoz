// Botão de emergência: alarme alto + a frase de socorro, repetidos até alguém parar.
// Tudo acontece no aparelho (Web Audio e o áudio já guardado), então funciona
// mesmo com o servidor fora do ar. O servidor só registra que houve o alarme.
import { EMERGENCIA_TEXTO } from "./config.js";
import { audioEmCache, gerarAudio, registrarEmergencia } from "./api.js";
import { obter, aoMudarAjuste } from "./ajustes.js";

const $tela = document.getElementById("emergencia");
const $hora = document.getElementById("emergencia-hora");
const $parar = document.getElementById("btn-parar-emergencia");

let ativa = false;
let contexto = null;  // AudioContext do alarme
let tocando = null;   // áudio da frase em andamento
const ouvintes = [];

// O modo Olhar escuta para trocar os alvos (grade <-> botão "Parar alarme").
export const aoMudarEmergencia = (f) => ouvintes.push(f);
const avisar = () => ouvintes.forEach((f) => f(ativa));

export const emergenciaAtiva = () => ativa;
export const botaoParar = () => $parar;

const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

// Sirene: duas notas alternadas, como as de ambulância (cerca de 2,4 s).
async function sirene() {
  contexto ??= new AudioContext();
  if (contexto.state === "suspended") await contexto.resume().catch(() => {});
  const osc = contexto.createOscillator();
  const volume = contexto.createGain();
  osc.type = "square";
  const t0 = contexto.currentTime;
  for (let i = 0; i < 6; i++) osc.frequency.setValueAtTime(i % 2 ? 660 : 880, t0 + i * 0.4);
  volume.gain.setValueAtTime(0.25, t0);
  volume.gain.setValueAtTime(0, t0 + 2.4);
  osc.connect(volume).connect(contexto.destination);
  osc.start(t0);
  osc.stop(t0 + 2.4);
  await esperar(2500);
}

function falarNavegador(texto) {
  return new Promise((ok) => {
    if (!("speechSynthesis" in window)) return ok();
    const fala = new SpeechSynthesisUtterance(texto);
    fala.lang = "pt-BR";
    fala.rate = 0.95;
    fala.onend = ok;
    fala.onerror = ok;
    speechSynthesis.speak(fala);
  });
}

// Usa a voz da pessoa se o áudio já estiver pronto; senão, a voz do navegador (na hora).
function falarSocorro() {
  const pronto = audioEmCache(EMERGENCIA_TEXTO);
  if (!pronto) return falarNavegador(EMERGENCIA_TEXTO);
  return new Promise((ok) => {
    tocando = new Audio(pronto.url);
    tocando.volume = 1;
    tocando.onended = ok;
    tocando.onerror = () => falarNavegador(EMERGENCIA_TEXTO).then(ok);
    tocando.play().catch(() => falarNavegador(EMERGENCIA_TEXTO).then(ok));
  });
}

async function repetir() {
  while (ativa) {
    await sirene();
    if (!ativa) break;
    await falarSocorro();
    await esperar(300);
  }
}

export function acionarEmergencia() {
  if (ativa) return;
  ativa = true;
  $hora.textContent = `Acionado às ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
  $tela.hidden = false;
  $parar.focus();
  navigator.vibrate?.([400, 200, 400, 200, 400]);
  registrarEmergencia();
  avisar();
  repetir();
}

export function pararEmergencia() {
  if (!ativa) return;
  ativa = false;
  $tela.hidden = true;
  if (tocando) { tocando.pause(); tocando = null; }
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  navigator.vibrate?.(0);
  avisar();
}

// Gera antes o áudio da frase de socorro com a voz em uso, para tocar sem esperar.
export function prepararEmergencia() {
  gerarAudio(EMERGENCIA_TEXTO).catch(() => {});
}

// Ajustes > Botão de emergência: quando desligado, o botão some do topo e da grade do Olhar.
export const emergenciaHabilitada = () => obter("emergencia") !== false;

export function iniciarEmergencia() {
  const $botao = document.getElementById("btn-emergencia");
  $botao.addEventListener("click", acionarEmergencia);
  const mostrar = () => { $botao.hidden = !emergenciaHabilitada(); };
  mostrar();
  aoMudarAjuste((chave) => { if (chave === "emergencia") mostrar(); });
  $parar.addEventListener("click", pararEmergencia);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && ativa) pararEmergencia(); });
}
