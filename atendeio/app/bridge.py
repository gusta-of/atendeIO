"""Ponte entre as threads do motor e a interface: callbacks do hub (thread da inferência) viram sinais Qt (fila, thread da UI)."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage


def to_qimage(frame) -> QImage:
    """Quadro BGR (numpy) -> QImage com cópia própria (o buffer do OpenCV não pode ser reaproveitado pelo Qt)."""
    h, w = frame.shape[:2]
    return QImage(frame.data, w, h, frame.strides[0], QImage.Format.Format_BGR888).copy()


class Bridge(QObject):
    frame = Signal(int, QImage)    # cam_id, imagem
    state = Signal(int, object)    # cam_id, estado (dict)

    def callback_for(self, cam_id: int):
        def on_frame(frame, state):                 # roda na thread de inferência: só converte e entrega
            self.frame.emit(cam_id, to_qimage(frame))
            self.state.emit(cam_id, state)
        return on_frame
