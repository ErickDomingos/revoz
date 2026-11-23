import { entrar, cadastrar } from "./api.js";

const $tela = document.getElementById("login");
const $form = document.getElementById("form-login");
const $titulo = document.getElementById("login-titulo");
const $email = document.getElementById("login-email");
const $senha = document.getElementById("login-senha");
const $papel = document.getElementById("login-papel");
const $grupoNome = document.getElementById("login-grupo-nome");
const $nome = document.getElementById("login-nome");
const $tipo = document.getElementById("login-tipo");
const $erro = document.getElementById("login-erro");
const $enviar = document.getElementById("login-enviar");
const $alternar = document.getElementById("login-alternar");

let criandoConta = false;

function definirModo(criar) {
  criandoConta = criar;
  $titulo.textContent = criar ? "Criar conta" : "Entrar";
  $enviar.textContent = criar ? "Criar conta e entrar" : "Entrar";
  $alternar.textContent = criar ? "Já tenho conta" : "Criar conta";
  $papel.hidden = !criar;
  $grupoNome.hidden = !criar;
  $senha.autocomplete = criar ? "new-password" : "current-password";
  $erro.textContent = "";
}

export function mostrarLogin() {
  definirModo(false);
  $tela.hidden = false;
  $email.focus();
}



// aoEntrar(usuario) é chamada depois de um login ou cadastro bem-sucedido.
export function iniciarLogin(aoEntrar) {
  $alternar.addEventListener("click", () => {
    definirModo(!criandoConta);
    (criandoConta ? $nome : $email).focus();
  });

  $form.addEventListener("submit", async (e) => {
    e.preventDefault();
    $erro.textContent = "";
    $enviar.disabled = true;
    try {
      const email = $email.value.trim();
      const senha = $senha.value;
      if (!email || !senha) throw new Error("Preencha o e-mail e a senha.");
      const nome = $nome.value.trim().replace(/\s+/g, " ");
      if (criandoConta && nome.length < 2) throw new Error("Escreva o seu nome.");
      if (criandoConta && senha.length < 8) throw new Error("A senha precisa ter pelo menos 8 caracteres.");

      const usuario = criandoConta ? await cadastrar(email, senha, $tipo.value, nome) : await entrar(email, senha);
      $senha.value = "";
      $nome.value = "";
      $tela.hidden = true;
      aoEntrar(usuario);
    } catch (erro) {
      if (erro.name === "TimeoutError") $erro.textContent = "O servidor não respondeu.";
      else if (erro instanceof TypeError) $erro.textContent = "Não consegui falar com o servidor.";
      else $erro.textContent = erro.message;
    } finally {
      $enviar.disabled = false;
    }
  });
}