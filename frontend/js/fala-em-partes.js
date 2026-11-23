// Textos longos: divide em frases e começa a tocar antes de converter tudo.
//
// Para não ficar com buracos no meio da fala, o app mede a velocidade do servidor
// na primeira parte e só começa a tocar quando dá para tocar até o fim SEM PARAR:
//  - servidor rápido (GPU, mais rápido que a fala): toca logo depois da primeira frase;
//  - servidor lento (CPU): espera o suficiente para as partes seguintes ficarem
//    prontas a tempo. Começa mais tarde, mas ainda antes do que esperando tudo.

const MIN_PARTE = 25;   // pedaços muito curtos se juntam ao vizinho ("Oi." + "Tudo bem?")
const MAX_PARTE = 180;  // frases muito longas são quebradas nas vírgulas
const FOLGA = 1.15;     // 15% de margem na estimativa

// "Bom dia. Hoje estou com dor nas costas, e queria..." -> ["Bom dia. Hoje estou...", ...]
export function dividirEmPartes(texto) {
  const frases = texto.replace(/\s+/g, " ").trim().match(/[^.!?;…\n]+[.!?;…]*\s*/g) || [texto];
  const quebradas = frases.flatMap((f) => {
    if (f.length <= MAX_PARTE) return [f];
    const partes = [];
    let atual = "";
    for (const trecho of f.split(/(?<=,)\s*/)) {
      if (atual && (atual + " " + trecho).length > MAX_PARTE) { partes.push(atual); atual = trecho; }
      else atual = atual ? `${atual} ${trecho}` : trecho;
    }
    if (atual) partes.push(atual);
    return partes;
  });
  const juntas = [];
  for (const p of quebradas.map((q) => q.trim()).filter(Boolean)) {
    const ultima = juntas[juntas.length - 1];
    if (ultima !== undefined && (ultima.length < MIN_PARTE || p.length < MIN_PARTE) &&
        (ultima + " " + p).length <= MAX_PARTE) {
      juntas[juntas.length - 1] = `${ultima} ${p}`;
    } else {
      juntas.push(p);
    }
  }
  return juntas.length ? juntas : [texto.trim()];
}

function duracao(url) {
  return new Promise((ok) => {
    const a = new Audio();
    a.preload = "metadata";
    a.onloadedmetadata = () => ok(Number.isFinite(a.duration) ? a.duration : 0);
    a.onerror = () => ok(0);
    a.src = url;
  });
}

// gerar(parte) -> { url, blob, voz, base }. tocar(url) -> Promise. aoEstado(texto) mostra o andamento.
// Devolve a lista de resultados (na ordem). Se uma parte falhar, lança o erro com .tocadas = quantas já tocaram.
// velocidade: a fala mais lenta dura mais (dá mais folga); a mais rápida, menos.
export async function falarEmPartes(partes, { gerar, tocar, aoEstado, aoComecar, velocidade = 1 }) {
  const n = partes.length;
  const prontos = new Array(n);   // { res, dur, ms, cache }
  let falha = null;
  let avisar = () => {};
  // Acorda quando uma parte fica pronta ou a cada 250 ms (a condição também depende do tempo).
  const mudou = () => new Promise((r) => {
    const t = setTimeout(r, 250);
    avisar = () => { clearTimeout(t); r(); };
  });

  // Produtor: converte as partes em ordem, uma de cada vez (o servidor converte uma por vez).
  (async () => {
    for (let i = 0; i < n; i++) {
      const t0 = performance.now();
      try {
        const res = await gerar(partes[i]);
        const ms = performance.now() - t0;
        prontos[i] = { res, dur: await duracao(res.url), ms, cache: ms < 150, fim: performance.now() };
      } catch (e) {
        falha = e;
        avisar();
        return;
      }
      avisar();
    }
  })();

  const chars = (de) => partes.slice(de).reduce((s, p) => s + p.length, 0);

  // Dá para começar a tocar já? Só se o áudio pronto cobre o tempo de converter o resto.
  function podeComecar() {
    let k = 0;
    while (k < n && prontos[k]) k++;            // partes 0..k-1 prontas
    if (k === 0) return false;
    if (k === n) return true;
    const medidas = prontos.slice(0, k).filter((p) => !p.cache && p.dur > 0);
    if (!medidas.length) return false;          // só veio do cache: ainda não sei a velocidade
    const ultima = medidas[medidas.length - 1];
    const segPorSeg = ultima.ms / 1000 / ultima.dur;          // segundos de conversão por segundo de fala
    const segPorChar = medidas.reduce((s, p) => s + p.dur, 0) /
      medidas.reduce((s, p) => s + partes[prontos.indexOf(p)].length, 0);
    const faltaConverter = chars(k) * segPorChar * segPorSeg * FOLGA;
    const jaConvertendo = (performance.now() - prontos[k - 1].fim) / 1000; // a parte k já está sendo convertida
    const prontoParaTocar = prontos.slice(0, k).reduce((s, p) => s + p.dur, 0) / velocidade;
    return prontoParaTocar >= faltaConverter - jaConvertendo;
  }

  // Espera até poder começar sem buracos
  while (!podeComecar()) {
    if (falha) throw Object.assign(falha, { tocadas: 0 });
    const feitas = prontos.filter(Boolean).length;
    aoEstado(`Gerando voz… (${feitas} de ${n})`);
    await mudou();
  }

  aoComecar?.();
  for (let i = 0; i < n; i++) {
    while (!prontos[i]) {                        // a estimativa errou: espera a próxima parte
      if (falha) throw Object.assign(falha, { tocadas: i });
      aoEstado(`Gerando voz… (${i} de ${n})`);
      await mudou();
    }
    aoEstado(null, i);
    await tocar(prontos[i].res.url);
  }
  return prontos.map((p) => p.res);
}
