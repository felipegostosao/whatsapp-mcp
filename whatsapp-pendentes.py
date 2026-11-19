#!/usr/bin/env python3
"""Mostra no Knobler quem mandou mensagem no WhatsApp e está sem resposta,
e envia pelo WhatsApp o que você digitar no cartão.

Sem IA: lê o banco local da ponte, abre um cartão por conversa no Knobler
(localhost:4477/ask) e espera a resposta em segundo plano. Texto digitado
vai pela ponte (localhost:8099/api/send). "Ignorar" fecha sem enviar.
Knobler fechado: cai para a notificação comum do macOS.
"""
import sqlite3, subprocess, json, os, sys, time, datetime as dt, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DB = f"{BASE}/whatsapp-bridge/store/messages.db"
ESTADO = f"{BASE}/.pendentes-estado.json"
KNOBLER = f"http://localhost:{os.getenv('KNOBLER_PORT', '4477')}"
PONTE = "http://localhost:8099/api/send"
JANELA_PADRAO_MIN = 20
NOME = os.getenv("WA_NOME", "o dono do número")  # como chamar você no prompt da sugestão
ESPERA_MAX_H = 12
IGNORAR = "Ignorar"

def agora():
    return dt.datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")

def ler_estado():
    try:
        with open(ESTADO) as f:
            e = json.load(f)
    except Exception:
        e = {}
    e.setdefault("ultimo", (dt.datetime.now().astimezone()
                            - dt.timedelta(minutes=JANELA_PADRAO_MIN)).isoformat(sep=" ", timespec="seconds"))
    e.setdefault("abertos", {})
    return e

def gravar_estado(e):
    with open(ESTADO, "w") as f:
        json.dump(e, f)

def http(metodo, url, corpo=None, timeout=3, headers=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        txt = r.read().decode()
        return json.loads(txt) if txt.strip() else {}

def notificar_mac(titulo, texto):
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(["osascript", "-e",
        f'display notification "{esc(texto)}" with title "{esc(titulo)}" sound name "Glass"'])

def pendentes(desde):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    chats = con.execute("""
        WITH ultima AS (
          SELECT chat_jid, is_from_me, timestamp,
                 ROW_NUMBER() OVER (PARTITION BY chat_jid ORDER BY timestamp DESC) rn
          FROM messages
          WHERE chat_jid NOT LIKE '%@g.us' AND chat_jid NOT LIKE '%@broadcast'
            AND chat_jid NOT LIKE '%@newsletter'
        )
        SELECT u.chat_jid, COALESCE(c.name, u.chat_jid)
        FROM ultima u LEFT JOIN chats c ON c.jid = u.chat_jid
        WHERE u.rn = 1 AND u.is_from_me = 0 AND u.timestamp > ?
        ORDER BY u.timestamp DESC
    """, (desde,)).fetchall()
    res = []
    for jid, nome in chats:
        msgs = con.execute("""
            SELECT content, media_type, timestamp FROM messages
            WHERE chat_jid = ? AND is_from_me = 0 AND timestamp > COALESCE(
              (SELECT MAX(timestamp) FROM messages WHERE chat_jid = ? AND is_from_me = 1), '')
            ORDER BY timestamp DESC LIMIT 4
        """, (jid, jid)).fetchall()[::-1]
        linhas = [t[11:16] + "  " + (c or "[" + (m or "mídia") + "]").strip()[:300] for c, m, t in msgs]
        res.append((jid, nome, "\n".join(linhas)))
    con.close()
    return res

REGRAS = f"{BASE}/regras-respostas.md"
ENVIAR_SUG = "Enviar sugestão"

def historico(jid, n=20):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute("SELECT timestamp, is_from_me, content, media_type FROM messages "
                       "WHERE chat_jid = ? ORDER BY timestamp DESC LIMIT ?", (jid, n)).fetchall()[::-1]
    con.close()
    return "\n".join(f"{t[5:16]} {NOME if eu else 'Contato'}: "
                     + (c or "[" + (m or "mídia") + "]").strip()[:400] for t, eu, c, m in rows)

def sugerir(jid, nome):
    try:
        regras = open(REGRAS).read()
    except Exception:
        regras = ""
    prompt = (f"{regras}\n\nConversa de WhatsApp de {NOME} com {nome} ({jid.split('@')[0]}):\n\n"
              f"{historico(jid)}\n\nEscreva só o texto da resposta que {NOME} mandaria agora, "
              "sem aspas nem explicação. Se não precisa responder, escreva SEM_RESPOSTA.")
    try:
        # sem hooks nem MCP: hooks (deja, graft...) injetavam texto na resposta
        r = subprocess.run([os.path.expanduser("~/.local/bin/claude"), "-p", "--model", "sonnet",
                            "--strict-mcp-config", "--settings", '{"disableAllHooks":true}', prompt],
                           capture_output=True, text=True, timeout=180, cwd="/tmp")
        lixo = ("déjà vu", "deja:", "graft", "🌱", "[trail]")
        s = "\n".join(l for l in r.stdout.splitlines()
                      if not any(x in l.lower() for x in lixo)).strip()
        return None if not s or "SEM_RESPOSTA" in s else s
    except Exception:
        return None

def abrir_cartao(jid, nome, texto):
    """Dispara em segundo plano: gera a sugestão, abre o cartão e espera."""
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "cartao", jid, nome, texto],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return "gerando"

