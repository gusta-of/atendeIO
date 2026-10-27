"""Configuração: uma dataclass imutável lida das variáveis de ambiente."""

import os
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(f"ATENDEIO_{name}", default)


@dataclass(frozen=True)
class Settings:
    # servidor
    host: str = "127.0.0.1"
    port: int = 8000
    # armazenamento
    static_dir: Path = ROOT / "static"
    data_dir: Path = ROOT / "data"
    model_path: Path = ROOT / "yolov8n.pt"
    seg_model_path: Path = ROOT / "yolov8n-seg.pt"  # silhuetas (oclusão das áreas); baixa sozinho na 1ª vez
    secret_key: str = ""  # Fernet; vazio => gera em data/secret.key
    # autenticação
    allow_signup: bool = True
    cookie_secure: bool = False
    session_ttl_s: int = 7 * 24 * 3600
    session_recheck_s: float = 30.0  # stream em andamento reconfere se a sessão vale
    login_fail_limit: int = 5
    login_fail_window_s: int = 600
    # visão / streaming
    conf_threshold: float = 0.45
    max_fps: float = 15.0            # teto de inferência por câmera
    idle_ttl_s: float = 30.0         # libera a câmera sem espectadores
    jpeg_quality: int = 75
    max_cameras: int = 12            # pipelines simultâneos no servidor
    max_cameras_per_user: int = 4    # câmeras simultâneas por utilizador
    first_frame_timeout_s: float = 12.0
    # áreas do salão (ver analytics/zones.py)
    max_zones_per_camera: int = 50
    occupy_after_s: float = 3.0
    free_after_s: float = 15.0
    item_hold_s: float = 3.0
    clean_after_s: float = 20.0
    zone_overlap_min: float = 0.35  # pontuação mínima de pertencimento à área (0..1)
    # Áreas "pintadas" no vídeo: quem está na frente esconde o contorno (precisa da segmentação)
    occlusion: bool = True
    occluder_exclude: tuple = ("dining table",)  # a mesa não apaga a área que está SOBRE ela
    # classes COCO que indicam "tem coisa na mesa" (copo, tigela, garrafa, taça, talheres)
    table_item_classes: tuple = ("cup", "bowl", "bottle", "wine glass", "fork", "knife", "spoon")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "atendeio.db"

    @property
    def key_path(self) -> Path:
        return self.data_dir / "secret.key"

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        s = cls(
            host=_env("HOST", cls.host),
            port=int(_env("PORT", str(cls.port))),
            data_dir=Path(_env("DATA", str(cls.data_dir))),
            secret_key=_env("SECRET_KEY", ""),
            allow_signup=_env("ALLOW_SIGNUP", "1") == "1",
            cookie_secure=_env("COOKIE_SECURE", "0") == "1",
            session_ttl_s=int(_env("SESSION_TTL", str(cls.session_ttl_s))),
            max_fps=float(_env("MAX_FPS", str(cls.max_fps))),
            occlusion=_env("OCCLUSION", "1") == "1",
            occupy_after_s=float(_env("OCCUPY_AFTER", str(cls.occupy_after_s))),
            free_after_s=float(_env("FREE_AFTER", str(cls.free_after_s))),
            clean_after_s=float(_env("CLEAN_AFTER", str(cls.clean_after_s))),
            idle_ttl_s=float(_env("IDLE_TTL", str(cls.idle_ttl_s))),
            jpeg_quality=int(_env("JPEG_QUALITY", str(cls.jpeg_quality))),
            max_cameras=int(_env("MAX_CAMERAS", str(cls.max_cameras))),
            max_cameras_per_user=int(_env("MAX_CAMERAS_PER_USER", str(cls.max_cameras_per_user))),
        )
        return replace(s, **overrides)
