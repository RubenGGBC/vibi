"""Observación local de trabajo que solo publica señales tipadas.

Las rutas, selectores, nombres y sellos se usan dentro del nodo y nunca forman
parte del mensaje. Este módulo comparte la cadencia de las vigilancias, pero no
su serializador de texto.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, time as hora, timedelta
from pathlib import Path

from . import cdp, system_shell, web_apps
from .equipo_senales import SONDA_POR_SENAL, construir
from .fs_scope import permitida, resolver

log = logging.getLogger("vibi.node.equipo")

TIC = 1.0
MAX_ENTRADAS = 10_000


@dataclass
class Seguimiento:
    id: str
    senal: str
    sonda: str
    parametros: dict
    intervalo: float
    proxima: float = 0.0
    sello: str | None = None
    secuencia: int = 0
    sin_cambios_desde: float = 0.0
    sin_cambios_desde_real: float = 0.0
    emitida: bool = False
    referencia: str = ""
    vistos: set[str] = field(default_factory=set)
    contador: int = 0


@dataclass
class Seguimientos:
    _por_id: dict[str, Seguimiento] = field(default_factory=dict)
    _pendientes: dict[str, tuple[dict, float]] = field(default_factory=dict)

    def reemplazar(self, crudo: object) -> None:
        entrantes = crudo if isinstance(crudo, list) else []
        vistos: set[str] = set()
        for bruto in entrantes:
            if not isinstance(bruto, dict):
                continue
            identificador = str(bruto.get("id") or "")
            senal = str(bruto.get("senal") or "")
            sonda = str(bruto.get("sonda") or "")
            if (
                not identificador
                or SONDA_POR_SENAL.get(senal) != sonda
                or not isinstance(bruto.get("parametros"), dict)
            ):
                continue
            try:
                intervalo = max(2.0, float(bruto.get("intervalo") or 10.0))
            except (TypeError, ValueError):
                continue
            vistos.add(identificador)
            anterior = self._por_id.get(identificador)
            if anterior:
                # Un manifiesto aprobado es inmutable. Si el servidor cambia
                # parámetros con el mismo id, el nodo deja de observarlo hasta
                # que llegue como una propuesta nueva.
                if (
                    anterior.senal != senal
                    or anterior.sonda != sonda
                    or anterior.parametros != bruto["parametros"]
                ):
                    del self._por_id[identificador]
                    continue
                anterior.intervalo = intervalo
            else:
                self._por_id[identificador] = Seguimiento(
                    identificador, senal, sonda, dict(bruto["parametros"]), intervalo
                )
        for sobrante in set(self._por_id) - vistos:
            del self._por_id[sobrante]

    def pendientes(self, ahora: float) -> list[Seguimiento]:
        return [s for s in self._por_id.values() if ahora >= s.proxima]

    def __len__(self) -> int:
        return len(self._por_id)

    def encolar(self, mensaje: dict, ahora: float) -> None:
        self._pendientes[str(mensaje["id"])] = (mensaje, ahora)

    def confirmar(self, identificador: object) -> None:
        self._pendientes.pop(str(identificador or ""), None)

    def por_enviar(self, ahora: float) -> list[dict]:
        salida: list[dict] = []
        for identificador, (mensaje, ultimo) in list(self._pendientes.items()):
            if ultimo <= 0 or ahora - ultimo >= 5.0:
                self._pendientes[identificador] = (mensaje, ahora)
                salida.append(mensaje)
        return salida


def _sello_archivo(ruta_cruda: object) -> tuple[str, bool]:
    ruta = resolver(ruta_cruda)
    if not ruta.exists():
        return "ausente", False
    if ruta.is_file():
        info = ruta.stat()
        crudo = f"f:{info.st_mtime_ns}:{info.st_size}"
        return hashlib.sha256(crudo.encode()).hexdigest(), True
    if not ruta.is_dir():
        return "otro", True

    piezas: list[str] = []
    raiz = Path(ruta)
    for directorio, carpetas, archivos in os.walk(raiz, followlinks=False):
        base = Path(directorio)
        carpetas[:] = sorted(
            nombre for nombre in carpetas
            if permitida(base / nombre) and not (base / nombre).is_symlink()
        )
        for nombre in sorted(archivos):
            archivo = base / nombre
            if not permitida(archivo):
                continue
            try:
                info = archivo.stat()
                relativo = archivo.relative_to(raiz)
                piezas.append(f"{relativo}:{info.st_mtime_ns}:{info.st_size}")
            except (OSError, ValueError):
                continue
            if len(piezas) >= MAX_ENTRADAS:
                piezas.append("limite")
                break
        if len(piezas) >= MAX_ENTRADAS:
            break
    return hashlib.sha256("\n".join(piezas).encode("utf-8", "ignore")).hexdigest(), True


def _segundos_de_trabajo(desde: float, hasta: float) -> float:
    """Tiempo transcurrido sin contar las noches locales de 00:00 a 08:00."""
    if hasta <= desde:
        return 0.0
    nocturnos = 0.0
    dia = datetime.fromtimestamp(desde).date()
    ultimo = datetime.fromtimestamp(hasta).date()
    while dia <= ultimo:
        inicio_noche = datetime.combine(dia, hora.min).astimezone().timestamp()
        fin_noche = datetime.combine(dia, hora(hour=8)).astimezone().timestamp()
        nocturnos += max(0.0, min(hasta, fin_noche) - max(desde, inicio_noche))
        dia += timedelta(days=1)
    return max(0.0, hasta - desde - nocturnos)


def _sello_ultima_linea(trabajo_id: str) -> str:
    salida = str(system_shell.salida(trabajo_id).get("salida") or "")
    lineas = [linea.strip() for linea in salida.splitlines() if linea.strip()]
    ultima = lineas[-1] if lineas else "sin-salida"
    return hashlib.sha256(ultima.encode("utf-8", "ignore")).hexdigest()


def _estado_trabajo(identificador: object) -> dict:
    buscado = str(identificador or "")
    for trabajo in system_shell.trabajos().get("trabajos", []):
        if str(trabajo.get("trabajo")) == buscado:
            return trabajo
    raise ValueError("El trabajo supervisado ya no existe")


async def _predicado_web(parametros: dict) -> bool:
    app = str(parametros.get("app") or "").strip()
    puerto = parametros.get("puerto")
    puerto = int(puerto) if puerto else web_apps.puerto_de(app)
    if not puerto:
        raise ValueError("No hay puerto para la aplicación web")
    selector = str(parametros.get("selector") or "").strip()
    if not selector:
        raise ValueError("Falta el selector aprobado")
    script = f"Boolean(document.querySelector({json.dumps(selector)}))"
    valor, _pagina = await cdp.evaluar_en(
        puerto, str(parametros.get("pestana") or "").strip() or None, script
    )
    return bool(valor)


async def observar(seguimiento: Seguimiento, ahora: float) -> tuple[bool, dict]:
    """Devuelve si hay que emitir y el único payload permitido."""
    if seguimiento.senal in {"avance", "sin_avance", "entregado"}:
        sello, existe = await asyncio.to_thread(
            _sello_archivo, seguimiento.parametros.get("ruta")
        )
        anterior = seguimiento.sello
        seguimiento.sello = sello
        if anterior is None:
            seguimiento.sin_cambios_desde = ahora
            seguimiento.sin_cambios_desde_real = time.time()
            return False, {}
        if seguimiento.senal == "entregado":
            return anterior == "ausente" and existe, {}
        if sello != anterior:
            seguimiento.sin_cambios_desde = ahora
            seguimiento.sin_cambios_desde_real = time.time()
            seguimiento.emitida = False
            return seguimiento.senal == "avance", {}
        if seguimiento.senal == "sin_avance" and not seguimiento.emitida:
            try:
                horas = max(0.01, float(seguimiento.parametros.get("horas", 8)))
            except (TypeError, ValueError):
                horas = 8.0
            desde_real = seguimiento.sin_cambios_desde_real or time.time()
            if _segundos_de_trabajo(desde_real, time.time()) >= horas * 3600:
                seguimiento.emitida = True
                return True, {"horas": horas}
        return False, {}

    if seguimiento.senal == "tarea_larga":
        trabajo = await asyncio.to_thread(
            _estado_trabajo, seguimiento.parametros.get("trabajo")
        )
        minutos = max(0.1, float(seguimiento.parametros.get("minutos", 30)))
        emitir = (
            not seguimiento.emitida
            and not trabajo.get("terminado")
            and float(trabajo.get("segundos") or 0) >= minutos * 60
        )
        seguimiento.emitida = seguimiento.emitida or emitir
        return emitir, {"minutos": minutos}

    if seguimiento.senal == "fallo_repetido":
        trabajos = await asyncio.to_thread(system_shell.trabajos)
        lista = trabajos.get("trabajos", [])
        if not seguimiento.referencia:
            inicial = next(
                (
                    t for t in lista
                    if str(t.get("trabajo")) == str(seguimiento.parametros.get("trabajo"))
                ),
                None,
            )
            if inicial is None:
                raise ValueError("El trabajo de referencia ya no existe")
            seguimiento.referencia = hashlib.sha256(
                str(inicial.get("comando") or "").encode("utf-8", "ignore")
            ).hexdigest()
        for trabajo in lista:
            identidad = str(trabajo.get("trabajo") or "")
            sello_comando = hashlib.sha256(
                str(trabajo.get("comando") or "").encode("utf-8", "ignore")
            ).hexdigest()
            if (
                identidad not in seguimiento.vistos
                and sello_comando == seguimiento.referencia
                and trabajo.get("terminado")
            ):
                seguimiento.vistos.add(identidad)
                if trabajo.get("codigo") not in (None, 0):
                    sello_error = _sello_ultima_linea(identidad)
                    if seguimiento.sello == sello_error:
                        seguimiento.contador += 1
                    else:
                        seguimiento.sello = sello_error
                        seguimiento.contador = 1
        veces = max(1, int(seguimiento.parametros.get("veces", 1)))
        emitir = not seguimiento.emitida and seguimiento.contador >= veces
        seguimiento.emitida = seguimiento.emitida or emitir
        return emitir, {"veces": seguimiento.contador}

    if seguimiento.senal in {"revision_pendiente", "integracion_rota"}:
        activo = await _predicado_web(seguimiento.parametros)
        anterior = seguimiento.sello
        seguimiento.sello = "si" if activo else "no"
        return anterior == "no" and activo, {}
    return False, {}


async def vigilar(connection, seguimientos: Seguimientos) -> None:
    while True:
        ahora = time.monotonic()
        # Hasta recibir el ACK se reintenta. El servidor deduplica por UUID y
        # secuencia, así que perder la respuesta no duplica evidencia.
        for mensaje in seguimientos.por_enviar(ahora):
            await connection.send(json.dumps(mensaje))
        for seguimiento in seguimientos.pendientes(ahora):
            seguimiento.proxima = ahora + seguimiento.intervalo
            try:
                emitir, payload = await observar(seguimiento, ahora)
                if not emitir:
                    continue
                seguimiento.secuencia += 1
                mensaje = construir(
                    seguimiento.id, seguimiento.senal,
                    seguimiento.secuencia, payload,
                )
                seguimientos.encolar(mensaje, ahora)
                await connection.send(json.dumps(mensaje))
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - un seguimiento no mata otros
                log.warning("No pude observar %s: %s", seguimiento.id, error)
                seguimiento.proxima = ahora + 30.0
        await asyncio.sleep(TIC)
