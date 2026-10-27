"""Fontes de vídeo: enumeração de câmeras locais e abertura via OpenCV."""

import glob
import os
import re

# Antes do import do cv2 (lido na inicialização do backend):
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
# RTSP sobre TCP: UDP perde pacotes em Wi-Fi/rede ocupada e corrompe a imagem
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402

NETWORK_PREFIXES = ("rtsp://", "http://", "tcp://", "udp://")


def _num(dev: str) -> int:
    return int(re.search(r"(\d+)$", dev).group(1))


def list_v4l2_devices() -> list:
    """Enumera câmeras V4L2 locais SEM abri-las (abrir atrapalha quem já usa).

    Devolve [{"ref", "name"}]. `ref` é um id estável de hardware (/dev/v4l/by-id
    ou by-path): o número /dev/videoN muda quando a câmera é reconectada. Só o
    nó de captura (index 0) entra; os demais nós da câmera são de metadados."""
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


def open_source(source) -> "cv2.VideoCapture":
    """Abre índice int, caminho /dev/videoN ou URL de rede e valida o 1º frame."""
    if isinstance(source, str) and source.startswith(NETWORK_PREFIXES):
        # timeouts: câmera IP fora do ar não pode travar a thread por minutos
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 6000,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, 6000,
        ])
    elif isinstance(source, int):
        cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
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
