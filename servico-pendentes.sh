#!/bin/bash
# Liga o aviso de pendentes como serviço do macOS: roda a cada 20 min e no login.
# Uso: WA_NOME="Seu Nome" ./servico-pendentes.sh   (rode de novo para mudar algo)
# Erros: tail -f ~/Library/Logs/whatsapp-pendentes.log
set -eu
PASTA="$(cd "$(dirname "$0")" && pwd -P)"
ROTULO=com.whatsapp-mcp.pendentes
PLIST="$HOME/Library/LaunchAgents/$ROTULO.plist"
LOG="$HOME/Library/Logs/whatsapp-pendentes.log"
NOME="${WA_NOME:-o dono do número}"
INTERVALO="${WA_INTERVALO:-1200}"

# regras pessoais ficam fora do git; começa pelo exemplo
[ -f "$PASTA/regras-respostas.md" ] || cp "$PASTA/regras-respostas.exemplo.md" "$PASTA/regras-respostas.md"

launchctl bootout "gui/$(id -u)/$ROTULO" 2>/dev/null || true
mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$ROTULO</string>
  <key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>$PASTA/whatsapp-pendentes.py</string></array>
  <key>EnvironmentVariables</key><dict><key>WA_NOME</key><string>$NOME</string></dict>
  <key>StartInterval</key><integer>$INTERVALO</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "aviso de pendentes ligado ($ROTULO), a cada $INTERVALO s. Log: $LOG"
