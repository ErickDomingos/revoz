// WebGazer falso: simula uma pessoa que olha (ou aponta o nariz) para onde o teste mandar.
// Durante a calibração, ela segue o ponto azul (pessoa "perfeita", com ruído).
(() => {
  let ouvinte = null, timer = null, gravados = 0, pausado = false;
  window.__alvo = null;           // {x, y} para onde a pessoa olha
  window.__ruido = 15;
  window.__semRosto = false;
  const onde = () => {
    const pt = document.querySelector(".pt-auto");
    if (pt) { const r = pt.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }
    return window.__alvo;
  };
  const ruido = () => (Math.random() - 0.5) * 2 * window.__ruido;
  // cabeça: nariz se desloca do centro do rosto conforme o ponto da tela (sentido invertido, como a câmera)
  let pos = null;
  function gerarPos() {
    const p = onde();
    if (!p || window.__semRosto) return;
    const u = -0.25 * (p.x / innerWidth - 0.5) + ruido() / 4000;
    const v = 0.18 * (p.y / innerHeight - 0.5) + ruido() / 4000;
    const a = new Array(468).fill(0).map(() => [0, 0, 0]);
    const w = 200, h = 260, cx = 320, cy = 240;
    a[234] = [cx - w / 2, cy, 0]; a[454] = [cx + w / 2, cy, 0];
    a[10] = [cx, cy - h / 2, 0]; a[152] = [cx, cy + h / 2, 0];
    a[1] = [cx + u * w, cy + v * h, 0];
    pos = a;
  }
  window.webgazer = {
    saveDataAcrossSessions() { return this; }, setRegression() { return this; },
    applyKalmanFilter() { return this; }, showPredictionPoints() { return this; },
    setGazeListener(f) { ouvinte = f; return this; },
    begin() {
      timer = setInterval(() => {
        if (pausado) return;
        gerarPos();
        const p = onde();
        if (ouvinte) ouvinte(p && !window.__semRosto ? { x: p.x + ruido(), y: p.y + ruido() } : null, 0);
      }, 30);
      return Promise.resolve(this);
    },
    removeMouseEventListeners() { window.__semMouse = true; return this; },
    clearData() { gravados = 0; },
    recordScreenPosition() { gravados++; window.__gravados = gravados; },
    pause() { pausado = true; }, resume() { pausado = false; },
    showVideoPreview() { return this; },
    getTracker() { return { getPositions: () => pos }; },
  };
})();
