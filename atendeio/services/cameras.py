"""Câmeras: cadastro RTSP/local, listagem e resolução da fonte — sempre por dono."""

import json
import os
import re
from typing import Callable, Optional

from ..errors import CredentialsRequired, NotFoundError, ValidationError
from ..repositories.cameras import CameraRepository
from ..security import SecretBox
from ..vision.sources import list_v4l2_devices, open_source
from . import rtsp
from .credentials import SessionCredentials


def _clean_name(name: str, default: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())[:60] or default


class CameraService:
    """`credentials` liga o modo "sem persistência": usuário e senha RTSP ficam só na memória (SessionCredentials) e a
    coluna `secret` fica vazia. Sem ele (modo servidor) as credenciais seguem criptografadas no banco."""

    def __init__(self, cameras: CameraRepository, box: SecretBox,
                 device_lister: Callable = list_v4l2_devices, credentials: Optional[SessionCredentials] = None):
        self._cameras, self._box, self._list_devices, self._creds = cameras, box, device_lister, credentials

    def _public(self, cam: dict) -> dict:
        """Visão segura pro cliente: nunca inclui `secret`."""
        view = {"id": cam["id"], "name": cam["name"], "kind": cam["kind"], "ref": cam["ref"]}
        if self._creds is not None and cam["kind"] == "rtsp":
            view["needs_credentials"] = not self._creds.has(cam["id"])
        return view

    # -- consulta -------------------------------------------------
    def list(self, user_id: int) -> list:
        return [self._public(c) for c in self._cameras.list_for_user(user_id)]

    def needs_credentials(self, cam: dict) -> bool:
        """Câmera RTSP que ainda não recebeu usuário/senha nesta execução (sempre False no modo servidor)."""
        return self._creds is not None and cam["kind"] == "rtsp" and not self._creds.has(cam["id"])

    def require_credentials(self, cam: dict) -> None:
        if self.needs_credentials(cam):
            raise CredentialsRequired("Informe o usuário e a senha desta câmera (não ficam salvos).")

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
        blob = None if self._creds is not None else \
            self._box.encrypt(json.dumps({"u": username or "", "p": password or ""}).encode())
        name = _clean_name(name, host)
        cam_id = self._cameras.add(user_id, name, "rtsp", ref, blob)
        if self._creds is not None:
            self._creds.put(cam_id, username, password)
        return self._public({"id": cam_id, "name": name, "kind": "rtsp", "ref": ref})

    def set_credentials(self, cam_id: int, user_id: int, username: str, password: str) -> dict:
        """Informa (de novo) usuário e senha de uma câmera RTSP: só na memória desta execução."""
        cam = self.get_owned(cam_id, user_id)
        if cam["kind"] != "rtsp":
            raise ValidationError("Só câmeras de rede (RTSP) têm usuário e senha.")
        if self._creds is None:
            raise ValidationError("Neste modo as credenciais são salvas no cadastro da câmera.")
        if len(username or "") > 128 or len(password or "") > 256:
            raise ValidationError("Usuário ou senha da câmera muito longos.")
        self._creds.put(cam_id, username, password)
        return self._public(cam)

    def add_local(self, user_id: int, ref: str, name: str) -> dict:
        # só aceita o que o servidor realmente enumerou (nada de caminho livre)
        dev = next((d for d in self._list_devices() if d["ref"] == ref), None)
        if dev is None:
            raise NotFoundError("Dispositivo não encontrado.")
        name = _clean_name(name, dev["name"])
        cam_id = self._cameras.add(user_id, name, "local", dev["ref"])
        return self._public({"id": cam_id, "name": name, "kind": "local", "ref": dev["ref"]})

    def update(self, cam_id: int, user_id: int, name: Optional[str] = None, host: Optional[str] = None, port=None,
               path: Optional[str] = None) -> dict:
        """Edita nome e, nas câmeras de rede, o endereço (IP/porta/caminho). Câmera USB só muda de nome: a `ref` é o
        id de hardware. Devolve a câmera já atualizada (visão pública). Usuário e senha não passam por aqui."""
        cam = self.get_owned(cam_id, user_id)
        new_name = _clean_name(name, cam["name"]) if name is not None else cam["name"]
        ref = cam["ref"]
        if cam["kind"] == "rtsp" and (host is not None or port is not None or path is not None):
            old_host, old_port, old_path = rtsp.parse_ref(cam["ref"])
            h, p, pa = rtsp.validate(host if host is not None else old_host, port if port not in (None, "") else old_port,
                                     path if path is not None else old_path)
            ref = rtsp.public_ref(h, p, pa)
        elif cam["kind"] == "local" and (host or port or path):
            raise ValidationError("Câmera USB não tem endereço de rede para editar.")
        self._cameras.update_basic(cam_id, user_id, new_name, ref)
        return self._public(self.get_owned(cam_id, user_id))

    def delete(self, cam_id: int, user_id: int) -> None:
        if not self._cameras.delete(cam_id, user_id):
            raise NotFoundError("Câmera não encontrada.")
        if self._creds is not None:
            self._creds.forget(cam_id)

    # -- FPS por câmera --------------------------------------------------------------------------------
    VIEW_FPS = (1.0, 30.0)         # faixa aceita com o vídeo aberto
    MONITOR_FPS = (0.2, 10.0)      # faixa aceita só monitorando (sem ninguém olhando)

    def get_fps(self, cam_id: int, user_id: Optional[int] = None) -> tuple:
        """(fps_view, fps_monitor) salvos; None = padrão do sistema. Com `user_id`, confere o dono."""
        if user_id is not None:
            self.get_owned(cam_id, user_id)
        return self._cameras.get_fps(cam_id)

    def set_fps(self, cam_id: int, user_id: int, fps_view: Optional[float], fps_monitor: Optional[float]) -> tuple:
        """Salva o FPS da câmera (None = voltar ao padrão). Só valores finitos dentro das faixas."""
        self.get_owned(cam_id, user_id)
        out = []
        for value, (lo, hi), label in ((fps_view, self.VIEW_FPS, "ao assistir"), (fps_monitor, self.MONITOR_FPS, "no monitoramento")):
            if value is None:
                out.append(None)
                continue
            try:
                v = float(value)
            except (TypeError, ValueError):
                raise ValidationError(f"FPS {label} inválido.")
            if not (v == v and lo <= v <= hi):          # v == v descarta NaN
                raise ValidationError(f"FPS {label}: use um valor entre {lo:g} e {hi:g}.")
            out.append(round(v, 2))
        self._cameras.update_fps(cam_id, user_id, out[0], out[1])
        return tuple(out)

    # -- fonte de vídeo -------------------------------------------
    def source_for(self, cam: dict):
        """O que o OpenCV abre. Contém credenciais: só usar dentro do servidor."""
        if cam["kind"] == "local":
            return os.path.realpath(cam["ref"])  # /dev/videoN atual do id estável
        host, port, path = rtsp.parse_ref(cam["ref"])
        rtsp.check_host(host)  # reconfere a cada abertura (DNS pode ter mudado)
        if self._creds is not None:
            self.require_credentials(cam)
            username, password = self._creds.get(cam["id"])
        else:
            sec = json.loads(self._box.decrypt(cam["secret"]))
            username, password = sec["u"], sec["p"]
        return rtsp.build_url(host, port, username, password, path)

    def probe(self, cam: dict) -> bool:
        """Testa se a câmera abre agora (usado pra avisar IP/senha errados no cadastro)."""
        try:
            open_source(self.source_for(cam)).release()
            return True
        except Exception:
            return False
