"""Configuración persistente, temas de color y constantes del cliente."""
import copy
import json
import os
import re

VERSION = "1.2.0"
CONFIG_VER = 2   # sube cuando cambie el formato/diseño y haya que migrar ajustes viejos

# Comandos propios del cliente: un alias no puede usar estos nombres.
COMANDOS_INTERNOS = {
    "join", "part", "msg", "query", "nick", "me", "quit", "raw", "close",
    "clear", "topic", "whois", "notice", "away", "kick", "mode", "ayuda", "help",
}

TEMAS = {
    "iOS Claro": {
        "bg": "#F2F2F7", "fg": "#000000", "campo": "#FFFFFF", "campo_fg": "#000000",
        "acento": "#007AFF", "hora": "#8E8E93", "sistema": "#8E8E93", "aviso": "#FF3B30",
        "accion": "#AF52DE", "enlace": "#007AFF", "separador": "#C6C6C8",
        "mencion": "#FFD60A", "mencion_fg": "#000000",
        "burbuja_propia": "#007AFF", "burbuja_propia_fg": "#FFFFFF",
        "burbuja_otro": "#E9E9EB", "burbuja_otro_fg": "#000000",
    },
    "iOS Oscuro": {
        "bg": "#000000", "fg": "#FFFFFF", "campo": "#1C1C1E", "campo_fg": "#FFFFFF",
        "acento": "#0A84FF", "hora": "#8E8E93", "sistema": "#8E8E93", "aviso": "#FF453A",
        "accion": "#BF5AF2", "enlace": "#64D2FF", "separador": "#38383A",
        "mencion": "#FFD60A", "mencion_fg": "#000000",
        "burbuja_propia": "#0A84FF", "burbuja_propia_fg": "#FFFFFF",
        "burbuja_otro": "#3A3A3C", "burbuja_otro_fg": "#FFFFFF",
    },
}

DEFECTO = {
    "nick": "Nebula",
    "nick_alt": "Nebula_",
    "usuario": "nebula",
    "nombre_real": "Mi cliente IRC",
    "mensaje_quit": "Adiós",
    "servidores": [
        {
            "nombre": "ChatZona",
            "host": "irc.chatzona.org",
            "puerto": 6697,
            "tls": True,
            "tls_nombre": "irc.chateagratis.net",
            "clave": "",
        }
    ],
    "servidor_activo": 0,
    "autoconectar": False,
    "perform": [],
    "aliases": {
        "j": "/join $1",
        "m": "/msg $1 $2-",
        "saludo": "/me saluda a $1",
    },
    "tema": "iOS Claro",
    "fuente": "Segoe UI",
    "tamano": 11,
    "mostrar_hora": True,
    "formato_hora": "%H:%M",
    "modo_ventanas": "pestanas",   # "pestanas" o "ventanas"
    "url_actualizacion": "",
    "buscar_al_inicio": False,
    "geometria": "1100x680",
    "config_ver": CONFIG_VER,
}


def carpeta_config():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    ruta = os.path.join(base, "MiClienteIRC")
    os.makedirs(ruta, exist_ok=True)
    return ruta


def ruta_config():
    return os.path.join(carpeta_config(), "config.json")


def _servidor_valido(s):
    if not isinstance(s, dict):
        return None
    host = str(s.get("host", "")).strip()
    if not host:
        return None
    try:
        puerto = int(s.get("puerto", 6697))
    except (TypeError, ValueError):
        puerto = 6697
    if not 1 <= puerto <= 65535:
        puerto = 6697
    return {
        "nombre": str(s.get("nombre") or host).strip() or host,
        "host": host,
        "puerto": puerto,
        "tls": bool(s.get("tls", True)),
        "tls_nombre": str(s.get("tls_nombre", "")).strip(),
        "clave": str(s.get("clave", "")),
    }


def validar(cfg):
    """Rellena lo que falte y corrige valores inválidos."""
    for clave in ("nick", "nick_alt", "usuario", "nombre_real", "mensaje_quit",
                  "fuente", "url_actualizacion", "formato_hora", "geometria"):
        cfg[clave] = str(cfg.get(clave, DEFECTO[clave]))
    for clave in ("nick", "usuario", "fuente", "formato_hora"):
        if not cfg[clave].strip():
            cfg[clave] = DEFECTO[clave]
    for clave in ("autoconectar", "mostrar_hora", "buscar_al_inicio"):
        cfg[clave] = bool(cfg.get(clave, DEFECTO[clave]))

    lista = cfg.get("servidores")
    if not isinstance(lista, list):
        lista = []
    servidores = [x for x in (_servidor_valido(s) for s in lista) if x]
    cfg["servidores"] = servidores or copy.deepcopy(DEFECTO["servidores"])
    try:
        activo = int(cfg.get("servidor_activo", 0))
    except (TypeError, ValueError):
        activo = 0
    cfg["servidor_activo"] = min(max(activo, 0), len(cfg["servidores"]) - 1)

    try:
        tamano = int(cfg.get("tamano", 10))
    except (TypeError, ValueError):
        tamano = 10
    cfg["tamano"] = min(max(tamano, 8), 24)
    if cfg.get("tema") not in TEMAS:
        cfg["tema"] = DEFECTO["tema"]
    if cfg.get("modo_ventanas") not in ("pestanas", "ventanas"):
        cfg["modo_ventanas"] = "pestanas"
    if not re.match(r"^\d+x\d+([+-]-?\d+){0,2}$", cfg["geometria"]):
        cfg["geometria"] = DEFECTO["geometria"]

    aliases = cfg.get("aliases")
    if not isinstance(aliases, dict):
        aliases = copy.deepcopy(DEFECTO["aliases"])
    cfg["aliases"] = {str(k): str(v) for k, v in aliases.items()
                      if str(k) not in COMANDOS_INTERNOS}
    perform = cfg.get("perform")
    if not isinstance(perform, list):
        perform = []
    cfg["perform"] = [str(x) for x in perform if str(x).strip()]
    return cfg


def cargar():
    cfg = copy.deepcopy(DEFECTO)
    try:
        with open(ruta_config(), "r", encoding="utf-8") as f:
            datos = json.load(f)
        if isinstance(datos, dict):
            cfg.update(datos)
            if datos.get("config_ver") != CONFIG_VER:
                # Diseño iOS: tema y fuente nuevos, y sin conexión automática
                cfg["autoconectar"] = False
                cfg["tema"] = DEFECTO["tema"]
                cfg["fuente"] = DEFECTO["fuente"]
                cfg["tamano"] = DEFECTO["tamano"]
                cfg["config_ver"] = CONFIG_VER
    except (OSError, ValueError):
        pass
    return validar(cfg)


def guardar(cfg):
    ruta = ruta_config()
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(temporal, ruta)
