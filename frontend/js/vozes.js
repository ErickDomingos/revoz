import { listarVozes, vozesGenericas, definirVozAtiva, preGerar } from "./api.js";
import { falar } from "./falar.js";
import { PREGERAR_FRASES } from "./config.js";
import { todasFrases } from "./frases.js";
import { prepararEmergencia } from "./emergencia.js";

const FRASE_TESTE = "Olá, esta é a minha voz.";
// Vozes genéricas: id null (nenhuma voz clonada), generica diz qual delas.
const GENERICAS_PADRAO = [
  { id: null, generica: "feminina", nome: "Voz genérica feminina", disponivel: true },
  { id: null, generica: "masculina", nome: "Voz genérica masculina", disponivel: true },
];

const $lista = document.getElementById("lista-vozes");
const $aviso = document.getElementById("vozes-aviso");

let catalogo = [];                 // vozes clonadas do usuário (cada uma com "ativa" e "base")
let genericas = GENERICAS_PADRAO;  // vindas de GET /vozes/generica
let genericaEscolhida = "feminina";

function botao(texto, classe, aoClicar) {
  const b = document.createElement("button");
  b.className = classe;
  b.textContent = texto;
  b.addEventListener("click", aoClicar);
  return b;
}

async function usar(voz) {
  $aviso.hidden = true;
  try {
    await definirVozAtiva(voz.id, voz.generica ?? null); // a escolha fica na conta
    await atualizarVozes();
    prepararEmergencia(); // a frase de socorro já fica pronta com a nova voz
    if (PREGERAR_FRASES) preGerar(todasFrases()); // gera as frases prontas com a nova voz
  } catch (erro) {
    $aviso.textContent = `Não foi possível trocar a voz: ${erro.message}`;
    $aviso.hidden = false;
  }
}

function detalhe(voz) {
  if (voz.generica) {
    return voz.disponivel ? "Voz sintética" : "Indisponível no servidor agora: sai a voz feminina";
  }
  const base = voz.base ? ` · convertida da voz ${voz.base}` : "";
  return `Voz clonada · ${voz.detalhe || "Pronta"}${base}`;
}

function cartao(voz, emUso) {
  const art = document.createElement("article");
  art.className = "cartao-voz" + (emUso ? " ativa" : "");

  const info = document.createElement("div");
  const nome = document.createElement("strong");
  nome.textContent = voz.nome;
  const sub = document.createElement("span");
  sub.className = "ajuda";
  sub.textContent = emUso ? "Em uso" : detalhe(voz);
  info.append(nome, sub);

  const acoes = document.createElement("div");
  acoes.className = "acoes";
  // Ouvir: testa essa voz sem trocar a que está em uso
  const opcoes = voz.id ? { voiceId: voz.id } : { generica: true, base: voz.generica };
  acoes.append(botao("Ouvir", "secundario", () => falar(FRASE_TESTE, opcoes)));

  if (emUso) {
    const b = botao("Em uso", "secundario em-uso", () => {});
    b.disabled = true;
    acoes.append(b);
  } else {
    acoes.append(botao("Usar", "secundario", () => usar(voz)));
  }

  art.append(info, acoes);
  return art;
}

function desenhar() {
  const clonadaAtiva = catalogo.find((v) => v.ativa)?.id ?? null;
  const itens = [
    ...genericas.map((g) => [g, !clonadaAtiva && g.generica === genericaEscolhida]),
    ...catalogo.map((v) => [v, v.id === clonadaAtiva]),
  ];
  $lista.replaceChildren(...itens.map(([v, emUso]) => cartao(v, emUso)));
}

export async function atualizarVozes() {
  $aviso.hidden = true;
  try {
    const [vozes, gen] = await Promise.all([listarVozes(), vozesGenericas()]);
    catalogo = vozes;
    genericaEscolhida = gen.escolhida;
    genericas = gen.opcoes.map((o) => ({ id: null, generica: o.id, nome: o.nome, disponivel: o.disponivel }));
  } catch (erro) {
    console.error("Catálogo de vozes indisponível:", erro);
    catalogo = [];
    $aviso.textContent = "Catálogo de vozes indisponível no momento. Você ainda pode usar a voz genérica.";
    $aviso.hidden = false;
  }
  desenhar();
}

// Ao sair da conta, esquece as vozes da conta anterior.
export function limparVozes() {
  catalogo = [];
  genericas = GENERICAS_PADRAO;
  genericaEscolhida = "feminina";
  desenhar();
}

export function iniciarVozes() {
  document.getElementById("btn-atualizar-vozes").addEventListener("click", atualizarVozes);
  desenhar();
}
