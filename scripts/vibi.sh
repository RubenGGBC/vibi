#!/usr/bin/env bash
# Deja Vibi en marcha: el core y el agente de nodo, cada uno con su bucle.
#
# Los dos van en la misma máquina a proposito. `agy` se lanza donde se lanza el
# core, y teniendolo aqui sus herramientas propias son tu disco de verdad.
set -uo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGDIR="${XDG_STATE_HOME:-$HOME/.local/state}/vibi"
mkdir -p "$LOGDIR"
PY="$RAIZ/.venv-host/bin/python"

if [ ! -x "$PY" ]; then
  echo "Falta $PY. Lanza el instalador otra vez." >&2
  exit 1
fi

# Un bucle por proceso: si uno muere, vuelve solo sin llevarse al otro.
bucle() {
  local nombre="$1"; shift
  while true; do
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] arrancando $nombre" >> "$LOGDIR/$nombre.log"
    "$@" >> "$LOGDIR/$nombre.log" 2>&1
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $nombre termino; reintento en 15s" >> "$LOGDIR/$nombre.log"
    sleep 15
  done
}

cd "$RAIZ" || exit 1
bucle core "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
cd "$RAIZ/agent" || exit 1
bucle nodo "$PY" -m vibi_node &

# La ventana va con los servicios: Vibi es una aplicacion, y arrancar solo el
# core dejaba al usuario con todo corriendo y nada que mirar.
APP="$HOME/.local/bin/vibi-companion"
[ -x "$APP" ] && "$APP" >/dev/null 2>&1 &

wait
