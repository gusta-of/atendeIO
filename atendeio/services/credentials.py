"""Cofre de credenciais RTSP que NÃO persiste: usuário e senha da câmera vivem só na memória desta execução.

Modo desktop: o cliente digita as credenciais a cada vez que liga o computador. IP, porta e caminho (a `ref` da câmera)
continuam no banco; usuário e senha, nunca.

Espelho opcional em arquivo (`spill_path` + `spill_key`): serve só para o motor reiniciar DENTRO da mesma sessão (queda do
processo) sem pedir tudo de novo. O arquivo é cifrado com uma chave aleatória por execução que o Electron guarda só na
memória dele e passa por variável de ambiente; reiniciar o computador (ou o app) troca a chave e o arquivo vira lixo, que é
apagado na partida. Sem `spill_key` não existe arquivo nenhum."""

import contextlib
import json
import os
import threading
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class SessionCredentials:
    def __init__(self, spill_path: Optional[Path] = None, spill_key: str = ""):
        self._items: dict = {}
        self._lock = threading.Lock()
        self._path = Path(spill_path) if spill_path and spill_key else None
        self._fernet = Fernet(spill_key.encode()) if self._path else None
        self._load()

    # -- uso ----------------------------------------------------------------------------------
    def put(self, cam_id: int, username: str, password: str) -> None:
        with self._lock:
            self._items[int(cam_id)] = (username or "", password or "")
            self._save()

    def get(self, cam_id: int) -> Optional[tuple]:
        with self._lock:
            return self._items.get(int(cam_id))

    def has(self, cam_id: int) -> bool:
        return self.get(cam_id) is not None

    def forget(self, cam_id: int) -> None:
        with self._lock:
            self._items.pop(int(cam_id), None)
            self._save()

    def clear(self) -> None:
        """Esquece tudo e apaga o espelho (saída do app)."""
        with self._lock:
            self._items.clear()
            self._remove()

    # -- espelho em arquivo cifrado ------------------------------------------------------------
    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._fernet.decrypt(self._path.read_bytes()))
            self._items = {int(k): (v[0], v[1]) for k, v in data.items()}
        except (InvalidToken, ValueError, OSError, KeyError, IndexError, TypeError):
            self._items = {}
            self._remove()   # chave de outra execução (ou arquivo corrompido): inútil, apaga

    def _save(self) -> None:
        if self._path is None:
            return
        if not self._items:
            self._remove()
            return
        payload = self._fernet.encrypt(json.dumps({str(k): list(v) for k, v in self._items.items()}).encode())
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(tmp, self._path)

    def _remove(self) -> None:
        if self._path is not None:
            with contextlib.suppress(OSError):
                self._path.unlink()
