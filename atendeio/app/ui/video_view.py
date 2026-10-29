from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme


class VideoView(QWidget):
    """Pinta o quadro mais recente (mantendo a proporção) ou uma mensagem. Sem GPU: QPainter em software."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image: Optional[QImage] = None
        self._message = "Aguardando imagem…"
        self.setMinimumHeight(240)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)                       # a altura acompanha a largura (proporção da câmera)
        self.setSizePolicy(policy)

    MAX_HEIGHT = 720

    def _aspect(self) -> float:
        if self._image is not None and not self._image.isNull() and self._image.height():
            return self._image.width() / self._image.height()
        return 16 / 9

    def hasHeightForWidth(self) -> bool:                    # noqa: N802 (Qt)
        return True

    def heightForWidth(self, w: int) -> int:                # noqa: N802 (Qt)
        return max(240, min(self.MAX_HEIGHT, int(w / self._aspect())))

    def sizeHint(self):                                     # noqa: N802 (Qt)
        from PySide6.QtCore import QSize
        return QSize(640, self.heightForWidth(640))

    def set_image(self, image: QImage) -> None:
        first_or_changed = (self._image is None or self._image.size() != image.size())
        self._image, self._message = image, ""
        if first_or_changed:
            self.updateGeometry()                          # proporção nova: refaz a altura
        self.update()

    def set_message(self, text: str) -> None:
        self._image, self._message = None, text
        self.update()

    def has_image(self) -> bool:
        return self._image is not None

    def image_rect(self) -> QRectF:
        """Onde o quadro é desenhado (letterbox) dentro do widget."""
        if self._image is None or self._image.isNull():
            return QRectF(self.rect())
        iw, ih = self._image.width(), self._image.height()
        scale = min(self.width() / iw, self.height() / ih)
        w, h = iw * scale, ih * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000000"))
        if self._image is not None:
            p.drawImage(self.image_rect(), self._image)
        elif self._message:
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect().adjusted(24, 24, -24, -24), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self._message)
