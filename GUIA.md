# Guia de uso: WhatsApp no Claude + avisos no Knobler

Este repositório junta duas coisas:

1. **O MCP do WhatsApp** (base do [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp)):
   deixa o Claude ler, buscar e enviar mensagens do seu WhatsApp pessoal.
2. **O aviso de pendentes** (`whatsapp-pendentes.py`): a cada 20 minutos procura quem te
   mandou mensagem e está sem resposta, e abre um cartão no Knobler com a mensagem e uma
   sugestão de resposta. Você envia a sugestão, digita outra ou ignora, sem abrir o celular.

Tudo roda no seu Mac. As mensagens ficam num banco SQLite local e só vão para o Claude
quando ele consulta (ou quando o aviso gera uma sugestão).

---

## Como as peças se encaixam

```
WhatsApp (celular)
      │  aparelho conectado, igual ao WhatsApp Web
      ▼
whatsapp-bridge  (Go, serviço do macOS, porta 8099)
      │  grava tudo em whatsapp-bridge/store/messages.db
      │  envia mensagens por POST /api/send
      ├──────────────► whatsapp-mcp-server (Python) ──► Claude Code / Claude Desktop
      │                  ferramentas: list_chats, list_messages, send_message...
      │
      └──────────────► whatsapp-pendentes.py (a cada 20 min)
                         lê o banco ─► pede sugestão ao `claude -p`
                         ─► cartão no Knobler (localhost:4477/ask)
                         ─► resposta escolhida volta pela ponte
```

| Peça | O que faz | Onde |
|---|---|---|
| Ponte | Mantém a conexão com o WhatsApp, guarda mensagens, expõe a API de envio | `whatsapp-bridge/` |
| Servidor MCP | Dá as ferramentas de WhatsApp ao Claude | `whatsapp-mcp-server/` |
| Aviso de pendentes | Detecta conversas sem resposta e abre cartões no Knobler | `whatsapp-pendentes.py` |
| Transcrição de áudios | Transcreve áudios recebidos e enviados, no Mac, a cada minuto | `transcrever-audios.py` |
| Regras de resposta | Tom de voz e regras por contato usadas na sugestão | `regras-respostas.md` (pessoal, fora do git) |
| Estilo de escrita | Referência de tom para o Claude ao escrever por você | `ESTILO.md` |

---

## Instalação (macOS)

