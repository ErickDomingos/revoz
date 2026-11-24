# Revoz

**Sua voz, de volta.** O Revoz é um aplicativo web de comunicação aumentativa e alternativa (CAA) para pessoas que perderam a fala, como pessoas com ELA ou com sequelas de AVC. A pessoa escolhe o que dizer **digitando, tocando em frases prontas ou só olhando para a tela**, e o app fala em voz alta com uma voz genérica ou com a **própria voz da pessoa**, recriada por IA a partir de gravações.

Trabalho em grupo da disciplina SCOM (2026), UNESP Sorocaba, com o Prof. Dr. Leopoldo A. D. L. Filho. Autores: **Érick Domingos da Silva** e **Leonardo de Lima Pereira**.
- **App publicado:**[https://erickdomingos.github.io/revoz/]
- **Relatório técnico e plano de disseminação:** entregues à disciplina

## O que o app faz

- **Digitar:** texto livre, frases prontas por categoria e frases recentes.
- **Olhar:** escolhe frases sem as mãos, pela webcam comum. Dois modos: **olhos** (WebGazer) ou **cabeça** (o nariz vira o cursor). Grade em dois níveis (categoria → frase), seleção por tempo de olhar e teste de precisão depois da calibração.
- **Vozes:** voz genérica feminina ou masculina, ou a voz clonada da pessoa (RVC).
- **A sua própria voz:** envio de áudios e autorização de uso da voz (consentimento em duas camadas), inclusive por um responsável legal.
- **Emergência:** sirene + frase de socorro repetidas até alguém parar; funciona sem servidor.
- **Conta:** nome, vínculos entre usuário e responsável, registro de atividade, baixar os dados e excluir a conta (LGPD).
- **Ajustes:** tempo de seleção, tamanho do texto, velocidade da fala, modo de apontar, cores e frases prontas.
- **Textos longos** começam a tocar antes de toda a conversão terminar, sem pausas.

## Segurança

A voz é dado biométrico, então o Revoz trata segurança como requisito:

- senhas com **argon2**, token **JWT** com validade e revogação, bloqueio após tentativas erradas;
- modelos de voz e áudios cifrados com **AES-256-GCM**;
- **marca d'água inaudível** em todo áudio clonado, com o número do registro de auditoria (`python watermark.py audio.wav` mostra o registro);
- auditoria de cada uso **sem guardar o texto falado**;
- direitos da LGPD: revogar, baixar os dados e excluir a conta.

Dados, chaves, modelos e áudios **nunca** vão para este repositório (ver `.gitignore`).

## Estrutura

```
frontend/            app web (HTML, CSS e JavaScript, sem framework)
  js/                um módulo por responsabilidade (modo-olhar.js, falar.js, emergencia.js…)
  mediapipe/         arquivos do Face Mesh servidos localmente
backend/             API em Python (FastAPI)
  main.py            gera o áudio: texto → voz genérica → RVC → marca d'água
  auth.py            login, cadastro, token
  conta.py           frases, histórico, voz em uso, emergência, LGPD
  privacidade.py     consentimento, vínculos, auditoria
  db.py              banco SQLite (documentado em docs/banco-de-dados.md)
  rvc_service.py     ponte com o RVC
  watermark.py       marca d'água
  test_*.py          testes automatizados do backend
testes-interface/    testes no navegador com API e webcam falsas (Playwright)
```

## Como rodar localmente (Windows)

1. **RVC:** instale o [Retrieval-based-Voice-Conversion-WebUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI) com Python 3.12 e os requisitos de CPU, e baixe os modelos `hubert_base.pt` e `rmvpe.pt` para `assets/`. O RVC **não** faz parte deste repositório.
2. **Dependências do backend**, no ambiente do RVC (sem `--upgrade`, para não quebrar o RVC):
   ```powershell
   & "C:\RVC\.venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
   ```
3. **Backend:**
   ```powershell
   $env:RVC_DIR = "C:\RVC"
   cd backend
   & "C:\RVC\.venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8080
   ```
4. **Frontend**, em outro terminal:
   ```powershell
   cd frontend
   python -m http.server 5500 --bind 127.0.0.1
   ```
   Abra `http://127.0.0.1:5500`. O endereço do backend fica em `frontend/js/config.js` (`API_URL`).
5. **Cadastrar uma voz treinada** (depois de criar a conta e assinar a autorização no app):
   ```powershell
   & "C:\RVC\.venv\Scripts\python.exe" voice_registry.py email@exemplo.com modelo.pth modelo.index --base masculina --nome "Minha voz"
   ```

Mais detalhes em `backend/LEIA-ME.md`.

## Testes

- **Backend** (na pasta `backend`, com o Python do RVC): `test_db.py`, `test_fase5.py`, `test_fase6.py`.
- **Interface** (na pasta `testes-interface`): `npm install`, `npx playwright install chromium` e `npm test`. Veja `testes-interface/LEIA-ME.md`.

## Tecnologias e licenças de terceiros

WebGazer.js (GPLv3), MediaPipe Face Mesh (Apache 2.0), RVC (MIT), FastAPI (MIT), PyTorch (BSD), gTTS (MIT), edge-tts (LGPLv3), argon2-cffi (MIT), PyJWT (MIT), cryptography (Apache/BSD), fonte Atkinson Hyperlegible (SIL OFL).

## Uso de IA generativa

O desenvolvimento contou com o apoio do assistente Claude (Anthropic), conforme declarado na seção "Uso de IA generativa" do relatório técnico.
