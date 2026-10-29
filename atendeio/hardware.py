"""Reconhece o hardware do utilizador e recomenda uma faixa de FPS por câmera. Sem Qt, sem dependências extras.

A recomendação parte de uma MEDIÇÃO: roda o YOLO de verdade alguns quadros e vê quanto tempo cada um leva nesta máquina
(`benchmark`). A inferência é serializada (uma por vez, em CPU), então `1000 / ms` é a capacidade TOTAL em quadros/s,
dividida entre as câmeras. Sem medição, `estimate_capacity` dá um palpite conservador pelos núcleos (marcado como estimativa).

    capacidade = 1000 / ms_por_quadro          orçamento = 70% da capacidade (folga para captura, interface, banco, sistema)
    monitoramento (só analisando): faixa até 5 fps, sugerido 1 fps, reduzido se a máquina não aguenta
    ao assistir (vídeo aberto): o que sobra do orçamento depois de monitorar as outras câmeras; teto de 15 fps
        (acima disso não melhora a contagem de pessoas e só gasta CPU)"""

import ctypes
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Tuple

from .resources import total_ram_mb

HEADROOM = 0.70            # fração da capacidade que se pode usar sem sufocar o resto
VIEW_CAP = 15.0            # teto de FPS ao assistir
MONITOR_CAP = 5.0
Range = Tuple[float, float, float]      # (mínimo, máximo, sugerido)


@dataclass
class HardwareInfo:
    os_name: str
    cpu_model: str
    cores: int                           # núcleos lógicos
    ram_total_mb: Optional[int]
    ram_available_mb: Optional[int]
    gpu: Optional[str]
    arch: str = ""


@dataclass
class Recommendation:
    tier: str                            # Básico | Intermediário | Forte
    capacity_fps: float                  # quadros/s totais que a máquina processa
    bench_ms: Optional[float]            # ms por quadro medido (None = não medido)
    estimated: bool
    cameras: int
    view: Range
    monitor: Range
    max_cameras: int
    notes: List[str] = field(default_factory=list)