Pré-requisitos: Go, Python 3, [uv](https://docs.astral.sh/uv/), Claude Code instalado e logado
(`claude` no terminal) e, para os cartões, o app Knobler aberto.

### 1. Ponte e QR code

```bash
git clone <este repositório> ~/Code/whatsapp-mcp
cd ~/Code/whatsapp-mcp/whatsapp-bridge
go run main.go
```

Aparece um QR code. No celular: **WhatsApp → Configurações → Aparelhos conectados →
Conectar um aparelho**. Espere a mensagem `Successfully paired` e o histórico baixar,
depois pare com **Ctrl+C**.

> Leia o QR com a ponte rodando no terminal, nunca com o serviço ligado: o serviço
> roda sem tela e o QR fica escondido no log.

### 2. Ponte como serviço (roda sem terminal aberto)

```bash
./servico.sh
```

Liga no login e volta sozinha se cair. Log: `~/Library/Logs/whatsapp-bridge.log`.
Rode de novo sempre que mudar o código da ponte (ele recompila).

### 3. MCP no Claude Code

```bash
claude mcp add whatsapp -s user -- uv --directory ~/Code/whatsapp-mcp/whatsapp-mcp-server run main.py
```

No Claude Desktop, use o bloco `mcpServers` do README original.

### 4. Aviso de pendentes no Knobler

```bash
cd ~/Code/whatsapp-mcp
WA_NOME="Seu Nome" ./servico-pendentes.sh
```

Na primeira vez ele cria `regras-respostas.md` a partir de `regras-respostas.exemplo.md`.
Edite esse arquivo com seu jeito de escrever e as regras por contato.

Opcional: `WA_INTERVALO=600` muda o intervalo (em segundos).

### 5. Transcrição automática de áudios (grátis, offline)

A transcrição nativa do WhatsApp é feita no celular e não viaja com a mensagem: a ponte
recebe só o arquivo `.ogg`. Por isso transcrevemos no próprio Mac com o whisper.cpp.

```bash
brew install whisper-cpp ffmpeg
mkdir -p ~/.whisper-models
curl -L -o ~/.whisper-models/ggml-large-v3-turbo.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
./servico-transcricao.sh
```

A cada minuto, todo áudio novo de conversa individual (grupos ficam de fora) é baixado,
transcrito em português e gravado na mensagem como `🎤 <texto>`. Assim o Claude, as
revisões e os cartões do Knobler entendem o que foi dito. Um áudio de 1 minuto leva
poucos segundos. Nada sai do Mac e não há custo.

Ajustes: `TRANSCREVER_DIAS` (padrão 3, só áudios recentes), `WHISPER_MODELO`.
Log: `~/Library/Logs/whatsapp-transcricao.log`.

---

## Uso no dia a dia

**Pelo Claude**, em linguagem normal:
- "O que chegou de novo no WhatsApp hoje?"
- "Revisa as conversas das últimas 48 horas e vê quem ficou sem resposta."
- "Lê a conversa com o fulano e sugere uma resposta."

O Claude só olha o WhatsApp quando você pede, e mostra o texto antes de enviar.

**Pelo Knobler**, sem pedir nada: a cada 20 minutos, cada conversa nova sem resposta vira
um cartão com as últimas mensagens da pessoa e uma sugestão. No cartão:
- **Enviar sugestão**: manda o texto como está;
- **digitar**: manda o que você escreveu no lugar;
- **Ignorar**: fecha sem enviar.

Se o Knobler estiver fechado, vira notificação comum do macOS.

### Regras do aviso
- Só conversas individuais. Grupos, listas de transmissão e canais ficam de fora.
- "Sem resposta" = a última mensagem da conversa é da outra pessoa e chegou depois da checagem anterior.
- Um cartão por conversa por vez. Cartão ignorado some sozinho em 12 horas.
- Propaganda e avisos automáticos chegam sem sugestão.

---

## O que mudamos em relação ao original

- **A ponte grava o que é enviado pela API** (`sendWhatsAppMessage` em `whatsapp-bridge/main.go`).
  Antes, só as mensagens enviadas pelo celular apareciam no banco. As enviadas pelo Claude
  ou pelo Knobler sumiam, e a conversa continuava parecendo sem resposta.
- **Serviço do macOS para a ponte** (`servico.sh`).
- **Aviso de pendentes com sugestão no Knobler** (`whatsapp-pendentes.py`, `servico-pendentes.sh`).
- A sugestão roda `claude -p` **sem hooks nem MCP** (`--settings '{"disableAllHooks":true}'
  --strict-mcp-config`), numa pasta neutra. Plugins com hook (ex.: os que injetam histórico de
  sessões) colavam texto extra na resposta, e esse texto chegou a ser enviado a um contato.
  Por segurança há também um filtro que remove linhas desse tipo antes de mostrar o cartão.

---

## Limitações conhecidas

- **Histórico antigo é parcial.** Ao conectar, o WhatsApp manda só uma parte. Do momento da
  conexão em diante o registro é completo, enquanto a ponte estiver ligada.
- **Alguns contatos aparecem como número** (ex.: `51681425408170@lid`). É o código interno
  do WhatsApp e a ponte nem sempre consegue traduzir para o nome.
- **A sessão expira** depois de algumas semanas. Para reconectar: pare o serviço
  (`launchctl bootout gui/$(id -u)/com.whatsapp-mcp.bridge`), leia o QR com `go run main.go`
  e ligue de novo com `./servico.sh`.
- **O Mac precisa estar ligado.** Com ele dormindo, as mensagens entram quando acordar.
- **Nunca rode duas pontes com a mesma sessão**: uma derruba a outra.
- **Envio pelo Knobler é direto**, sem segunda confirmação.

## Arquivos que NÃO vão para o git

`whatsapp-bridge/store/` (sessão e mensagens), `regras-respostas.md` (regras pessoais),
`.pendentes-estado.json`, logs e o binário compilado. A pasta `store/` dá acesso total
à sua conta de WhatsApp: nunca compartilhe.
