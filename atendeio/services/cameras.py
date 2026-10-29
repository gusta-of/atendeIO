"""Câmeras: cadastro RTSP/local, listagem e resolução da fonte — sempre por dono."""

import json
import re
from typing import Callable

from ..errors import NotFoundError, ValidationError
from ..repositories.cameras import CameraRepository
from ..security import SecretBox
from ..vision.sources import list_v4l2_devices, local_source, open_source
from . import rtsp


def _clean_name(name: str, default: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())[:60] or default


def _public(cam: dict) -> dict:
    """Visão segura pro cliente: nunca inclui `secret`."""
    return {"id": cam["id"], "name": cam["name"], "kind": cam["kind"], "ref": cam["ref"]}


class CameraService:
    def __init__(self, cameras: CameraRepository, box: SecretBox,
                 device_lister: Callable = list_v4l2_devices):
        self._cameras, self._box, self._list_devices = cameras, box, device_lister

    # -- consulta -------------------------------------------------
    def list(self, user_id: int) -> list:
        return [_public(c) for c in self._cameras.list_for_user(user_id)]

    def get_owned(self, cam_id: int, user_id: int) -> dict:
        """Câmera do utilizador. Se for de outro, é o mesmo NotFound de uma inexistente."""
        cam = self._cameras.get_for_user(cam_id, user_id)
        if cam is None:
            raise NotFoundError("Câmera não encontrada.")
        return cam

    def local_devices(self, user_id: int) -> list:
        """Câmeras do servidor livres + as do próprio utilizador (as de outros nem aparecem)."""
        taken = self._cameras.local_refs(not_owned_by=user_id)
        mine = self._cameras.local_refs(owned_by=user_id)
        return [{"ref": d["ref"], "name": d["name"], "mine": d["ref"] in mine}
                for d in self._list_devices() if d["ref"] not in taken]

    # -- cadastro -------------------------------------------------
    def add_rtsp(self, user_id: int, name: str, host: str, port, username: str,
                 password: str, path: str = "") -> dict:
        if len(username or "") > 128 or len(password or "") > 256:
            raise ValidationError("Usuário ou senha da câmera muito longos.")
        host, port, path = rtsp.validate(host, port, path)
        ref = rtsp.public_ref(host, port, path)
        blob = self._box.encrypt(json.dumps({"u": username or "", "p": password or ""}).encode())
        name = _clean_name(name, host)
        cam_id = self._cameras.add(user_id, name, "rtsp", ref, blob)
        return {"id": cam_id, "name": name, "kind": "rtsp", "ref": ref}

    def add_local(self, user_id: int, ref: str, name: str) -> dict:
        # só aceita o que o servidor realmente enumerou (nada de caminho livre)
        dev = next((d for d in self._list_devices() if d["ref"] == ref), None)
        if dev is None:
            raise NotFoundError("Dispositivo não encontrado.")
        name = _clean_name(name, dev["name"])
        cam_id = self._cameras.add(user_id, name, "local", dev["ref"])
        return {"id": cam_id, "name": name, "kind": "local", "ref": dev["ref"]}

    def delete(self, cam_id: int, user_id: int) -> None:
        if not self._cameras.delete(cam_id, user_id):
            raise NotFoundError("Câmera não encontrada.")

    # -- fonte de vídeo -------------------------------------------
    def source_for(self, cam: dict):
        """O que o OpenCV abre. Contém credenciais: só usar dentro do servidor."""
        if cam["kind"] == "local":
            return local_source(cam["ref"])  # /dev/videoN (Linux) ou índice DirectShow (Windows), atuais
        host, port, path = rtsp.parse_ref(cam["ref"])
        rtsp.check_host(host)  # reconfere a cada abertura (DNS pode ter mudado)
        sec = json.loads(self._box.decrypt(cam["secret"]))
        return rtsp.build_url(host, port, sec["u"], sec["p"], path)

    def probe(self, cam: dict) -> bool:
        """Testa se a câmera abre agora (usado pra avisar IP/senha errados no cadastro)."""
        try:
            open_source(self.source_for(cam)).release()
            return True
        except Exception:
            return False
