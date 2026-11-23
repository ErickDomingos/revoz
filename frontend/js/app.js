import { iniciarDigitar, atualizarRecentes, esconderRecentes } from "./modo-digitar.js";
import { iniciarOlhar, ativar, desativar, voltarAoInicio } from "./modo-olhar.js";
import { iniciarVozes, atualizarVozes, limparVozes } from "./vozes.js";
import { iniciarAjustes } from "./ajustes.js";
import { liberarAudio, esquecerUltimaFala } from "./falar.js";
import { preGerar, servidorOnline, usuarioAtual, sair, aoSessaoExpirar } from "./api.js";
import { iniciarLogin, mostrarLogin } from "./login.js";
import { iniciarPrivacidade, privacidadeAoEntrar, atualizarMinhaVoz, atualizarVinculos } from "./privacidade.js";
import { iniciarConta, contaAoEntrar, contaAoSair } from "./conta.js";
import { atualizarGuia, guiaAoEntrar, guiaAoSair } from "./guia.js";
import { iniciarEmergencia, prepararEmergencia } from "./emergencia.js";
import { iniciarIdentidade, mostrarIdentidade, esconderIdentidade } from "./identidade.js";
import { todasFrases } from "./frases.js";
import { API_URL, PREGERAR_FRASES } from "./config.js";

iniciarEmergencia();
iniciarDigitar();
iniciarOlhar();
iniciarVozes();
iniciarAjustes();
iniciarPrivacidade();
iniciarConta(() => voltarAoLogin()); // depois de excluir a conta

// ---------- Abas ----------
const abas = [...document.querySelectorAll('[role="tab"]')];

const paineis = [...document.querySelectorAll('[role="tabpanel"]')];
// Telas que não têm aba própria: a aba "mãe" fica marcada enquanto elas estão abertas.
const ABA_MAE = { consentimento: "vozes" };

function trocar(modo) {
  const abaMarcada = ABA_MAE[modo] || modo;
  abas.forEach((aba) => {
    const ativa = aba.dataset.modo === abaMarcada;
    aba.setAttribute("aria-selected", ativa);
    aba.tabIndex = ativa ? 0 : -1;
  });
  paineis.forEach((p) => { p.hidden = p.id !== `painel-${modo}`; });

  if (modo === "olhar") {
    liberarAudio(); // o clique na aba libera o áudio para as seleções por olhar
    ativar();
  } else {
    desativar();
  }
  if (modo === "vozes") atualizarVozes();
  if (modo === "consentimento") atualizarVinculos().then(atualizarMinhaVoz); // vínculos definem "de quem é a voz"
  if (modo === "guia") atualizarGuia();
  if (modo === "conta") atualizarVinculos();
  document.querySelector("main").scrollTop = 0;
}

abas.forEach((aba) => aba.addEventListener("click", () => trocar(aba.dataset.modo)));

// Nome e iniciais no topo: tocar abre a aba Conta.
iniciarIdentidade(() => trocar("conta"));

// O logo volta para o início (Digitar), como na maioria dos apps.
document.getElementById("logo-inicio").addEventListener("click", (e) => {
  e.preventDefault();
  trocar("digitar");
  document.getElementById("aba-digitar").focus();
});

// Atalhos "Ir para ..." (Guia, Vozes): qualquer botão com data-ir troca de aba
document.addEventListener("click", (e) => {
  const atalho = e.target.closest("[data-ir]");
  if (!atalho) return;
  const destino = atalho.dataset.ir;
  trocar(destino);
  if (ABA_MAE[destino]) {
    // tela sem aba própria: o foco vai para o título dela (leitor de tela anuncia onde chegou)
    const titulo = document.querySelector(`#painel-${destino} h2`);
    titulo.tabIndex = -1;
    titulo.focus();
  } else {
    document.getElementById(`aba-${destino}`).focus();
  }
});

