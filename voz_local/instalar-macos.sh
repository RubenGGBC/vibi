#!/bin/bash
# Instala la voz local de Vibi en un Mac con Apple Silicon (M1, M2, M3, M4...)
# y la deja siempre encendida como LaunchAgent.
#
#   ./voz_local/instalar-macos.sh            instala o actualiza
#   ./voz_local/instalar-macos.sh --quitar   la desinstala (Vibi vuelve a edge-tts)
#
# Qué deja:
#   voz_local/.venv                              entorno propio, Python 3.12
#   ~/.cache/huggingface/.../Kokoro-82M-bf16     el modelo (~330 MB)
#   ~/Library/LaunchAgents/VibiVoz.plist         el servicio, en 127.0.0.1:8932
#   ~/Library/Logs/Vibi/voz.log                  su log
#
# El core no hay que tocarlo: con `TTS_ENGINE=local` (el valor por defecto) usa
# este servicio en cuanto responde, y edge-tts mientras no.
set -euo pipefail

ETIQUETA="VibiVoz"
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"
PLIST="$HOME/Library/LaunchAgents/$ETIQUETA.plist"
LOGS="$HOME/Library/Logs/Vibi"
PUERTO="${VIBI_VOZ_PUERTO:-8932}"
DOMINIO="gui/$(id -u)"

if [[ "${1:-}" == "--quitar" ]]; then
  launchctl bootout "$DOMINIO/$ETIQUETA" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Voz local desinstalada. Vibi usa edge-tts. (El entorno sigue en $VENV.)"
  exit 0
fi

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "La voz local necesita un Mac con Apple Silicon (MLX corre en su GPU)." >&2
  exit 1
fi

echo "==> Entorno Python 3.12 en $VENV"
if command -v uv >/dev/null 2>&1; then
  [[ -x "$VENV/bin/python" ]] || uv venv -q -p 3.12 "$VENV"
  VIRTUAL_ENV="$VENV" uv pip install -q -r "$DIR/requirements.txt"
else
  PY="$(command -v python3.12 || true)"
  if [[ -z "$PY" ]]; then
    echo "Falta Python 3.12. Instala uv (curl -LsSf https://astral.sh/uv/install.sh | sh)" >&2
    echo "o python@3.12 con Homebrew, y vuelve a ejecutar esto." >&2
    exit 1
  fi
  [[ -x "$VENV/bin/python" ]] || "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r "$DIR/requirements.txt"
fi

echo "==> Descargando y probando el modelo"
"$VENV/bin/python" "$DIR/servidor.py" --descargar

echo "==> Servicio $ETIQUETA en 127.0.0.1:$PUERTO"
mkdir -p "$LOGS" "$(dirname "$PLIST")"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$ETIQUETA</string>
	<key>ProgramArguments</key>
	<array>
		<string>$VENV/bin/python</string>
		<string>$DIR/servidor.py</string>
		<string>--puerto</string>
		<string>$PUERTO</string>
	</array>
	<key>WorkingDirectory</key>
	<string>$DIR</string>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>ProcessType</key>
	<string>Interactive</string>
	<key>StandardOutPath</key>
	<string>$LOGS/voz.log</string>
	<key>StandardErrorPath</key>
	<string>$LOGS/voz.log</string>
</dict>
</plist>
PLIST
launchctl bootout "$DOMINIO/$ETIQUETA" 2>/dev/null || true
launchctl bootstrap "$DOMINIO" "$PLIST"

for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$PUERTO/salud" >/dev/null; then
    echo "Voz local lista: $(curl -s "http://127.0.0.1:$PUERTO/salud")"
    exit 0
  fi
  sleep 1
done
echo "El servicio no ha respondido en 60 s; mira $LOGS/voz.log" >&2
exit 1
