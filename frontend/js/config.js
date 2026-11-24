// Configuração central: ajustem aqui, sem mexer no resto do código.

export const API_URL = "https://perhaps-confidential-shorts-nicole.trycloudflare.com";
// Ajustem depois de medir o tempo real do RVC.
export const TIMEOUT_API_MS = 120000;

// Gera as frases fixas em segundo plano ao abrir o app. Deixe false se o RVC for lento
// (a geração em segundo plano pode atrasar a frase que a pessoa pediu).
export const PREGERAR_FRASES = false;

// Se o servidor falhar, fala com a voz do navegador (a pessoa nunca fica sem falar).
export const FALLBACK_NAVEGADOR = true;

// Modo olhar
export const DWELL_MS = 1500;           // tempo padrão olhando uma frase para selecioná-la
export const CALIB_ESPERA_MS = 800;     // calibração: tempo para o olhar chegar no ponto
export const CALIB_GRAVACAO_MS = 1500;  // calibração: quanto tempo grava com o olhar no ponto
export const CALIB_VALIDACAO_MS = 1200; // depois da calibração: mede o erro em cada ponto de teste

// Frases prontas por categoria (as mesmas do servidor, em conta.py).
// Valem até a pessoa entrar na conta; depois vêm as dela (GET /frases).
export const CATEGORIAS = [
  { nome: "Respostas", frases: ["Sim", "Não", "Talvez", "Não sei", "Obrigado"] },
  { nome: "Necessidades", frases: ["Estou com sede", "Estou com fome", "Quero ir ao banheiro", "Quero mudar de posição", "Quero dormir"] },
  { nome: "Saúde", frases: ["Estou com dor", "Estou com frio", "Estou com calor", "Estou com falta de ar", "Chame a enfermagem"] },
  { nome: "Sentimentos", frases: ["Estou bem", "Estou triste", "Estou com medo", "Eu te amo"] },
  { nome: "Conversa", frases: ["Bom dia", "Boa noite", "Pode repetir?", "Espere um pouco", "Quero conversar"] },
];
export const FRASES = CATEGORIAS.flatMap((c) => c.frases);
export const MAX_CATEGORIAS = 8;
export const MAX_POR_CATEGORIA = 8;

// Botão de emergência: o alarme toca no próprio aparelho, mesmo sem servidor.
export const EMERGENCIA_TEXTO = "Preciso de ajuda, por favor venha aqui!";
