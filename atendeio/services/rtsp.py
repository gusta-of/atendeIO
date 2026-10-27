"""Montagem e validação de URLs RTSP (cliente informa IP, usuário e senha)."""

import ipaddress
import re
import socket
from urllib.parse import quote

from ..errors import ValidationError

HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
PATH_RE = re.compile(r"^[A-Za-z0-9_\-./?=&%:]*$")

# Caminhos RTSP típicos por marca.
PRESETS = {
    "generico": {"label": "Genérica", "path": ""},
    "tapo": {"label": "TP-Link Tapo", "path": "stream1"},
    "hikvision": {"label": "Hikvision", "path": "Streaming/Channels/101"},
    "dahua": {"label": "Dahua / Intelbras", "path": "cam/realmonitor?channel=1&subtype=0"},
    "reolink": {"label": "Reolink", "path": "h264Preview_01_main"},
}


def check_host(host: str) -> None:
    """Impede usar o servidor pra acessar a si mesmo ou metadados de nuvem. Redes privadas
    (192.168.x.x etc.) são permitidas: é onde as câmeras ficam."""
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        raise ValidationError("Não consegui resolver o endereço da câmera.")
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            raise ValidationError("Endereço não permitido para câmera.")


def validate(host: str, port, path: str) -> tuple:
    """Devolve (host, port, path) normalizados ou levanta ValidationError."""
    host = (host or "").strip()
    if not HOST_RE.match(host):
        raise ValidationError("IP ou endereço da câmera inválido.")
    try:
        port = 554 if port in (None, "") else int(port)
    except (TypeError, ValueError):
        raise ValidationError("Porta inválida.")
    if not 1 <= port <= 65535:
        raise ValidationError("Porta inválida.")
    path = (path or "").strip().lstrip("/")
    if not PATH_RE.match(path):
        raise ValidationError("Caminho RTSP com caracteres inválidos.")
    check_host(host)
    return host, port, path


def build_url(host: str, port: int, username: str, password: str, path: str = "") -> str:
    """rtsp://user:senha@host:porta/caminho — credenciais escapadas (senha com @ : / # quebraria a URL)."""
    cred = f"{quote(username, safe='')}:{quote(password, safe='')}@" if username else ""
    return f"rtsp://{cred}{host}:{port}/{(path or '').lstrip('/')}"


def public_ref(host: str, port: int, path: str) -> str:
    """Identificação da câmera SEM credenciais (é o que o banco guarda em claro)."""
    return f"rtsp://{host}:{port}/{path}"


_REF_RE = re.compile(r"^rtsp://([^:/]+):(\d+)/(.*)$")


def parse_ref(ref: str) -> tuple:
    m = _REF_RE.match(ref)
    return m.group(1), int(m.group(2)), m.group(3)
