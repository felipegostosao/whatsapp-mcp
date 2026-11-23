#!/usr/bin/env python3
"""Transcreve sozinho os áudios das conversas individuais, de graça e no próprio Mac.

Roda a cada minuto (servico-transcricao.sh). Para cada áudio sem texto:
baixa pela ponte (POST /api/download), converte com ffmpeg e transcreve com
whisper.cpp (whisper-cli) em português. O texto vai para a mensagem no banco,
como "🎤 <transcrição>", e assim aparece no MCP, nas revisões e nos cartões do Knobler.

As transcrições também ficam na tabela `transcricoes`: se a ponte regravar a
mensagem (sincronização de histórico), o texto é reposto na volta seguinte.
"""
import sqlite3, subprocess, json, os, sys, time, tempfile, fcntl, urllib.request, datetime as dt

BASE = os.path.dirname(os.path.abspath(__file__))
DB = f"{BASE}/whatsapp-bridge/store/messages.db"
PONTE = "http://localhost:8099/api/download"
MODELO = os.path.expanduser(os.getenv("WHISPER_MODELO", "~/.whisper-models/ggml-large-v3-turbo.bin"))
WHISPER = os.getenv("WHISPER_CLI", "/opt/homebrew/bin/whisper-cli")
FFMPEG = os.getenv("FFMPEG", "/opt/homebrew/bin/ffmpeg")
DIAS = int(os.getenv("TRANSCREVER_DIAS", "3"))       # só áudios recentes
POR_RODADA = int(os.getenv("TRANSCREVER_MAX", "20"))  # limite por execução
PREFIXO = "🎤 "
LOG = os.path.expanduser("~/Library/Logs/whatsapp-transcricao.log")
TRAVA = f"{BASE}/.transcricao.lock"


def log(*a):
    with open(LOG, "a") as f:
        f.write(dt.datetime.now().strftime("%m-%d %H:%M:%S ") + " ".join(str(x) for x in a) + "\n")


def conectar():
    con = sqlite3.connect(DB, timeout=30)
    con.execute("""CREATE TABLE IF NOT EXISTS transcricoes (
        id TEXT, chat_jid TEXT, texto TEXT, criado TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id, chat_jid))""")
    return con


def repor(con):
    """Devolve o texto às mensagens que a ponte regravou sem ele."""
    con.execute(f"""UPDATE messages SET content = '{PREFIXO}' || (
            SELECT texto FROM transcricoes t WHERE t.id = messages.id AND t.chat_jid = messages.chat_jid)
        WHERE media_type = 'audio' AND COALESCE(content, '') = ''
          AND EXISTS (SELECT 1 FROM transcricoes t WHERE t.id = messages.id AND t.chat_jid = messages.chat_jid)""")
    con.commit()


def transcrever(caminho):
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "a.wav")
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", caminho, "-ar", "16000", "-ac", "1", wav],
                       check=True, timeout=120)
        saida = os.path.join(tmp, "t")
        subprocess.run([WHISPER, "-m", MODELO, "-l", "pt", "-nt", "-np", "-f", wav, "-otxt", "-of", saida],
                       check=True, timeout=600, capture_output=True)
        with open(saida + ".txt") as f:
            return " ".join(l.strip() for l in f if l.strip())


def baixar(msg_id, chat):
    req = urllib.request.Request(PONTE, data=json.dumps({"message_id": msg_id, "chat_jid": chat}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read().decode())
    if not resp.get("success"):
        raise RuntimeError(resp.get("message"))
    return resp["path"]


def principal():
    trava = open(TRAVA, "w")
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # rodada anterior ainda transcrevendo
    con = conectar()
    repor(con)
    desde = (dt.datetime.now().astimezone() - dt.timedelta(days=DIAS)).isoformat(sep=" ", timespec="seconds")
    fila = con.execute("""
        SELECT m.id, m.chat_jid FROM messages m
        WHERE m.media_type = 'audio' AND COALESCE(m.content, '') = ''
          AND m.chat_jid NOT LIKE '%@g.us' AND m.chat_jid NOT LIKE '%@broadcast'
          AND m.chat_jid NOT LIKE '%@newsletter'
          AND m.timestamp > ?
          AND NOT EXISTS (SELECT 1 FROM transcricoes t WHERE t.id = m.id AND t.chat_jid = m.chat_jid)
        ORDER BY m.timestamp DESC LIMIT ?""", (desde, POR_RODADA)).fetchall()
    for msg_id, chat in fila:
        inicio = time.time()
        try:
            texto = transcrever(baixar(msg_id, chat)) or "(áudio sem fala)"
        except Exception as e:
            log("falhou", chat, msg_id, str(e)[:200])
            # marca para não tentar para sempre um áudio que não baixa mais
            texto = "(não foi possível transcrever)"
        con.execute("INSERT OR REPLACE INTO transcricoes (id, chat_jid, texto) VALUES (?, ?, ?)", (msg_id, chat, texto))
        con.execute("UPDATE messages SET content = ? WHERE id = ? AND chat_jid = ?", (PREFIXO + texto, msg_id, chat))
        con.commit()
        log("ok", chat, msg_id, f"{time.time() - inicio:.1f}s", texto[:80])
    con.close()


if __name__ == "__main__":
    principal()