def cartao(jid, nome, texto):
    sug = sugerir(jid, nome)
    cid = f"wa-{abs(hash(jid)) % 10**8}-{int(time.time())}"
    pergunta = f"{nome} no WhatsApp:\n\n{texto}\n\n"
    opcoes = []
    if sug:
        pergunta += f"Sugestão de resposta:\n{sug}\n\nEnvie a sugestão, ou digite outra resposta."
        opcoes.append({"label": ENVIAR_SUG, "description": sug[:200]})
    else:
        pergunta += "Sem sugestão (parece não precisar de resposta). Digite se quiser responder."
    opcoes.append({"label": IGNORAR, "description": "Fecha o cartão sem responder."})
    try:
        http("POST", f"{KNOBLER}/ask", {"id": cid, "source": "WhatsApp", "questions": [{
            "question": pergunta, "header": "WhatsApp", "multiSelect": False, "options": opcoes}]}, timeout=2)
    except Exception:
        notificar_mac(f"WhatsApp: {nome}", texto.split("\n")[-1][7:120])
        e = ler_estado(); e["abertos"].pop(jid, None); gravar_estado(e)
        return
    esperar(cid, jid, pergunta, sug)

def esperar(cid, jid, pergunta, sug=None):
    fim = time.time() + ESPERA_MAX_H * 3600
    while time.time() < fim:
        try:
            st = http("GET", f"{KNOBLER}/ask/{cid}", timeout=30, headers={"X-Knobler-Wait": "25"})
        except Exception:
            time.sleep(10)
            continue
        if st.get("cancelled"):
            break
        if st.get("answered"):
            ans = (st.get("answers") or {}).get(pergunta) or next(iter((st.get("answers") or {}).values()), {})
            texto = (ans.get("text") or "").strip()
            if not texto and sug and ENVIAR_SUG in (ans.get("labels") or []):
                texto = sug
            if texto:
                try:
                    r = http("POST", PONTE, {"recipient": jid, "message": texto}, timeout=20)
                    if not r.get("success", True):
                        notificar_mac("WhatsApp: não enviou", r.get("message", "erro na ponte"))
                except Exception as e:
                    notificar_mac("WhatsApp: não enviou", str(e)[:120])
            break
        time.sleep(1)
    else:
        try:
            http("POST", f"{KNOBLER}/ask/{cid}/cancel", {}, timeout=2)
        except Exception:
            pass
    e = ler_estado()
    e["abertos"].pop(jid, None)
    gravar_estado(e)

def principal():
    e = ler_estado()
    momento = agora()
    lista = pendentes(e["ultimo"])
    sem_knobler = []
    for jid, nome, texto in lista:
        if jid in e["abertos"]:
            continue  # já tem cartão aberto para essa conversa
        try:
            e["abertos"][jid] = abrir_cartao(jid, nome, texto)
        except Exception:
            sem_knobler.append((nome, texto))
    if sem_knobler:
        if len(sem_knobler) == 1:
            notificar_mac(f"WhatsApp: {sem_knobler[0][0]}", sem_knobler[0][1].split("\n")[-1][7:120])
        else:
            nomes = [n for n, _ in sem_knobler]
            notificar_mac(f"WhatsApp: {len(nomes)} conversas sem resposta",
                          ", ".join(nomes[:6]) + ("…" if len(nomes) > 6 else ""))
    e["ultimo"] = momento
    gravar_estado(e)

if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "cartao":
        cartao(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        principal()
