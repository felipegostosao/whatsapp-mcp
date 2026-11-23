#!/bin/bash
# Liga a transcrição automática de áudios como serviço do macOS: roda a cada minuto e no login.
# Uso: ./servico-transcricao.sh   (precisa de whisper-cli, ffmpeg e um modelo ggml; ver GUIA.md)
# Erros: tail -f ~/Library/Logs/whatsapp-transcricao.log
set -eu
PASTA="$(cd "$(dirname "$0")" && pwd -P)"
ROTULO=com.whatsapp-mcp.transcricao
PLIST="$HOME/Library/LaunchAgents/$ROTULO.plist"
LOG="$HOME/Library/Logs/whatsapp-transcricao.log"
INTERVALO="${WA_INTERVALO:-60}"


launchctl bootout "gui/$(id -u)/$ROTULO" 2>/dev/null || true
mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$ROTULO</string>
  <key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>$PASTA/transcrever-audios.py</string></array>
  <key>StartInterval</key><integer>$INTERVALO</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "transcrição automática ligada ($ROTULO), a cada $INTERVALO s. Log: $LOG"
