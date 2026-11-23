// Quem está usando o app: nome, iniciais e foto-de-letras no topo e na aba Conta.
import { editarNome } from "./api.js";

const $ = (id) => document.getElementById(id);
let atual = null;
let aoAbrirConta = () => {};

const palavras = (nome) => (nome || "").trim().split(/\s+/).filter(Boolean);

// "Erick Domingos" -> "ED"; "Leonardo" -> "L"; sem nome -> as 2 primeiras letras do e-mail
export function iniciais(u) {
  const p = palavras(u?.nome);
  if (p.length >= 2) return (p[0][0] + p[p.length - 1][0]).toUpperCase();
  if (p.length === 1) return p[0][0].toUpperCase();
  return (u?.email || "?").slice(0, 2).toUpperCase();
}

export const primeiroNome = (u) => palavras(u?.nome)[0] || (u?.email || "").split("@")[0];

export function mostrarIdentidade(u) {
  atual = u;
  const temNome = palavras(u.nome).length > 0;
  const papel = u.papel === "cuidador" ? "Conta de responsável" : "Conta de usuário";

  // topo: sempre à vista, para saber de quem é a sessão
  const $perfil = $("btn-perfil");
  $perfil.hidden = false;
  $perfil.querySelector(".avatar").textContent = iniciais(u);
  $perfil.querySelector(".perfil-nome").textContent = primeiroNome(u);
  $perfil.setAttribute("aria-label", `Conta de ${temNome ? u.nome : u.email}. Abrir a aba Conta`);
  $perfil.title = `${temNome ? u.nome : u.email} (${papel.toLowerCase()})`;

  // aba Conta
  $("conta-avatar").textContent = iniciais(u);
  $("info-nome").textContent = temNome ? u.nome : "Sem nome";
  $("info-nome").classList.toggle("vazio", !temNome);
  $("info-conta").textContent = u.email;
  $("info-papel").textContent = papel;
  $("btn-editar-nome").textContent = temNome ? "Editar nome" : "Adicionar nome";
  $("nome-msg").textContent = temNome ? "" : "Adicione o seu nome: ele aparece no topo do app e para os responsáveis vinculados.";

  // boas-vindas
  $("bv-titulo").textContent = temNome ? `Bem-vindo ao Revoz, ${primeiroNome(u)}` : "Bem-vindo ao Revoz";
}

export function esconderIdentidade() {
  atual = null;
  $("btn-perfil").hidden = true;
  $("form-nome").hidden = true;
}

export function iniciarIdentidade(abrirConta) {
  aoAbrirConta = abrirConta;
  $("btn-perfil").addEventListener("click", () => aoAbrirConta());

  const $form = $("form-nome");
  const $campo = $("campo-nome");
  $("btn-editar-nome").addEventListener("click", () => {
    $form.hidden = false;
    $campo.value = atual?.nome || "";
    $campo.focus();
  });
  $("btn-cancelar-nome").addEventListener("click", () => { $form.hidden = true; });
  $form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const nome = $campo.value.trim().replace(/\s+/g, " ");
    if (nome.length < 2) { $("nome-msg").textContent = "Escreva o seu nome."; return; }
    try {
      const u = await editarNome(nome);
      $form.hidden = true;
      mostrarIdentidade({ ...atual, ...u });
      $("nome-msg").textContent = "Nome salvo.";
    } catch (erro) {
      $("nome-msg").textContent = `Não foi possível salvar: ${erro.message}`;
    }
  });
}