# -- detecção ---------------------------------------------------------------------------------------------
def _run(cmd: List[str], timeout: float = 4.0) -> str:
    """Saída de um comando do sistema; vazio se não existir, demorar ou falhar (a detecção nunca derruba o app)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""


def _cpu_model() -> str:
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        if sys.platform == "darwin":
            return _run(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor()
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.lower().startswith(("model name", "hardware", "processor\t: arm")):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "desconhecido"


def _ram_available_mb() -> Optional[int]:
    try:
        if sys.platform == "win32":
            class _Mem(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("tpage", ctypes.c_ulonglong), ("apage", ctypes.c_ulonglong),
                            ("tvirt", ctypes.c_ulonglong), ("avirt", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
            m = _Mem()
            m.length = ctypes.sizeof(_Mem)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return int(m.avail // (1024 * 1024))
        if sys.platform == "darwin":
            return None
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return None


def _gpu() -> Optional[str]:
    """Nome da placa de vídeo (só informativo: o atendeIO roda a detecção na CPU)."""
    if sys.platform == "win32":
        out = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"], 6.0)
        names = [x.strip() for x in out.splitlines() if x.strip()]
    elif sys.platform == "darwin":
        out = _run(["system_profiler", "SPDisplaysDataType"], 6.0)
        names = [m.group(1).strip() for m in re.finditer(r"Chipset Model:\s*(.+)", out)]
    else:
        names = [x.strip() for x in _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]).splitlines() if x.strip()]
        if not names:
            for line in _run(["lspci"]).splitlines():
                if re.search(r"VGA|3D|Display", line, re.I):
                    names.append(re.sub(r"^\S+\s+[^:]+:\s*", "", line).strip())
    return "; ".join(dict.fromkeys(names)) or None


def detect() -> HardwareInfo:
    return HardwareInfo(os_name=f"{platform.system()} {platform.release()}".strip(), cpu_model=_cpu_model(),
                        cores=os.cpu_count() or 1, ram_total_mb=total_ram_mb(), ram_available_mb=_ram_available_mb(),
                        gpu=_gpu(), arch=platform.machine())


# -- medição ----------------------------------------------------------------------------------------------
def benchmark(detector, frames: int = 10, size: Tuple[int, int] = (640, 360), progress=None) -> Optional[float]:
    """Mediana de ms por quadro da inferência real nesta máquina (None se o detector não está disponível).
    O primeiro quadro (carga do modelo) é descartado. `progress(i, n)` é chamado a cada quadro."""
    import numpy as np
    rng = np.random.default_rng(7)
    frame = rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    try:
        detector.detect(frame, None)                       # aquecimento / carga do modelo
        times = []
        for i in range(frames):
            t0 = time.perf_counter()
            detector.detect(frame, None)
            times.append((time.perf_counter() - t0) * 1000)
            if progress:
                progress(i + 1, frames)
    except Exception:
        return None
    return statistics.median(times) if times else None


def estimate_capacity(info: HardwareInfo) -> float:
    """Palpite conservador (quadros/s) sem medir: ~2 fps por núcleo lógico até 8 núcleos."""
    return max(1.0, min(info.cores, 8) * 2.0)


# -- recomendação ---------------------------------------------------------------------------------------------
def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def recommend(info: HardwareInfo, bench_ms: Optional[float] = None, cameras: int = 1) -> Recommendation:
    cameras = max(1, int(cameras))
    estimated = not (bench_ms and bench_ms > 0)
    capacity = estimate_capacity(info) if estimated else 1000.0 / bench_ms
    budget = capacity * HEADROOM
    notes: List[str] = []

    # monitoramento: todas as câmeras analisam de fundo
    hi_m = _clamp(budget * 0.5 / cameras, 0.2, MONITOR_CAP)
    lo_m = min(0.5, hi_m)
    sug_m = _clamp(1.0, lo_m, hi_m)
    # ao assistir: o que sobra depois de monitorar as OUTRAS câmeras
    remaining = budget - (cameras - 1) * sug_m
    hi_v = _clamp(float(int(remaining)), 1.0, VIEW_CAP)
    lo_v = max(1.0, float(round(hi_v / 2)))
    sug_v = max(lo_v, float(int(hi_v * 0.75)))

    ram = info.ram_total_mb
    ram_cap = 12 if not ram or ram >= 12288 else 6 if ram >= 6144 else 3
    max_cams = int(_clamp(int(budget / 1.0), 1, ram_cap))

    tier = "Básico" if capacity < 4 else "Intermediário" if capacity < 10 else "Forte"
    if estimated:
        notes.append("Estimativa pelos núcleos do processador. Rode a medição para uma recomendação precisa.")
    if ram and ram < 6144:
        notes.append(f"Pouca memória ({ram // 1024} GB): o app usa o perfil econômico e recomenda poucas câmeras.")
    if cameras > max_cams:
        notes.append(f"Você tem {cameras} câmeras, acima do recomendado para esta máquina ({max_cams}). "
                     f"Reduza o FPS ou o número de câmeras analisando ao mesmo tempo.")
    if sug_m < 1.0:
        notes.append("Esta máquina está no limite: o monitoramento foi reduzido abaixo de 1 FPS.")
    if info.gpu:
        notes.append("O atendeIO analisa na CPU; a placa de vídeo não é usada (e não é necessária).")
    if hi_v >= VIEW_CAP:
        notes.append(f"Acima de {VIEW_CAP:.0f} FPS a contagem de pessoas não melhora, só gasta mais CPU.")
    return Recommendation(tier=tier, capacity_fps=round(capacity, 1), bench_ms=round(bench_ms, 1) if not estimated else None,
                          estimated=estimated, cameras=cameras, view=(lo_v, hi_v, sug_v),
                          monitor=(round(lo_m, 2), round(hi_m, 2), round(sug_m, 2)), max_cameras=max_cams, notes=notes)


# -- texto para humanos -------------------------------------------------------------------------------------------
def _gb(mb: Optional[int]) -> str:
    return "?" if mb is None else f"{mb / 1024:.1f} GB"


def hardware_lines(info: HardwareInfo) -> List[str]:
    return [f"Sistema:        {info.os_name} ({info.arch})", f"Processador:    {info.cpu_model}",
            f"Núcleos:        {info.cores} (lógicos)", f"Memória:        {_gb(info.ram_total_mb)} (livre {_gb(info.ram_available_mb)})",
            f"Placa de vídeo: {info.gpu or 'não encontrada'}"]


def recommendation_lines(rec: Recommendation) -> List[str]:
    how = f"medido: {rec.bench_ms} ms por quadro" if not rec.estimated else "estimado (sem medição)"
    out = [f"Capacidade:     {rec.capacity_fps} quadros/s no total ({how}) · perfil {rec.tier}",
           f"Câmeras:        {rec.cameras} analisando · recomendado até {rec.max_cameras}",
           f"FPS ao assistir (vídeo aberto):  {rec.view[0]:g} a {rec.view[1]:g}  · sugerido {rec.view[2]:g}",
           f"FPS monitorando (sem ninguém olhando):  {rec.monitor[0]:g} a {rec.monitor[1]:g}  · sugerido {rec.monitor[2]:g}"]
    out += [f"• {n}" for n in rec.notes]
    return out


def as_dict(info: HardwareInfo, rec: Recommendation) -> dict:
    return {"hardware": asdict(info), "recommendation": asdict(rec)}
