"""Configuração do envio à cloud: endpoint, chave do dispositivo e liga/desliga. Sem HTTP, sem SQL.

A chave fica criptografada (Fernet) no banco e nunca volta ao cliente: a API só diz se existe (`key_set`)."""

import ipaddress
from typing import Optional
from urllib.parse import urlsplit

from ..errors import ValidationError
from ..repositories.cloud import CloudConfigRepository
from ..security import SecretBox

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
MAX_URL = 300
MAX_KEY = 512


def normalize_url(raw: str) -> str:
    """Endereço base da cloud. HTTPS obrigatório; HTTP só em loopback (desenvolvimento com servidor falso)."""
    url = (raw or "").strip().rstrip("/")
    if not url:
        raise ValidationError("Indique o endereço da cloud.")
    if len(url) > MAX_URL:
        raise ValidationError("Endereço da cloud muito longo.")
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or not host:
        raise ValidationError("Endereço da cloud inválido.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValidationError("O endereço não pode ter utilizador, senha, parâmetros ou fragmento.")
    if parts.scheme == "http" and not _is_loopback(host):
        raise ValidationError("A cloud tem de usar HTTPS.")
    return url


def _is_loopback(host: str) -> bool:
    if host in LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class CloudService:
    def __init__(self, repo: CloudConfigRepository, box: SecretBox):
        self._repo, self._box = repo, box

    def public(self) -> dict:
        """O que o cliente pode ver: nunca a chave."""
        c = self._repo.get()
        return {"enabled": bool(c["enabled"]), "url": c["url"], "key_set": bool(c["api_key"]),
                "device_id": c["device_id"]}

    def update(self, enabled: bool, url: str, api_key: Optional[str] = None) -> dict:
        """`api_key` None = mantém a chave guardada. Ligar exige endereço e chave."""
        current = self._repo.get()
        url = normalize_url(url) if (enabled or (url or "").strip()) else ""
        if api_key is not None:
            api_key = api_key.strip()
            if not api_key or len(api_key) > MAX_KEY:
                raise ValidationError("Chave do dispositivo inválida.")
        if enabled and not (api_key or current["api_key"]):
            raise ValidationError("Indique a chave do dispositivo para ligar o envio.")
        if api_key is None:
            self._repo.update(enabled, url)
        else:
            self._repo.update(enabled, url, self._box.encrypt(api_key.encode()), keep_key=False)
        return self.public()

    def credentials(self) -> Optional[dict]:
        """{"url", "key", "device_id"} se o envio está ligado e completo; senão None. Só dentro do servidor."""
        c = self._repo.get()
        if not (c["enabled"] and c["url"] and c["api_key"]):
            return None
        return {"url": c["url"], "key": self._box.decrypt(c["api_key"]).decode(), "device_id": c["device_id"]}
