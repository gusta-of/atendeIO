"""Configuração: uma dataclass imutável lida das variáveis de ambiente."""

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from .resources import low_resource_defaults, total_ram_mb

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(f"ATENDEIO_{name}", default)


@dataclass(frozen=True)
class Settings:
    # modo: "server" (hoje: vários utilizadores, credenciais RTSP cifradas no banco) ou "desktop" (agente no cliente:
    # credenciais RTSP só em memória, pedidas a cada partida)
    mode: str = "server"
    launch_secret: str = ""   # segredo por execução (Electron -> motor): sem ele o motor recusa qualquer requisição (modo desktop)
    parent_pid: int = 0       # modo desktop: se o Electron (pai) morrer, o motor se encerra sozinho (não fica órfão segurando a câmera)
    run_key: str = ""   # chave Fernet por execução (vem do Electron, só em memória lá) que cifra o espelho temporário das credenciais
    # servidor
    host: str = "127.0.0.1"
    port: int = 8000
    # armazenamento
    data_dir: Path = ROOT / "data"
    model_path: Path = ROOT / "yolov8n.pt"
    seg_model_path: Path = ROOT / "yolov8n-seg.pt"  # silhuetas (oclusão das áreas); baixa sozinho na 1ª vez
    secret_key: str = ""  # Fernet; vazio => gera em data/secret.key
    # autenticação
    allow_signup: bool = True
    cookie_secure: bool = False
    session_ttl_s: int = 7 * 24 * 3600
    session_recheck_s: float = 30.0  # stream em andamento reconfere se a sessão vale
    ticket_ttl_s: int = 60           # tíquete de mídia (apps nativos): vale só para ABRIR o vídeo/eventos
    cors_origins: tuple = ()         # origens dos apps nativos (ex.: capacitor://localhost); vazio = só mesma origem
    login_fail_limit: int = 5
    login_fail_window_s: int = 600
    # visão / streaming
    conf_threshold: float = 0.55    # Valor de confianca para identificar objetos
    max_fps: float = 5.0            # teto de inferência por câmera
    idle_ttl_s: float = 30.0         # libera a câmera sem espectadores
    jpeg_quality: int = 75
    max_cameras: int = 12            # pipelines simultâneos no servidor
    max_cameras_per_user: int = 4    # câmeras simultâneas por utilizador
    first_frame_timeout_s: float = 12.0
    # monitoramento contínuo + histórico de fluxo (só números agregados, nunca imagens)
    map_fps: float = 4.0      # ritmo mínimo de leitura com o Mapa aberto (mostra o movimento das pessoas)
    monitor_fps: float = 1.0          # ritmo da inferência quando NINGUÉM assiste o vídeo
    monitor_tick_s: float = 30.0      # de quanto em quanto o monitor confere as câmeras monitoradas
    flow_flush_s: float = 15.0        # descarrega as amostras agregadas no banco a cada tanto
    flow_minute_days: int = 30        # retenção da resolução de minuto
    flow_hour_days: int = 730         # retenção da resolução de hora
    timezone: str = "America/Sao_Paulo"  # fuso do restaurante: dia/hora das análises
    # logs ao vivo (depuração): nunca podem pesar na aplicação
    log_events_per_s: float = 10.0    # orçamento por conexão; o excedente é descartado e resumido
    log_frame_hz: float = 2.0         # quadros detalhados, no máx. por segundo
    log_history: int = 200
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
    def run_dir(self) -> Path:
        return self.data_dir / "run"   # temporário: apagado na saída; ilegível depois de reiniciar (a chave muda)

    @property
    def desktop(self) -> bool:
        return self.mode == "desktop"

    @property
    def key_path(self) -> Path:
        return self.data_dir / "secret.key"

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        eco = low_resource_defaults(total_ram_mb())   # PC fraco: padrões mais leves (as variáveis explícitas vencem)
        s = cls(
            mode=_env("MODE", cls.mode),
            run_key=_env("RUN_KEY", ""),
            parent_pid=int(_env("PARENT_PID", "0") or 0),
            launch_secret=_env("LAUNCH_SECRET", ""),
            host=_env("HOST", cls.host),
            port=int(_env("PORT", str(cls.port))),
            data_dir=Path(_env("DATA", str(cls.data_dir))),
            secret_key=_env("SECRET_KEY", ""),
            allow_signup=_env("ALLOW_SIGNUP", "1") == "1",
            cookie_secure=_env("COOKIE_SECURE", "0") == "1",
            session_ttl_s=int(_env("SESSION_TTL", str(cls.session_ttl_s))),
            cors_origins=tuple(o.strip().rstrip("/") for o in _env("CORS_ORIGINS", "").split(",") if o.strip()),
            max_fps=float(_env("MAX_FPS", str(cls.max_fps))),
            occlusion=_env("OCCLUSION", "0" if eco.get("occlusion") is False else "1") == "1",
            monitor_fps=float(_env("MONITOR_FPS", str(cls.monitor_fps))),
            map_fps=float(_env("MAP_FPS", str(cls.map_fps))),
            timezone=_env("TIMEZONE", cls.timezone),
            flow_minute_days=int(_env("FLOW_MINUTE_DAYS", str(cls.flow_minute_days))),
            flow_hour_days=int(_env("FLOW_HOUR_DAYS", str(cls.flow_hour_days))),
            log_events_per_s=float(_env("LOG_EVENTS_PER_S", str(cls.log_events_per_s))),
            occupy_after_s=float(_env("OCCUPY_AFTER", str(cls.occupy_after_s))),
            free_after_s=float(_env("FREE_AFTER", str(cls.free_after_s))),
            clean_after_s=float(_env("CLEAN_AFTER", str(cls.clean_after_s))),
            idle_ttl_s=float(_env("IDLE_TTL", str(cls.idle_ttl_s))),
            jpeg_quality=int(_env("JPEG_QUALITY", str(eco.get("jpeg_quality", cls.jpeg_quality)))),
            max_cameras=int(_env("MAX_CAMERAS", str(eco.get("max_cameras", cls.max_cameras)))),
            max_cameras_per_user=int(_env("MAX_CAMERAS_PER_USER", str(eco.get("max_cameras_per_user", cls.max_cameras_per_user)))),
        )
        return replace(s, **overrides)
