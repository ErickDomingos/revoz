// Fase 5: cadastro de voz com consentimento em duas camadas, vínculos e auditoria.
import {
  enviarAmostra, listarAmostras, apagarAmostra,
  textoConsentimento, statusConsentimento, assinarConsentimento, revogarConsentimento,
  pedirVinculo, listarVinculos, mudarVinculo, listarAuditoria,
} from "./api.js";

const $ = (id) => document.getElementById(id);
let usuario = null;   // {id, email, papel}
let termo = null;     // texto do consentimento vindo do servidor
let vinculos = [];

// SQLite grava em UTC "AAAA-MM-DD HH:MM:SS"
const quando = (s) => (s ? new Date(s.replace(" ", "T") + "Z").toLocaleString("pt-BR") : "");

function botao(texto, classe, aoClicar) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = classe;
  b.textContent = texto;
  b.addEventListener("click", aoClicar);
  return b;
}

function cartao(titulo, detalhe, ...botoes) {
  const art = document.createElement("article");
  art.className = "cartao-voz";
  const info = document.createElement("div");
  const forte = document.createElement("strong");
  forte.textContent = titulo;
  const span = document.createElement("span");
  span.className = "ajuda";
  span.textContent = detalhe;
  info.append(forte, span);
  const acoes = document.createElement("div");
  acoes.className = "acoes";
  acoes.append(...botoes);
  art.append(info, acoes);
  return art;
}

// ---------------------------------------------------------- de quem é a voz
// "" = a própria voz; número = paciente com vínculo ativo (só para cuidador)
const alvo = () => ($("mv-alvo").value ? Number($("mv-alvo").value) : undefined);

// "Maria Silva (maria@x.com)", ou só o e-mail se a conta ainda não tem nome
const pessoa = (nome, email) => (nome ? `${nome} (${email})` : email);

function desenharAlvos() {
  const $alvo = $("mv-alvo");
  const anterior = $alvo.value;
  const opcoes = [new Option("Minha própria voz", "")];
  vinculos
    .filter((v) => v.cuidador_id === usuario?.id && v.status === "ativo")
    .forEach((v) => opcoes.push(new Option(`Usuário: ${pessoa(v.paciente_nome, v.paciente_email)} (sou responsável legal)`, v.paciente_id)));
  $alvo.replaceChildren(...opcoes);
  if ([...$alvo.options].some((o) => o.value === anterior)) $alvo.value = anterior;
}

// ---------------------------------------------------------- amostras e status
export async function atualizarMinhaVoz() {
  if (!usuario) return;
  const $status = $("mv-status");
  try {
    const [st, amostras] = await Promise.all([statusConsentimento(alvo()), listarAmostras(alvo())]);
    $status.textContent = st.valido
      ? `Consentimento válido desde ${quando(st.criado_em)}, assinado por ${st.nome_declarante} (${st.amostras_autorizadas} áudio(s) autorizados).`
      : "Ainda não há consentimento. Sem ele, o app não usa voz clonada.";
    $("mv-revogar").hidden = !st.valido;

    $("mv-amostras").replaceChildren(...amostras.map((a) => cartao(
      `Áudio ${a.formato.toUpperCase()}${a.duracao_s ? ` · ${a.duracao_s.toFixed(0)} s` : ""}`,
      `Enviado em ${quando(a.criado_em)}`,
      botao("Apagar", "secundario", async () => {
        await apagarAmostra(a.id, alvo()).catch((e) => ($status.textContent = e.message));
        atualizarMinhaVoz();
      }),
    )));
  } catch (erro) {
    $status.textContent = `Não foi possível carregar: ${erro.message}`;
  }
}

