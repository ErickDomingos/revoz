import { API_URL, TIMEOUT_API_MS } from "./config.js";

// ---------- Sessão (token do login) ----------
const CHAVE_TOKEN = "token";
let aoExpirar = () => {};

export function obterToken() {
  try {
    return localStorage.getItem(CHAVE_TOKEN);
  } catch {
    return null;
  }
}

function guardarToken(token) {
  try {
    if (token) localStorage.setItem(CHAVE_TOKEN, token);
    else localStorage.removeItem(CHAVE_TOKEN);
  } catch { /* sem armazenamento: vale só até recarregar */ }
}

// Chamada quando o servidor recusa o token (venceu ou foi invalidado).
export function aoSessaoExpirar(funcao) {
  aoExpirar = funcao;
}

function cabecalhos(extra = {}) {
  const token = obterToken();
  return { ...extra, ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

function sessaoExpirada() {
  guardarToken(null);
  limparCache();
  aoExpirar();
  return new Error("Sessão expirada. Entre de novo.");
}

async function enviar(caminho, corpo) {
  const resp = await fetch(`${API_URL}${caminho}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corpo),
    signal: AbortSignal.timeout(10000),
  });
  const dados = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(typeof dados.detail === "string" ? dados.detail : "Não foi possível concluir. Confira os dados.");
  }
  return dados;
}

export async function entrar(email, senha) {
  const dados = await enviar("/auth/login", { email, senha });
  guardarToken(dados.token);
  return dados.usuario;
}

export async function cadastrar(email, senha, papel, nome) {
  await enviar("/auth/cadastro", { nome, email, senha, papel });
  return entrar(email, senha);
}

export const editarNome = (nome) => pedir("PUT", "/auth/nome", { corpo: { nome } });

// Devolve o usuário da sessão atual, ou null se não houver sessão válida.
export async function usuarioAtual() {
  if (!obterToken()) return null;
  try {
    const resp = await fetch(`${API_URL}/auth/eu`, { headers: cabecalhos(), signal: AbortSignal.timeout(5000) });
    if (resp.status === 401) {
      guardarToken(null);
      return null;
    }
    return resp.ok ? await resp.json() : null;
  } catch {
    return null;
  }
}

export function sair() {
  guardarToken(null);
  limparCache();
}

// Fase 6: a voz em uso agora fica no servidor (PUT /vozes/ativa), não no navegador.
// Antes ela ficava no localStorage e passava de uma conta para outra no mesmo aparelho.
try { localStorage.removeItem("voice_id"); } catch { /* sem armazenamento */ }

// ---------- Geração de áudio ----------
// Frase repetida toca na hora, sem pedir de novo ao servidor.
const cache = new Map();

export function limparCache() {
  cache.forEach((r) => URL.revokeObjectURL(r.url));
  cache.clear();
}

// opcoes.voiceId: testa essa voz (só vozes do próprio usuário); omitido = voz ativa da conta.
// opcoes.generica: força a voz genérica. opcoes.base: "feminina" | "masculina" (qual genérica).
// opcoes.historico: guarda a frase nas "Recentes" (só o modo Digitar usa).
// Quem está pedindo é identificado pelo token, nunca por um campo enviado pelo app.
export async function gerarAudio(texto, { voiceId = null, generica = false, base = null, historico = false } = {}) {
  const chave = `${generica ? `generica:${base ?? ""}` : voiceId ?? ""}|${texto}`;
  if (cache.has(chave)) {
    if (historico) registrarRecente(texto).catch(() => {}); // tocou do cache: só anota
    return cache.get(chave);
  }

  const ctrl = new AbortController();
  const limite = setTimeout(() => ctrl.abort(), TIMEOUT_API_MS);
  try {
    const corpo = { texto, generica, historico, ...(voiceId ? { voice_id: voiceId } : {}), ...(base ? { base } : {}) };
    const resp = await fetch(`${API_URL}/gerar-audio`, {
      method: "POST",
      headers: cabecalhos({ "Content-Type": "application/json" }),
      body: JSON.stringify(corpo),
      signal: ctrl.signal,
    });
    if (resp.status === 401) throw sessaoExpirada();
    if (!resp.ok) throw new Error(`Erro ${resp.status}`);

    const blob = await resp.blob();
    const resultado = {
      blob, // guardado para baixar ou compartilhar a fala
      url: URL.createObjectURL(blob),
      voz: resp.headers.get("X-Voz") || "desconhecida",
      base: resp.headers.get("X-Voz-Base"), // "feminina" | "masculina"
    };
    cache.set(chave, resultado);
    return resultado;
  } finally {
    clearTimeout(limite);
  }
}

// Áudio já gerado com a voz em uso, sem esperar o servidor (null se não houver).
export const audioEmCache = (texto) => cache.get(`|${texto}`) || null;

// Gera as frases fixas em sequência (sem sobrecarregar o servidor),
// para que toquem na hora quando forem selecionadas.
export async function preGerar(frases) {
  for (const frase of frases) {
    try {
      await gerarAudio(frase);
    } catch {
      return; // servidor fora do ar ou sem login: para de tentar
    }
  }
}

// ---------- Catálogo de vozes (GET /vozes, só as vozes do próprio usuário) ----------
export async function listarVozes() {
  const resp = await fetch(`${API_URL}/vozes`, { headers: cabecalhos(), signal: AbortSignal.timeout(5000) });
  if (resp.status === 401) throw sessaoExpirada();
  if (!resp.ok) throw new Error(`Erro ${resp.status}`);
  const dados = await resp.json();
  const lista = Array.isArray(dados) ? dados : (dados.vozes ?? []);
  return lista.map((v) => {
    if (typeof v === "string") return { id: v, nome: v };
    const id = v.id ?? v.voice_id;
    return { id, nome: v.nome ?? v.name ?? id, detalhe: v.detalhe, ativa: Boolean(v.ativa) };
  });
}

// ---------- Estado do servidor (GET /health, não exige login) ----------
export async function servidorOnline() {
  try {
    const resp = await fetch(`${API_URL}/health`, { signal: AbortSignal.timeout(3000) });
    return resp.ok;
  } catch (erro) {
    console.error("API inacessível:", erro); // problemas de CORS aparecem aqui
    return false;
  }
}
// ---------- Fase 5: privacidade (amostras, consentimento, vínculos, auditoria) ----------
// Chamada genérica com o token. 401 = sessão vencida; os outros erros viram Error com a mensagem do servidor.
async function pedir(metodo, caminho, { corpo, bruto, tipo, tempo = 15000 } = {}) {
  const extra = bruto ? { "Content-Type": tipo || "application/octet-stream" }
    : corpo !== undefined ? { "Content-Type": "application/json" } : {};
  const resp = await fetch(`${API_URL}${caminho}`, {
    method: metodo,
    headers: cabecalhos(extra),
    body: bruto ?? (corpo !== undefined ? JSON.stringify(corpo) : undefined),
    signal: AbortSignal.timeout(tempo),
  });
  if (resp.status === 401) throw sessaoExpirada();
  const dados = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(typeof dados.detail === "string" ? dados.detail : `Erro ${resp.status}`);
  }
  return dados;
}

const doPaciente = (pacienteId) => (pacienteId ? `?paciente_id=${encodeURIComponent(pacienteId)}` : "");

// pacienteId: omitido = os dados do próprio usuário; número = paciente vinculado (cuidador).
export const enviarAmostra = (arquivo, pacienteId) =>
  pedir("POST", `/amostras${doPaciente(pacienteId)}`, { bruto: arquivo, tipo: arquivo.type || "audio/wav", tempo: 120000 });
export const listarAmostras = (pacienteId) => pedir("GET", `/amostras${doPaciente(pacienteId)}`);
export const apagarAmostra = (id, pacienteId) =>
  pedir("DELETE", `/amostras/${encodeURIComponent(id)}${doPaciente(pacienteId)}`);

export const textoConsentimento = () => pedir("GET", "/consentimento/texto");
export const statusConsentimento = (pacienteId) => pedir("GET", `/consentimento${doPaciente(pacienteId)}`);
export const assinarConsentimento = (dados) => pedir("POST", "/consentimento", { corpo: dados });
export function revogarConsentimento(pacienteId, apagarDados = false) {
  const q = new URLSearchParams();
  if (pacienteId) q.set("paciente_id", pacienteId);
  if (apagarDados) q.set("apagar_dados", "true");
  const qs = q.toString();
  return pedir("DELETE", `/consentimento${qs ? `?${qs}` : ""}`);
}

export const pedirVinculo = (email) => pedir("POST", "/vinculos", { corpo: { paciente_email: email } });
export const listarVinculos = () => pedir("GET", "/vinculos");
export const mudarVinculo = (cuidadorId, pacienteId, status) =>
  pedir("POST", "/vinculos/status", { corpo: { cuidador_id: cuidadorId, paciente_id: pacienteId, status } });

export const apagarVoz = (id) => pedir("DELETE", `/vozes/${encodeURIComponent(id)}`);
export const listarAuditoria = () => pedir("GET", "/auditoria");

// ---------- Fase 6: dados da conta (voz ativa, frases, recentes, LGPD) ----------
// id = null volta para a voz genérica (generica = "feminina" | "masculina").
// O cache é limpo porque os áudios guardados são da voz antiga.
export async function definirVozAtiva(id, generica = null) {
  const r = await pedir("PUT", "/vozes/ativa", { corpo: { voice_id: id, ...(generica ? { generica } : {}) } });
  limparCache();
  return r;
}

// { escolhida: "feminina", opcoes: [{ id, nome, disponivel }] }
export const vozesGenericas = () => pedir("GET", "/vozes/generica");

// Frases prontas: [{ nome: "Saúde", frases: ["Estou com dor", ...] }, ...]
export async function obterCategorias() {
  return (await pedir("GET", "/frases")).categorias;
}
export async function salvarCategorias(categorias) {
  return (await pedir("PUT", "/frases", { corpo: { categorias } })).categorias;
}

// O alarme já tocou no aparelho; aqui só fica o registro na atividade da conta.
// Sem login ou sem servidor, só não registra (não pede o login no meio de uma emergência).
export function registrarEmergencia() {
  if (!obterToken()) return Promise.resolve();
  return fetch(`${API_URL}/emergencia`, { method: "POST", headers: cabecalhos(), signal: AbortSignal.timeout(5000) })
    .catch(() => {});
}

export async function listarRecentes(n = 10) {
  return (await pedir("GET", `/historico?n=${n}`)).frases;
}
export function registrarRecente(texto) {
  return pedir("POST", "/historico", { corpo: { texto } });
}
export function limparRecentes() {
  return pedir("DELETE", "/historico");
}

// Baixa o JSON com tudo o que o servidor guarda sobre a conta.
export async function baixarMeusDados() {
  const resp = await fetch(`${API_URL}/conta/dados`, { headers: cabecalhos(), signal: AbortSignal.timeout(15000) });
  if (resp.status === 401) throw sessaoExpirada();
  if (!resp.ok) throw new Error(`Erro ${resp.status}`);
  return resp.blob();
}

// Apaga a conta, os áudios e os modelos. Pede a senha de novo.
export async function excluirConta(senha) {
  const r = await pedir("POST", "/conta/excluir", { corpo: { senha }, tempo: 60000 });
  sair();
  return r;
}
