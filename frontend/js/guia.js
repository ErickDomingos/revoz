// Aba Guia: passo a passo do app, com a situação de cada passo da conta que entrou.
import { statusConsentimento, listarVozes, vozesGenericas } from "./api.js";
import { ehPadrao } from "./frases.js";

const passo = (nome) => document.querySelector(`#painel-guia .passo[data-passo="${nome}"]`);

function marcar(nome, feito, texto) {
  const el = passo(nome);
  if (!el) return;
  el.classList.toggle("feito", feito);
  el.querySelector(".situacao").textContent = texto ?? (feito ? "Feito" : "Pendente");
}

let usuario = null;

export async function atualizarGuia() {
  marcar("conta", Boolean(usuario), usuario ? `Feito: ${usuario.email}` : "Pendente");
  if (!usuario) {
    ["generica", "frases", "consentimento", "clonada"].forEach((n) => marcar(n, false, ""));
    return;
  }
  // cada consulta é independente: se uma falhar, as outras ainda aparecem
  const [consent, vozes, gen] = await Promise.allSettled([
    statusConsentimento(), listarVozes(), vozesGenericas(),
  ]);
  if (gen.status === "fulfilled") marcar("generica", true, `Em uso: ${gen.value.escolhida}`);
  marcar("frases", !ehPadrao(), ehPadrao() ? "Usando as frases padrão" : "Feito");
  if (consent.status === "fulfilled") marcar("consentimento", consent.value.valido);
  if (vozes.status === "fulfilled") {
    const ativa = vozes.value.find((v) => v.ativa);
    marcar("clonada", Boolean(ativa), ativa ? `Em uso: ${ativa.nome}` : vozes.value.length ? "Voz pronta, falta usar" : "Pendente");
  }
}

export function guiaAoEntrar(u) {
  usuario = u;
}

export function guiaAoSair() {
  usuario = null;
  atualizarGuia();
}