async function enviarArquivos() {
  const $arquivos = $("mv-arquivos");
  const $status = $("mv-status");
  const lista = [...$arquivos.files];
  if (!lista.length) { $status.textContent = "Escolha pelo menos um arquivo de áudio."; return; }
  $("mv-enviar").disabled = true;
  try {
    for (const [i, arquivo] of lista.entries()) {
      $status.textContent = `Enviando ${i + 1} de ${lista.length}: ${arquivo.name}…`;
      await enviarAmostra(arquivo, alvo());
    }
    $arquivos.value = "";
    await atualizarMinhaVoz();
  } catch (erro) {
    $status.textContent = `Falha no envio: ${erro.message}`;
  } finally {
    $("mv-enviar").disabled = false;
  }
}

// ---------------------------------------------------------- consentimento
async function carregarTermo() {
  termo = await textoConsentimento();
  $("mv-texto-identidade").textContent = termo.camada_identidade;
  $("mv-usos").replaceChildren(...termo.camada_uso.map((texto, i) => {
    const label = document.createElement("label");
    label.className = "marcar";
    const caixa = document.createElement("input");
    caixa.type = "checkbox";
    caixa.dataset.uso = i;
    const span = document.createElement("span");
    span.textContent = texto;
    label.append(caixa, span);
    return label;
  }));
}

async function assinar(e) {
  e.preventDefault();
  const $erro = $("mv-erro");
  $erro.textContent = "";
  $("mv-assinar").disabled = true;
  try {
    if (!termo) await carregarTermo();
    const amostras = await listarAmostras(alvo());
    if (!amostras.length) throw new Error("Envie pelo menos um áudio antes de assinar.");
    const aceites = [...$("mv-usos").querySelectorAll("input[type=checkbox]")].map((c) => c.checked);
    if (!$("mv-identidade").checked || aceites.some((a) => !a)) {
      throw new Error("Para autorizar, é preciso marcar todas as declarações.");
    }
    const pacienteId = alvo();
    await assinarConsentimento({
      versao: termo.versao,
      senha: $("mv-senha").value,
      nome_completo: $("mv-nome").value.trim(),
      relacao: pacienteId ? "responsavel_legal" : "propria",
      paciente_id: pacienteId ?? null,
      aceite_identidade: true,
      aceites_uso: aceites,
      amostras: amostras.map((a) => a.id),
    });
    $("mv-form").reset();
    await atualizarMinhaVoz();
  } catch (erro) {
    $erro.textContent = erro.message;
  } finally {
    $("mv-senha").value = "";
    $("mv-assinar").disabled = false;
  }
}

async function revogar(apagarDados) {
  const msg = apagarDados
    ? "Revogar e APAGAR definitivamente os áudios e os modelos desta voz? Não dá para desfazer."
    : "Revogar o consentimento? A voz clonada para de ser usada na hora.";
  if (!confirm(msg)) return;
  try {
    await revogarConsentimento(alvo(), apagarDados);
  } catch (erro) {
    $("mv-status").textContent = erro.message;
  }
  atualizarMinhaVoz();
}

// ---------------------------------------------------------- vínculos
const ROTULO_VINCULO = { pendente: "Aguardando aprovação", ativo: "Ativo", revogado: "Revogado" };

export async function atualizarVinculos() {
  if (!usuario) return;
  const cuidador = usuario.papel === "cuidador";
  $("vinc-form").hidden = !cuidador;
  $("vinc-ajuda").textContent = cuidador
    ? "Peça vínculo com a conta do usuário de quem você cuida. Ele precisa aprovar antes de você usar a voz dele."
    : "Responsáveis que pedirem vínculo aparecem aqui. Só aprove quem você conhece.";
  try {
    vinculos = await listarVinculos();
  } catch (erro) {
    $("vinc-msg").textContent = erro.message;
    return;
  }
  const mudar = (v, status) => async () => {
    await mudarVinculo(v.cuidador_id, v.paciente_id, status).catch((e) => ($("vinc-msg").textContent = e.message));
    await atualizarVinculos();
    atualizarMinhaVoz();
  };
  $("vinc-lista").replaceChildren(...vinculos.map((v) => {
    const souPaciente = v.paciente_id === usuario.id;
    const outro = souPaciente ? `Responsável: ${pessoa(v.cuidador_nome, v.cuidador_email)}`
      : `Usuário: ${pessoa(v.paciente_nome, v.paciente_email)}`;
    const botoes = [];
    if (souPaciente && v.status === "pendente") {
      botoes.push(botao("Aprovar", "secundario", mudar(v, "ativo")), botao("Recusar", "secundario", mudar(v, "revogado")));
    } else if (v.status !== "revogado") {
      botoes.push(botao(v.status === "pendente" ? "Cancelar pedido" : "Revogar", "secundario", mudar(v, "revogado")));
    }
    return cartao(outro, ROTULO_VINCULO[v.status] || v.status, ...botoes);
  }));
  desenharAlvos();
}

