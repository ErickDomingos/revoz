import { FALLBACK_NAVEGADOR } from "./config.js";
import { gerarAudio, registrarRecente } from "./api.js";
import { dividirEmPartes, falarEmPartes } from "./fala-em-partes.js";
import { obter } from "./ajustes.js";

const $status = document.getElementById("status");
const $selo = document.getElementById("selo-voz");
const $baixar = document.getElementById("btn-baixar-fala");
const $enviar = document.getElementById("btn-enviar-fala");
let ocupado = false;
let ultima = null; // { blob, quando }: a última fala gerada pelo servidor

// Um único player, liberado num clique: assim o navegador deixa tocar
// depois, mesmo quando a frase foi escolhida pelo olhar (sem clique).
const player = new Audio();

export function liberarAudio() {
  // Áudio mudo de 0 s, só para o navegador liberar o player.
  player.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";
  player.play().catch(() => {});
}

export const estaFalando = () => ocupado;

const ROTULOS = {
  clonada: "Voz clonada",
  generica: "Voz genérica",
  "generica-rvc-pendente": "Voz genérica",
  "generica-sem-consentimento": "Voz genérica (falta o consentimento da voz clonada)",
  navegador: "Voz do navegador (servidor indisponível)",
};

function mostrar(msg, voz, base) {
  $status.textContent = msg;
  if (!voz) return;
  let rotulo = ROTULOS[voz] || voz;
  if (voz.startsWith("generica") && base) rotulo = rotulo.replace("Voz genérica", `Voz genérica ${base}`);
  $selo.textContent = rotulo;
}

// ---------- Baixar / enviar a última fala ----------
const doisDigitos = (n) => String(n).padStart(2, "0");

function arquivoDaFala() {
  const d = ultima.quando;
  const ext = ultima.blob.type.includes("wav") ? "wav" : "mp3";
  const nome = `fala-${d.getFullYear()}${doisDigitos(d.getMonth() + 1)}${doisDigitos(d.getDate())}` +
    `-${doisDigitos(d.getHours())}${doisDigitos(d.getMinutes())}${doisDigitos(d.getSeconds())}.${ext}`;
  return new File([ultima.blob], nome, { type: ultima.blob.type || "audio/mpeg" });
}

function podeEnviar(arquivo) {
  try {
    return Boolean(navigator.canShare && navigator.canShare({ files: [arquivo] }));
  } catch {
    return false;
  }
}

function mostrarAcoes() {
  $baixar.hidden = !ultima;
  $enviar.hidden = !ultima || !podeEnviar(arquivoDaFala()); // o compartilhamento existe mais no celular
}

// Ao sair da conta, a fala anterior não fica disponível para a próxima pessoa.
export function esquecerUltimaFala() {
  ultima = null;
  mostrarAcoes();
}

