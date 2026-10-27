"""Análise de fluxo: consulta o histórico de uma câmera do utilizador e monta o relatório no fuso do restaurante."""

import csv
import io
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from ..analytics.flow import build_report, day_series, hourly_rows, local_day_bounds
from ..config import Settings
from ..errors import ValidationError
from ..repositories.flow import FlowRepository
from .cameras import CameraService
from .monitor import _zone

MAX_SPAN_DAYS = 731


class FlowService:
    def __init__(self, repo: FlowRepository, cameras: CameraService, settings: Settings):
        self._repo, self._cameras = repo, cameras
        self.tz: ZoneInfo = _zone(settings.timezone)

    def today(self) -> date:
        return datetime.now(self.tz).date()

    def _window(self, d_from: Optional[date], d_to: Optional[date], hour_from: int, hour_to: int) -> tuple:
        d_to = d_to or self.today()
        d_from = d_from or d_to - timedelta(days=6)                  # padrão: últimos 7 dias, hoje incluído
        if d_to < d_from:
            raise ValidationError("A data final não pode ser antes da inicial.")
        if (d_to - d_from).days > MAX_SPAN_DAYS:
            raise ValidationError("Período grande demais (máximo de 2 anos).")
        if not (0 <= hour_from < hour_to <= 24):
            raise ValidationError("Faixa de horas inválida (use início menor que o fim, entre 0 e 24).")
        return d_from, d_to

    def _hour_bounds(self, d_from: date, d_to: date) -> tuple:
        lo = datetime(d_from.year, d_from.month, d_from.day, tzinfo=self.tz)
        hi = datetime(d_to.year, d_to.month, d_to.day, tzinfo=self.tz) + timedelta(days=1)
        return int(lo.timestamp() // 3600) - 1, int(hi.timestamp() // 3600) + 1   # folga de 1 h: o filtro exato é local

    def report(self, cam_id: int, user_id: int, d_from: Optional[date] = None, d_to: Optional[date] = None,
               hour_from: int = 0, hour_to: int = 24, now: Optional[datetime] = None) -> dict:
        self._cameras.get_owned(cam_id, user_id)
        d_from, d_to = self._window(d_from, d_to, hour_from, hour_to)
        lo, hi = self._hour_bounds(d_from, d_to)
        return build_report(self._repo.hours(cam_id, lo, hi), self._repo.areas(cam_id, lo, hi), self.tz,
                            d_from, d_to, hour_from, hour_to, now)

    def day(self, cam_id: int, user_id: int, day: Optional[date] = None) -> dict:
        self._cameras.get_owned(cam_id, user_id)
        day = day or self.today()
        lo, hi = local_day_bounds(day, self.tz)
        return {"date": day.isoformat(), "timezone": str(self.tz),
                "series": day_series(self._repo.minutes(cam_id, lo, hi), self.tz, day)}

    def csv(self, cam_id: int, user_id: int, d_from: Optional[date] = None, d_to: Optional[date] = None,
            hour_from: int = 0, hour_to: int = 24) -> str:
        self._cameras.get_owned(cam_id, user_id)
        d_from, d_to = self._window(d_from, d_to, hour_from, hour_to)
        lo, hi = self._hour_bounds(d_from, d_to)
        rows = hourly_rows(self._repo.hours(cam_id, lo, hi), self.tz, d_from, d_to, hour_from, hour_to)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["data", "dia_da_semana", "hora", "media_pessoas", "maximo_pessoas",
                                            "amostras"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue()