// ---------------------------------------------------------- auditoria
const ACOES = {
  gerar_audio: "Gerou fala", login: "Entrou na conta", cadastro: "Criou a conta", sair_todos: "Saiu de todos os aparelhos",
  confirmar_senha: "Confirmou a senha", consentimento: "Assinou o consentimento",
  revogar_consentimento: "Revogou o consentimento", enviar_amostra: "Enviou um áudio", apagar_amostra: "Apagou um áudio",
  criar_voz: "Voz cadastrada", apagar_voz: "Apagou uma voz", pedir_vinculo: "Pediu vínculo",
  vinculo_ativo: "Aprovou vínculo", vinculo_revogado: "Revogou vínculo",
  // Fase 6
  definir_voz_ativa: "Trocou a voz em uso", salvar_frases: "Editou as frases prontas", editar_nome: "Mudou o nome da conta", emergencia: "Acionou o botão de emergência",
  limpar_historico: "Limpou as frases recentes", exportar_dados: "Baixou os próprios dados",
  exportar_para_treino: "Áudios abertos para o treino da voz",
};

async function mostrarAuditoria() {
  const $lista = $("lista-auditoria");
  try {
    const itens = await listarAuditoria();
    if (!itens.length) { $lista.replaceChildren(Object.assign(document.createElement("li"), { textContent: "Nenhuma atividade." })); return; }
    $lista.replaceChildren(...itens.slice(0, 30).map((r) => {
      const li = document.createElement("li");
      li.className = r.resultado;
      const quem = r.usuario_id === usuario?.id ? "Você" : (r.quem || "Alguém");
      li.textContent = `${quando(r.quando)} · ${quem} · ${ACOES[r.acao] || r.acao} · ${r.resultado}`;
      return li;
    }));
  } catch (erro) {
    $lista.replaceChildren(Object.assign(document.createElement("li"), { textContent: erro.message }));
  }
}

// ---------------------------------------------------------- inicialização
export function iniciarPrivacidade() {
  $("mv-enviar").addEventListener("click", enviarArquivos);
  $("mv-form").addEventListener("submit", assinar);
  $("mv-alvo").addEventListener("change", atualizarMinhaVoz);
  $("mv-revogar-so").addEventListener("click", () => revogar(false));
  $("mv-revogar-tudo").addEventListener("click", () => revogar(true));
  $("btn-auditoria").addEventListener("click", mostrarAuditoria);
  $("vinc-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const r = await pedirVinculo($("vinc-email").value.trim());
      $("vinc-msg").textContent = r.mensagem;
      $("vinc-email").value = "";
      atualizarVinculos();
    } catch (erro) {
      $("vinc-msg").textContent = erro.message;
    }
  });
  desenharAlvos();
}

// Chamada depois do login (ou quando a sessão é restaurada).
export async function privacidadeAoEntrar(u) {
  usuario = u;
  $("lista-auditoria").replaceChildren();
  carregarTermo().catch(() => {});
  await atualizarVinculos();
  atualizarMinhaVoz();
}
