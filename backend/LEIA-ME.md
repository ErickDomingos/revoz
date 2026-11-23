# Backend (SCOM)

## Rodar (uma vez)
    py -3.12 -m venv .venv
    .venv\Scripts\activate
    python -m pip install -r requirements.txt

No .venv do RVC (onde o servidor roda de verdade) instalem só o que falta:
    python -m pip install PyJWT argon2-cffi cryptography gTTS
(numpy e soundfile já vêm com o RVC; não usem --upgrade para não quebrar o RVC)

## Subir a API
    python -m uvicorn main:app --reload --port 8080
Teste em http://127.0.0.1:8080/docs. Com o RVC, rodem sem --reload (ver rvc_service.py).

## Fase 5 — segurança e privacidade

### Primeira vez depois de atualizar
1. Criptografar os modelos que já existem em voice_models/ (apaga os originais abertos):
       python voice_registry.py criptografar
2. Guardem uma cópia de data/model.key FORA do projeto. Sem essa chave os modelos
   criptografados não abrem mais. Em produção, usem a variável APPVOICE_MODEL_KEY.

### Fluxo para ter uma voz clonada
1. Criar conta e entrar (aba Ajustes / tela de login).
2. Aba Vozes > "Cadastrar minha voz": enviar os áudios e assinar o consentimento
   (camada 1: senha + nome + relação; camada 2: os 4 usos autorizados).
3. Treinar o .pth (Fase 3) e cadastrar:
       python voice_registry.py <email> "C:\caminho\modelo.pth" "C:\caminho\modelo.index"
   Sem consentimento válido o cadastro é recusado.

### Rotas novas
| Rota | O que faz |
|---|---|
| POST /amostras | envia um áudio (corpo = o arquivo, Content-Type audio/...); gravado cifrado |
| GET /amostras, DELETE /amostras/{id} | lista / apaga as próprias amostras |
| GET /consentimento/texto | texto e versão do termo |
| POST /consentimento | registra o consentimento em duas camadas |
| GET /consentimento | status (válido ou não) |
| DELETE /consentimento?apagar_dados=true | revoga (e opcionalmente apaga amostras e modelos) |
| POST /vinculos, GET /vinculos, POST /vinculos/status | cuidador pede, paciente aprova/revoga |
| DELETE /vozes/{id} | dono apaga a própria voz |
| GET /auditoria | o que foi feito com a conta e com as vozes do usuário |

Cuidador age em nome do paciente mandando `paciente_id` (só com vínculo ativo).

### Marca d'água
Todo áudio com voz clonada sai com uma marca na faixa de ~16,7–19 kHz que
carrega o número do registro de auditoria. Para conferir um arquivo:
    python watermark.py arquivo.wav

### Testes
    python test_db.py       (camada de dados)
    python test_fase5.py    (Fase 5 inteira, com banco e pastas temporários)
    python test_fase6.py    (Fase 6 inteira, com banco e pastas temporários)

Header de resposta X-Voz: generica | generica-sem-consentimento | generica-rvc-pendente | clonada.

## Fase 6 — banco de dados e armazenamento

Detalhes, diagrama das tabelas e dicionário de dados: `docs/banco-de-dados.md`.

### Rotas novas
| Rota | O que faz |
|---|---|
| PUT /vozes/ativa | escolhe a voz em uso (`voice_id: null` = voz genérica); fica guardada na conta |
| GET /frases, PUT /frases | frases da grade do modo Olhar (1 a 12, cada uma até 300 caracteres) |
| GET /historico, POST /historico, DELETE /historico | frases recentes do modo Digitar |
| GET /conta/dados | baixa em JSON tudo o que o banco guarda sobre a conta |
| POST /conta/excluir | apaga conta, áudios e modelos (corpo: `{"senha": "..."}`) |

`POST /gerar-audio` ganhou dois campos opcionais: `historico` (guarda a frase nas recentes)
e `generica` (força a voz genérica, usado no botão "Ouvir" da voz genérica).

Na subida, o servidor apaga sobras de conversões interrompidas (arquivos `appvoice_*`
na pasta temporária, que podem incluir um modelo aberto).

## Vozes genéricas e treino da voz própria

### Voz genérica masculina
A feminina usa o gTTS. A masculina usa o edge-tts (voz pt-BR-AntonioNeural). No .venv do RVC:
    python -m pip install edge-tts
(sem --upgrade). Sem o edge-tts, a masculina sai com a voz feminina e o cabeçalho
`X-Voz-Base` mostra qual voz saiu de fato. Rotas: `GET /vozes/generica` e
`PUT /vozes/ativa` com `{"voice_id": null, "generica": "masculina"}`.

### Do áudio da pessoa até a voz clonada
1. A pessoa envia os áudios e assina na aba Consentimento do app.
2. No servidor: `python treino.py exportar <email> <pasta>` (abre só os áudios autorizados).
3. A pasta vai para a máquina com GPU por um meio privado; lá, aba "Treinar" do RVC.
4. Com o .pth e o .index prontos, no servidor:
       python voice_registry.py <email> modelo.pth modelo.index --base masculina --nome "Voz do Leo"
   `--base` é a voz genérica que o RVC converte: use o mesmo gênero da voz treinada.
5. Apaguem as cópias abertas: `python treino.py apagar <pasta>` (e na máquina com GPU).

## Não commitar
voice_models/, amostras/ e data/ (modelos e áudios são dados biométricos;
data/ tem as chaves) — já estão no .gitignore.
Também não mandem essas pastas por zip ou Drive: quem tem data/model.key junto com
os .enc consegue abrir os áudios e os modelos.
