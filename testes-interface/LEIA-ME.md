# Testes de interface do Revoz

Roteiros que abrem o app num navegador Chromium sem janela e conferem o que a pessoa veria.
Eles **não precisam** do RVC, do backend real nem de webcam:

- `mock_api.py` é uma **API falsa**, que imita as rotas do backend e devolve áudios curtos.
- `fake_webgazer.js` é uma **webcam falsa**: substitui o WebGazer e "olha" (ou aponta o nariz)
  para onde o teste mandar. Durante a calibração, segue o ponto azul como uma pessoa perfeita.

| Arquivo | O que testa |
| --- | --- |
| `teste_olhar.js` | Login, Sair no topo, frases prontas, editor de categorias, calibração dos olhos e teste de precisão, seleção pelo olhar (ímã, bloqueio em cascata), emergência pelo olhar e pelo topo, modo cabeça, celular |
| `teste_partes.js` | Fala em partes sem pausas com servidor rápido (GPU) e lento (CPU), arquivo único no Baixar, Recentes |
| `teste_visual.js` | Tema Revoz e clássico, chave da emergência, aba Conta, logo volta ao início, celular |
| `teste_nome.js` | Nome da pessoa no cadastro, no topo, na aba Conta e nas boas-vindas |
| `teste_ajustes2.js` | Ordem das abas, tela "A sua própria voz", tamanho do texto, velocidade da fala |

## Como rodar

Precisa de Node.js 18+ e Python 3.

```powershell
cd testes-interface
npm install
npx playwright install chromium
npm test
```

Antes, **parem o backend real e o servidor do frontend** (as portas 8080 e 5500 precisam estar livres).
O `rodar.js` faz uma cópia do frontend apontando para a API falsa, então o `config.js` do projeto não é alterado.