$baixar.addEventListener("click", () => {
  if (!ultima) return;
  const arquivo = arquivoDaFala();
  const url = URL.createObjectURL(arquivo);
  const a = Object.assign(document.createElement("a"), { href: url, download: arquivo.name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

$enviar.addEventListener("click", async () => {
  if (!ultima) return;
  try {
    await navigator.share({ files: [arquivoDaFala()], title: "Fala" });
  } catch (erro) {
    if (erro.name !== "AbortError") console.error(erro); // AbortError = a pessoa fechou a janela
  }
});

// Ajustes > Velocidade da fala. O navegador mantém o tom (preservesPitch) ao acelerar ou desacelerar.
const velocidade = () => Number(obter("velocidade")) || 1;

function tocar(url) {
  return new Promise((ok, erro) => {
    const audio = new Audio(url); // um player novo a cada fala
    audio.preservesPitch = true;
    audio.playbackRate = velocidade();
    audio.onended = ok;
    audio.onerror = () => erro(new Error("Falha ao tocar o áudio"));
    audio.play().catch(erro);
  });
}

function falarNavegador(texto) {
  return new Promise((ok) => {
    const fala = new SpeechSynthesisUtterance(texto);
    fala.lang = "pt-BR";
    fala.rate = velocidade();
    fala.onend = ok;
    fala.onerror = ok;
    speechSynthesis.speak(fala);
  });
}

// ---------- Juntar as partes num arquivo só (para Baixar/Enviar) ----------
function taxaDoWav(buf) {
  const v = new DataView(buf);
  const txt = (i) => String.fromCharCode(v.getUint8(i), v.getUint8(i + 1), v.getUint8(i + 2), v.getUint8(i + 3));
  return buf.byteLength > 28 && txt(0) === "RIFF" && txt(8) === "WAVE" ? v.getUint32(24, true) : 0;
}

// Mantém a taxa do WAV do servidor (a marca d'água fica nas frequências altas).
async function juntarEmWav(blobs) {
  const brutos = await Promise.all(blobs.map((b) => b.arrayBuffer()));
  const taxa = taxaDoWav(brutos[0]) || 48000;
  const ctx = new OfflineAudioContext(1, 1, taxa);
  const audios = [];
  for (const b of brutos) audios.push(await ctx.decodeAudioData(b));
  const total = audios.reduce((s, a) => s + a.length, 0);
  const pcm = new Int16Array(total);
  let pos = 0;
  for (const a of audios) {
    for (let i = 0; i < a.length; i++) {
      let soma = 0;
      for (let c = 0; c < a.numberOfChannels; c++) soma += a.getChannelData(c)[i];
      const x = Math.max(-1, Math.min(1, soma / a.numberOfChannels));
      pcm[pos++] = x < 0 ? x * 0x8000 : x * 0x7fff;
    }
  }
  const cab = new DataView(new ArrayBuffer(44));
  const escrever = (i, t) => [...t].forEach((ch, k) => cab.setUint8(i + k, ch.charCodeAt(0)));
  escrever(0, "RIFF"); cab.setUint32(4, 36 + pcm.byteLength, true); escrever(8, "WAVE");
  escrever(12, "fmt "); cab.setUint32(16, 16, true); cab.setUint16(20, 1, true); cab.setUint16(22, 1, true);
  cab.setUint32(24, taxa, true); cab.setUint32(28, taxa * 2, true); cab.setUint16(32, 2, true); cab.setUint16(34, 16, true);
  escrever(36, "data"); cab.setUint32(40, pcm.byteLength, true);
  return new Blob([cab, pcm], { type: "audio/wav" });
}

// Estados: pronto -> gerando -> falando -> pronto
// O estado também vai para o <body> (data-estado), usado pelo CSS.
// opcoes: { voiceId, generica, base, historico } (ver gerarAudio em api.js).
// Texto com várias frases: começa a tocar antes de converter tudo (fala-em-partes.js).
// Devolve true se a frase foi falada (por qualquer voz).
export async function falar(texto, opcoes = {}) {
  texto = texto.trim();
  if (!texto || ocupado) return false;
  ocupado = true;
  let mensagemFinal = "Pronto";
  let falou = false;
  const partes = dividirEmPartes(texto);
  let parteAtual = 0; // se der erro no meio, a voz do navegador fala só o que faltou
  try {
    document.body.dataset.estado = "gerando";
    mostrar("Gerando voz…");
    if (partes.length === 1) {
      const { url, voz, base, blob } = await gerarAudio(texto, opcoes);
      ultima = { blob, quando: new Date() };
      mostrarAcoes();
      document.body.dataset.estado = "falando";
      mostrar(`Falando: “${texto}”`, voz, base);
      await tocar(url);
    } else {
      esquecerUltimaFala();
      const { historico, ...semHistorico } = opcoes; // a frase inteira vai para as Recentes, não as partes
      let primeira = null;
      const resultados = await falarEmPartes(partes, {
        gerar: async (parte) => {
          const r = await gerarAudio(parte, semHistorico);
          primeira ??= r;
          return r;
        },
        tocar,
        velocidade: velocidade(),
        aoEstado: (msg, i) => {
          if (msg) {
            document.body.dataset.estado = "gerando";
            mostrar(msg);
          } else {
            parteAtual = i;
            document.body.dataset.estado = "falando";
            mostrar(`Falando: “${texto}”`, primeira.voz, primeira.base);
          }
        },
      });
      if (historico) registrarRecente(texto).catch(() => {});
      juntarEmWav(resultados.map((r) => r.blob))
        .then((blob) => { ultima = { blob, quando: new Date() }; mostrarAcoes(); })
        .catch((e) => console.error("Não foi possível juntar as partes para baixar", e));
    }
    falou = true;
  } catch (erro) {
    console.error(erro);
    esquecerUltimaFala(); // a voz do navegador não gera arquivo: não oferece baixar uma fala antiga
    if (FALLBACK_NAVEGADOR && "speechSynthesis" in window) {
      const resto = partes.slice(parteAtual).join(" ");
      document.body.dataset.estado = "falando";
      mostrar(`Falando: “${texto}”`, "navegador");
      await falarNavegador(resto);
      falou = true;
    } else {
      mensagemFinal = "Não foi possível gerar a voz. Tente de novo.";
    }
  } finally {
    ocupado = false;
    document.body.dataset.estado = "pronto";
    mostrar(mensagemFinal);
  }
  return falou;
}
