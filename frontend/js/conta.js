// Frases prontas por categoria (guardadas na conta), "baixar meus dados" e "excluir minha conta".
import { obterCategorias, salvarCategorias, baixarMeusDados, excluirConta } from "./api.js";
import { definirCategorias, obterCategorias as categoriasAtuais } from "./frases.js";
import { CATEGORIAS, MAX_CATEGORIAS, MAX_POR_CATEGORIA } from "./config.js";

const $ = (id) => document.getElementById(id);
const $editor = $("editor-categorias");

// ---------- Editor de categorias ----------
function botaoPequeno(texto, rotulo, aoClicar, classe = "secundario") {
  const b = document.createElement("button");
  b.type = "button";
  b.className = classe;
  b.textContent = texto;
  b.setAttribute("aria-label", rotulo);
  b.addEventListener("click", aoClicar);
  return b;
}

function cartaoCategoria(cat = { nome: "", frases: [] }) {
  const cartao = document.createElement("div");
  cartao.className = "cat-editor";
  const nome = Object.assign(document.createElement("input"), {
    type: "text", className: "cat-nome", maxLength: 40, value: cat.nome, placeholder: "Nome da categoria",
  });
  nome.setAttribute("aria-label", "Nome da categoria");
  const frases = Object.assign(document.createElement("textarea"), {
    className: "cat-frases", rows: 4, value: cat.frases.join("\n"), placeholder: "Uma frase por linha",
  });
  const rotular = () => frases.setAttribute("aria-label", `Frases de ${nome.value || "nova categoria"}, uma por linha`);
  nome.addEventListener("input", rotular);
  rotular();

  const mover = (passo) => {
    const irma = passo < 0 ? cartao.previousElementSibling : cartao.nextElementSibling;
    if (!irma) return;
    passo < 0 ? irma.before(cartao) : irma.after(cartao);
    nome.focus();
  };
  const acoes = document.createElement("div");
  acoes.className = "cat-acoes";
  acoes.append(
    botaoPequeno("↑", "Subir categoria", () => mover(-1)),
    botaoPequeno("↓", "Descer categoria", () => mover(1)),
    botaoPequeno("Remover", "Remover categoria", () => cartao.remove(), "secundario perigo"),
  );
  const topo = document.createElement("div");
  topo.className = "cat-topo";
  topo.append(nome, acoes);
  cartao.append(topo, frases);
  return cartao;
}

function preencherEditor(cats) {
  $editor.replaceChildren(...cats.map(cartaoCategoria));
}

function lerEditor() {
  return [...$editor.querySelectorAll(".cat-editor")].map((c) => ({
    nome: c.querySelector(".cat-nome").value.trim(),
    frases: c.querySelector(".cat-frases").value.split("\n").map((f) => f.trim()).filter(Boolean),
  })).filter((c) => c.nome || c.frases.length);
}

function problema(cats) {
  if (!cats.length) return "Crie pelo menos uma categoria com uma frase.";
  if (cats.length > MAX_CATEGORIAS) return `Use no máximo ${MAX_CATEGORIAS} categorias.`;
  for (const c of cats) {
    if (!c.nome) return "Dê um nome para cada categoria.";
    if (!c.frases.length) return `A categoria "${c.nome}" está sem frases.`;
    if (c.frases.length > MAX_POR_CATEGORIA) return `"${c.nome}" tem mais de ${MAX_POR_CATEGORIA} frases. Divida em duas categorias.`;
  }
  if (new Set(cats.map((c) => c.nome.toLowerCase())).size !== cats.length) return "Há duas categorias com o mesmo nome.";
  return null;
}

function aplicar(cats) {
  definirCategorias(cats);
  preencherEditor(categoriasAtuais());
}

// Chamada depois do login: carrega as frases da conta para as grades e para o editor.
export async function contaAoEntrar() {
  $("frases-msg").textContent = "";
  $("conta-msg").textContent = "";
  try {
    aplicar(await obterCategorias());
  } catch {
    aplicar(CATEGORIAS); // servidor fora: usa o padrão do config.js
  }
}

// Ao sair: volta para as frases padrão e esconde a confirmação de exclusão.
export function contaAoSair() {
  aplicar(CATEGORIAS);
  $("form-excluir").hidden = true;
  $("excluir-senha").value = "";
}

async function salvar() {
  const $msg = $("frases-msg");
  const cats = lerEditor();
  const erro = problema(cats);
  if (erro) { $msg.textContent = erro; return; }
  $("btn-salvar-frases").disabled = true;
  try {
    aplicar(await salvarCategorias(cats));
    $msg.textContent = "Frases salvas.";
  } catch (e) {
    $msg.textContent = `Não foi possível salvar: ${e.message}`;
  } finally {
    $("btn-salvar-frases").disabled = false;
  }
}

async function baixar() {
  const $msg = $("conta-msg");
  try {
    const blob = await baixarMeusDados();
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: "meus-dados-appvoice.json" });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    $msg.textContent = "Arquivo com os seus dados baixado.";
  } catch (erro) {
    $msg.textContent = `Não foi possível baixar: ${erro.message}`;
  }
}

// aoExcluir() é chamada depois que a conta foi apagada (o app volta para a tela de login).
export function iniciarConta(aoExcluir) {
  $("btn-salvar-frases").addEventListener("click", salvar);
  $("btn-nova-categoria").addEventListener("click", () => {
    if ($editor.children.length >= MAX_CATEGORIAS) {
      $("frases-msg").textContent = `Use no máximo ${MAX_CATEGORIAS} categorias.`;
      return;
    }
    const novo = cartaoCategoria();
    $editor.append(novo);
    novo.querySelector(".cat-nome").focus();
  });
  $("btn-frases-padrao").addEventListener("click", () => {
    preencherEditor(CATEGORIAS);
    $("frases-msg").textContent = "Frases padrão no editor. Toque em Salvar frases para usar.";
  });
  $("btn-baixar-dados").addEventListener("click", baixar);

  $("btn-excluir-conta").addEventListener("click", () => {
    $("form-excluir").hidden = false;
    $("excluir-senha").focus();
  });
  $("btn-cancelar-exclusao").addEventListener("click", () => {
    $("form-excluir").hidden = true;
    $("excluir-senha").value = "";
  });

  $("form-excluir").addEventListener("submit", async (e) => {
    e.preventDefault();
    const $msg = $("conta-msg");
    const senha = $("excluir-senha").value;
    if (!senha) { $msg.textContent = "Digite a sua senha para confirmar."; return; }
    try {
      await excluirConta(senha);
      contaAoSair();
      $msg.textContent = "";
      aoExcluir();
    } catch (erro) {
      $msg.textContent = erro.message; // ex.: "Senha incorreta."
    } finally {
      $("excluir-senha").value = "";
    }
  });

  preencherEditor(CATEGORIAS); // as grades já começam com o padrão (frases.js)
}
