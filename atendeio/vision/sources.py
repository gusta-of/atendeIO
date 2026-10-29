"""Fontes de vídeo: enumeração de câmeras locais e abertura via OpenCV.

Linux: webcams via V4L2 (/dev/v4l/by-id). Windows: webcams via DirectShow (nomes com pygrabber).
RTSP funciona igual nos dois sistemas.
"""

import glob
import logging
import os
import re
import sys

# Antes do import do cv2 (lido na inicialização do backend):
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
# RTSP sobre TCP: UDP perde pacotes em Wi-Fi/rede ocupada e corrompe a imagem
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402

log = logging.getLogger(__name__)

NETWORK_PREFIXES = ("rtsp://", "http://", "tcp://", "udp://")
IS_WINDOWS = sys.platform == "win32"
WIN_PREFIX = "win:"


def _num(dev: str) -> int:
    return int(re.search(r"(\d+)$", dev).group(1))


# -- Windows (DirectShow) ---------------------------------------------------

def _windows_names() -> list:
    """Nomes das câmeras DirectShow, na ordem dos índices. Não abre nenhuma câmera."""
    try:
        from pygrabber.dshow_graph import FilterGraph
    except ImportError:
        log.warning("pygrabber não instalado: webcams USB não serão listadas no Windows.")
        return []
    return FilterGraph().get_input_devices()


def _list_windows_devices() -> list:
    # ref = nome + ocorrência ("Câmera HD#2"): sobrevive a reconexões, ao contrário do índice
    seen, out = {}, []
    for name in _windows_names():
        seen[name] = seen.get(name, 0) + 1
        out.append({"ref": f"{WIN_PREFIX}{name}#{seen[name]}", "name": name})
    return out


def _windows_index(ref: str) -> int:
    """Índice DirectShow atual de um ref estável."""
    name, _, occurrence = ref[len(WIN_PREFIX):].rpartition("#")
    count = 0
    for index, candidate in enumerate(_windows_names()):
        if candidate == name:
            count += 1
            if count == int(occurrence):
                return index
    raise RuntimeError("Câmera local não encontrada.")


# -- API pública ----------------------------------------------------------

def list_v4l2_devices() -> list:
    """Enumera câmeras locais SEM abri-las (abrir atrapalha quem já usa).

    Devolve [{"ref", "name"}]. `ref` é um id estável de hardware: no Linux o
    /dev/v4l/by-id (o número /dev/videoN muda ao reconectar); no Windows, nome +
    ocorrência. Só o nó de captura (index 0) entra no Linux; os demais são de metadados."""
    if IS_WINDOWS:
        return _list_windows_devices()

    def links(folder):
        return {os.path.realpath(p): p for p in sorted(glob.glob(f"/dev/v4l/{folder}/*"))}

    by_id, by_path = links("by-id"), links("by-path")
    out = []
    for dev in sorted(glob.glob("/dev/video*"), key=_num):
        base = f"/sys/class/video4linux/video{_num(dev)}"
        try:
            with open(f"{base}/index") as f:
                if f.read().strip() != "0":
                    continue
            with open(f"{base}/name") as f:
                name = f.read().strip().split(":")[0]
        except OSError:
            name = os.path.basename(dev)
        real = os.path.realpath(dev)
        out.append({"ref": by_id.get(real) or by_path.get(real) or dev, "name": name})
    return out


def local_source(ref: str):
    """Converte o ref guardado na BD na fonte que o OpenCV abre.

    Refs `win:` (webcams DirectShow) passam a índice atual. Os restantes ficam como estão:
    /dev/videoN no Linux, ou um caminho de ficheiro (usado nos testes)."""
    if ref.startswith(WIN_PREFIX):
        return _windows_index(ref)
    return os.path.realpath(ref)


def open_source(source) -> "cv2.VideoCapture":
    """Abre índice int, caminho /dev/videoN ou URL de rede e valida o 1º frame."""
    if isinstance(source, str) and source.startswith(NETWORK_PREFIXES):
        # timeouts: câmera IP fora do ar não pode travar a thread por minutos
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 6000,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, 6000,
        ])
    elif isinstance(source, int):
        backend = cv2.CAP_DSHOW if IS_WINDOWS else cv2.CAP_V4L2
        cap = cv2.VideoCapture(source, backend)
    elif str(source).startswith("/dev/video"):
        cap = cv2.VideoCapture(str(source), cv2.CAP_V4L2)  # FFmpeg nesse caminho falha com QBUF
    else:
        cap = cv2.VideoCapture(str(source))

    if not cap.isOpened():
        cap.release()
        raise RuntimeError("Não consegui abrir a fonte de vídeo.")  # sem a fonte: pode ter credenciais
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # sempre o frame mais novo, não uma fila atrasada
    ok, frame = cap.read()
    if not ok or frame is None:
        cap.release()
        raise RuntimeError("A fonte abriu, mas não veio frame.")
    return cap
