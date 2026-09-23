"""BarGauge.py — Jauge horizontale style racing (thermomètre).

Affiche :
  - Un titre à gauche
  - Une barre de progression cyan → rouge
  - La valeur numérique à droite
  - Des marques de graduation en bas de la barre

Usage :
    gauge = BarGauge("AIR", "°C", -10, 80, red_threshold=0.83)
    gauge.setValue(45.0)
"""

from PyQt5.QtGui import QColor, QPainter, QPen, QFont, QFontMetrics, QLinearGradient
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtWidgets import QWidget

_BG    = QColor(10,  10,  10)     # noir profond
_CYAN  = QColor(255, 220,  0)     # jaune soleil
_RED   = QColor(255,  50,  0)     # orange-rouge
_DIM   = QColor(55,  55,  55)     # barre vide anthracite
_WHITE = QColor(255, 255, 255)    # blanc pur valeur
_LABEL = QColor(255, 200,  0)     # jaune titre/unité
_TICK  = QColor(200, 160,  0)     # jaune foncé graduation


class BarGauge(QWidget):
    """Jauge horizontale compacte style racing."""

    def __init__(self, title, unit, vmin, vmax,
                 red_threshold=0.80, parent=None):
        super().__init__(parent)
        self.title         = title
        self.unit          = unit
        self.min           = vmin
        self.max           = vmax
        self.red_threshold = red_threshold
        self._value        = vmin
        self._power        = 0.0
        self.setMinimumHeight(36)

    # ── API ───────────────────────────────────────────────────────────────────

    def setValue(self, v):
        self._value = v
        span = self.max - self.min
        self._power = max(0.0, min(1.0, (v - self.min) / span)) if span else 0.0
        self.update()

    # ── Rendu ─────────────────────────────────────────────────────────────────

    def paintEvent(self, evt):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        W, H = self.width(), self.height()
        painter.fillRect(0, 0, W, H, _BG)

        ff = self.font().family()

        # ── Dimensions ────────────────────────────────────────────────
        title_font = QFont(ff, 9, QFont.Bold)
        val_font   = QFont(ff, 11, QFont.Bold)
        tick_font  = QFont(ff, 7)

        fm_t = QFontMetrics(title_font)
        fm_v = QFontMetrics(val_font)

        title_w = fm_t.width(self.title) + 6
        val_w   = fm_v.width("-000.0") + 6   # largeur réservée pour la valeur

        # Zone de la barre entre le titre et la valeur
        margin   = 4
        bar_x    = title_w + margin
        bar_w    = W - title_w - val_w - margin * 3
        bar_h    = max(10, H // 3)
        bar_y    = (H - bar_h) // 2 - 2

        # ── Titre ─────────────────────────────────────────────────────
        painter.setPen(QPen(_LABEL))
        painter.setFont(title_font)
        painter.drawText(
            QPointF(margin, bar_y + bar_h / 2 + fm_t.ascent() / 2),
            self.title
        )

        # ── Barre fond (gris) ─────────────────────────────────────────
        painter.setPen(Qt.NoPen)
        painter.setBrush(_DIM)
        painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 3, 3)

        # ── Barre remplie ─────────────────────────────────────────────
        if self._power > 0:
            fill_w  = bar_w * self._power
            red_x   = bar_w * self.red_threshold

            # partie cyan
            cyan_w = min(fill_w, red_x)
            if cyan_w > 0:
                painter.setBrush(_CYAN)
                painter.drawRoundedRect(
                    QRectF(bar_x, bar_y, cyan_w, bar_h), 3, 3
                )

            # partie rouge
            if fill_w > red_x:
                red_w = fill_w - red_x
                painter.setBrush(_RED)
                painter.drawRoundedRect(
                    QRectF(bar_x + red_x, bar_y, red_w, bar_h), 3, 3
                )

        # ── Graduations (5 marques majeures) ──────────────────────────
        N = 5
        tick_y_top = bar_y + bar_h + 2
        tick_y_bot = tick_y_top + 4
        span_val   = self.max - self.min

        painter.setFont(tick_font)
        for i in range(N + 1):
            frac   = i / N
            tx     = bar_x + frac * bar_w
            col    = _RED if frac >= self.red_threshold else _TICK
            pen    = QPen(col)
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawLine(QPointF(tx, tick_y_top), QPointF(tx, tick_y_bot))

            # Label de graduation
            lbl = self._fmt(self.min + frac * span_val)
            fm_lbl = QFontMetrics(tick_font)
            lx  = tx - fm_lbl.width(lbl) / 2
            ly  = tick_y_bot + fm_lbl.ascent() + 1
            if ly < H:
                painter.drawText(QPointF(lx, ly), lbl)

        # ── Valeur numérique à droite ─────────────────────────────────
        val_str = self._fmt(self._value)
        val_col = _RED if self._power >= self.red_threshold else _WHITE
        painter.setPen(QPen(val_col))
        painter.setFont(val_font)
        vx = W - val_w - margin + (val_w - fm_v.width(val_str)) / 2
        vy = bar_y + bar_h / 2 + fm_v.ascent() / 2
        painter.drawText(QPointF(vx, vy), val_str)

        # ── Unité sous la valeur ──────────────────────────────────────
        unit_font = QFont(ff, 7)
        fm_u      = QFontMetrics(unit_font)
        painter.setPen(QPen(_LABEL))
        painter.setFont(unit_font)
        ux = W - val_w - margin + (val_w - fm_u.width(self.unit)) / 2
        uy = vy + fm_u.ascent() + 1
        if uy < H:
            painter.drawText(QPointF(ux, uy), self.unit)

    # ── Formatage ─────────────────────────────────────────────────────────────

    def _fmt(self, v):
        if isinstance(v, float):
            if abs(v) >= 100:
                return f"{v:.0f}"
            if abs(v) >= 10:
                return f"{v:.1f}"
            return f"{v:.2f}"
        return str(v)