// Setas do teclado percorrem as abas
document.querySelector('[role="tablist"]').addEventListener("keydown", (e) => {
  const i = abas.indexOf(document.activeElement);
  const passo = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
  if (i < 0 || !passo) return;
  e.preventDefault();
  const proxima = abas[(i + passo + abas.length) % abas.length];
  proxima.focus();
  proxima.click();
});

// ---------- Estado do servidor ----------
// Na primeira vez que o servidor responde, gera o áudio das frases fixas
// para que toquem na hora.
const $servidor = document.getElementById("estado-servidor");
const $info = document.getElementById("info-servidor");
let preGerado = false;
let logado = false;

async function checarServidor() {
  const online = await servidorOnline();
  $servidor.dataset.estado = online ? "online" : "offline";
  $servidor.textContent = online ? "Conectado" : "Offline";
  $info.textContent = online
    ? `Conectado a ${API_URL}`
    : `Sem resposta de ${API_URL}. Confira se o servidor está rodando, a porta e o CORS.`;
  if (online && logado && !preGerado) {
    preGerado = true;
    prepararEmergencia(); // a frase de socorro primeiro: tem que tocar na hora
    if (PREGERAR_FRASES) preGerar(todasFrases());
  }
}

document.getElementById("btn-testar").addEventListener("click", checarServidor);
checarServidor();
setInterval(checarServidor, 10000);

// ---------- Splash e boas-vindas (só na primeira vez) ----------
const $splash = document.getElementById("splash");
const $boasVindas = document.getElementById("boas-vindas");
setTimeout(() => $splash.classList.add("some"), 900);

// Aparece depois do login (antes ficava escondida atrás da tela de login).
function mostrarBoasVindas() {
  let jaVisto = false;
  try { jaVisto = localStorage.getItem("onboarding") === "ok"; } catch { /* sem armazenamento */ }
  if (!jaVisto) $boasVindas.hidden = false;
}

function fecharBoasVindas() {
  $boasVindas.hidden = true;
  liberarAudio(); // o clique libera o áudio já na primeira vez
  try { localStorage.setItem("onboarding", "ok"); } catch { /* sem armazenamento */ }
}

document.getElementById("btn-comecar").addEventListener("click", fecharBoasVindas);
document.getElementById("btn-ver-guia").addEventListener("click", () => {
  fecharBoasVindas();
  trocar("guia");
});

// ---------- Login e conta ----------
const $conta = document.getElementById("info-conta");
const $sairTopo = document.getElementById("btn-sair-topo");
// No banco os papéis continuam "paciente" e "cuidador"; na tela, "usuário" e "responsável".
const mostrarConta = async (u) => {
  logado = true;
  mostrarIdentidade(u);
  $sairTopo.hidden = false;
  $sairTopo.title = `Sair da conta ${u.email}`;
  privacidadeAoEntrar(u); // Fase 5: consentimento, vínculos e auditoria do usuário que entrou
  atualizarRecentes();    // Fase 6: frases recentes da conta
  guiaAoEntrar(u);
  mostrarBoasVindas();
  await contaAoEntrar();  // frases prontas (por categoria) guardadas na conta
  preGerado = false;
  checarServidor();       // com a conta e as frases carregadas, prepara os áudios
};

// Sair (ou conta excluída): nada da conta anterior fica na tela.
function voltarAoLogin() {
  logado = false;
  preGerado = false;
  $sairTopo.hidden = true;
  esconderIdentidade();
  contaAoSair();
  voltarAoInicio();
  esconderRecentes();
  limparVozes();
  guiaAoSair();
  esquecerUltimaFala();
  $conta.textContent = "";
  trocar("digitar");
  mostrarLogin();
}

iniciarLogin(mostrarConta);
aoSessaoExpirar(mostrarLogin); // o servidor recusou o token: pede o login de novo
usuarioAtual().then((u) => (u ? mostrarConta(u) : mostrarLogin()));

// "Sair" fica no topo (sempre à mão) e também na aba Conta.
const sairDaConta = () => {
  sair();
  voltarAoLogin();
};
document.getElementById("btn-sair").addEventListener("click", sairDaConta);
$sairTopo.addEventListener("click", sairDaConta);