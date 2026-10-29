"""Recursos da máquina: o app precisa rodar em PC fraco (sem placa de vídeo, até ~4 GB de RAM)."""

import ctypes
import os
import sys
from typing import Optional

LOW_RAM_MB = 6144   # abaixo disso o motor usa o perfil econômico


def total_ram_mb() -> Optional[int]:
    """RAM total em MB, ou None se não der para saber (nesse caso o perfil normal vale)."""
    try:
        if sys.platform == "win32":
            class _Mem(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("tpage", ctypes.c_ulonglong), ("apage", ctypes.c_ulonglong),
                            ("tvirt", ctypes.c_ulonglong), ("avirt", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
            m = _Mem()
            m.length = ctypes.sizeof(_Mem)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return int(m.total // (1024 * 1024))
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024))
    except (OSError, ValueError, AttributeError):
        return None


def low_resource_defaults(ram_mb: Optional[int]) -> dict:
    """Padrões do perfil econômico (PC com pouca RAM): sem o modelo de segmentação (que sozinho pesa ~300 MB e CPU extra),
    poucos pipelines simultâneos e JPEG mais leve. Variáveis ATENDEIO_* explícitas sempre vencem."""
    if ram_mb is None or ram_mb >= LOW_RAM_MB:
        return {}
    return {"occlusion": False, "max_cameras": 3, "max_cameras_per_user": 3, "jpeg_quality": 65}


def pid_alive(pid: int) -> bool:
    """O processo `pid` ainda existe? (Sem `os.kill(pid, 0)` no Windows: lá isso ENCERRA o processo.)"""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
