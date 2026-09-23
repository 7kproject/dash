import math
from PyQt5.QtGui import (QColor, QPainterPath, QPainter, QFont,
                         QFontMetrics, QPen)
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtWidgets import QWidget

# ── Palette haute visibilité soleil / anti-reflets ────────────────────────────
# Fond très sombre pour maximiser le contraste même avec reflets de vitres
_BG         = QColor(10,  10,  10)    # noir profond (pas bleuté qui reflète)
# Arc : jaune vif — meilleure lisibilité en plein soleil que le cyan
_CYAN       = QColor(255, 220,  0)    # jaune soleil
_RED        = QColor(255,  50,  0)    # orange-rouge vif (plus lisible que rouge pur)
# Aiguille blanche chaude épaisse
_NEEDLE     = QColor(255, 255, 200)   # blanc chaud
_TICK_MAJOR = QColor(255, 210,  0)    # jaune graduation principale
_TICK_MINOR = QColor(180, 140,  0)    # jaune foncé graduation secondaire
_PIVOT      = QColor(255, 255, 180)   # blanc-jaune pivot
_VALUE      = QColor(255, 255, 255)   # blanc pur pour les chiffres
_LABEL      = QColor(255, 200,  0)    # jaune pour titres et unités


class Dial(QWidget):
    """Cadran style racing — valeur affichée au bout de l'aiguille.

    Signature identique à l'ancienne pour ne pas toucher MainWindow :
        Dial(title, unit, tmin, tmax, green, yellow, red, pc, red_threshold)
    """

    # Rayon de l'arc — utilisé pour le calcul de la position du texte valeur
    _R_OUT  = 88
    _R_IN   = 76
    _START  = 225   # degré de départ de l'arc (bas-gauche)
    _SPAN   = 270   # balayage total

    def __init__(self, title, unit, tmin, tmax,
                 green=0.98, yellow=0.20, red=0, pc=1,
                 red_threshold=0.75, red_low=None, parent=None):
        """
        red_threshold : fraction haute [0-1] au-delà de laquelle l'arc vire au rouge.
        red_low       : fraction basse [0-1] en dessous de laquelle l'arc vire au rouge.
                        None = pas de zone rouge basse.
        """
        QWidget.__init__(self, parent)
        self.title         = title
        self.unit          = unit
        self.min           = tmin
        self.max           = tmax
        self.speed         = tmin
        self.red_threshold = red_threshold   # seuil haut (fraction)
        self.red_low       = red_low         # seuil bas (fraction) ou None
        self._power        = 0.0

    # ── API publique ──────────────────────────────────────────────────────────

    def setSpeed(self, speed):
        self.speed  = speed
        span = self.max - self.min
        self._power = max(0.0, min(1.0, (speed - self.min) / span)) if span else 0.0
        self.update()

    def setUnit(self, unit):
        self.unit = unit

    # Stubs de compatibilité
    def setPowerGradient(self, g):    pass
    def setDisplayPowerPath(self, v): pass
    def setUnitTextColor(self, c):    pass
    def setSpeedTextColor(self, c):   pass
    def setPowerPathColor(self, c):   pass

    # ── Rendu principal ───────────────────────────────────────────────────────

    def paintEvent(self, evt):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h  = self.width(), self.height()
        side  = min(w, h)
        scale = side / 200.0

        painter.fillRect(0, 0, w, h, _BG)
        painter.translate(w / 2.0, h / 2.0)
        painter.scale(scale, scale)

        self._drawArc(painter)
        self._drawTicks(painter)
        self._drawNeedle(painter)
        self._drawLabel(painter)     # titre en bas
        self._drawValueAtNeedle(painter)   # valeur + unité au bout de l'aiguille

    # ── Arc ───────────────────────────────────────────────────────────────────

    def _drawArc(self, painter):
        """Arc en trois zones possibles :
           [rouge-bas 0→red_low] [jaune red_low→red_high] [rouge-haut red_high→1]
        L'arc coloré progresse de 0 jusqu'à _power ; les zones non atteintes
        restent en gris anthracite.
        """
        r_out, r_in = self._R_OUT, self._R_IN
        thick       = r_out - r_in
        rect        = QRectF(-r_out, -r_out, r_out * 2, r_out * 2)

        def _arc(col, start_frac, span_frac):
            """Dessine un segment d'arc coloré."""
            if span_frac <= 0:
                return
            pen = QPen(col)
            pen.setWidth(thick)
            pen.setCapStyle(Qt.FlatCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(rect,
                            int((self._START - start_frac * self._SPAN) * 16),
                            int(-span_frac * self._SPAN * 16))

        # ── Arc de fond (gris anthracite, plein) ──────────────────────
        pen_bg = QPen(QColor(55, 55, 55))
        pen_bg.setWidth(thick)
        pen_bg.setCapStyle(Qt.FlatCap)
        painter.setPen(pen_bg)
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(rect, int(self._START * 16), int(-self._SPAN * 16))

        # ── Dessin de l'arc coloré jusqu'à _power ─────────────────────
        p        = self._power            # fraction actuelle [0-1]
        r_lo     = self.red_low  if self.red_low  is not None else 0.0
        r_hi     = self.red_threshold

        # Zone rouge basse  [0 → r_lo]
        if r_lo > 0:
            _arc(_RED, 0.0, min(p, r_lo))

        # Zone jaune        [r_lo → r_hi]
        if p > r_lo:
            yellow_start = r_lo
            yellow_end   = min(p, r_hi)
            _arc(_CYAN, yellow_start, yellow_end - yellow_start)

        # Zone rouge haute  [r_hi → 1]
        if p > r_hi:
            _arc(_RED, r_hi, p - r_hi)

    # ── Graduations ───────────────────────────────────────────────────────────

    def _drawTicks(self, painter):
        N_MAJ = 8
        N_MIN = 4
        total = N_MAJ * N_MIN
        span  = self.max - self.min

        for i in range(total + 1):
            frac  = i / total
            a_deg = self._START - frac * self._SPAN
            a_rad = math.radians(a_deg)
            ca, sa = math.cos(a_rad), math.sin(a_rad)

            is_maj  = (i % N_MIN == 0)
            r_outer = self._R_OUT
            r_inner = self._R_IN + 2 if is_maj else self._R_IN + 6

            p1 = QPointF(r_outer * ca, -r_outer * sa)
            p2 = QPointF(r_inner * ca, -r_inner * sa)

            pen = QPen(_TICK_MAJOR if is_maj else _TICK_MINOR)
            pen.setWidthF(1.8 if is_maj else 0.8)
            painter.setPen(pen)
            painter.drawLine(p1, p2)

            if is_maj:
                val   = self.min + frac * span
                txt   = self._fmt_tick(val)
                r_lbl = 62
                lx, ly = r_lbl * ca, -r_lbl * sa
                # rouge si dans zone haute OU dans zone basse
                r_lo  = self.red_low if self.red_low is not None else -1
                in_red = frac >= self.red_threshold or frac <= r_lo
                col   = _RED if in_red else _CYAN
                font  = QFont(self.font().family(), 8, QFont.Bold)
                painter.setPen(QPen(col))
                painter.setFont(font)
                fm = QFontMetrics(font)
                painter.drawText(
                    QPointF(lx - fm.width(txt) / 2, ly + fm.ascent() / 2),
                    txt
                )

    def _fmt_tick(self, val):
        if abs(val) >= 1000:
            return f"{val / 1000:.0f}k"
        if isinstance(val, float) and val != int(val):
            return f"{val:.1f}"
        return f"{int(val)}"

    # ── Aiguille ──────────────────────────────────────────────────────────────

    def _drawNeedle(self, painter):
        a_deg = self._START - self._power * self._SPAN
        a_rad = math.radians(a_deg)
        ca, sa = math.cos(a_rad), math.sin(a_rad)

        length, tail, hw = 80, 15, 4   # hw=4 → aiguille plus épaisse, visible au soleil

        tip  = QPointF( length * ca, -length * sa)
        tl   = QPointF(-tail   * ca,  tail   * sa)
        pl   = QPointF(-hw * sa, -hw * ca)    # perpendiculaire gauche
        pr   = QPointF( hw * sa,  hw * ca)    # perpendiculaire droite

        path = QPainterPath()
        path.moveTo(tip)
        path.lineTo(pr)
        path.lineTo(tl)
        path.lineTo(pl)
        path.closeSubpath()

        painter.save()
        painter.setBrush(_NEEDLE)
        painter.setPen(Qt.NoPen)
        painter.drawPath(path)

        painter.setBrush(_PIVOT)
        pen_piv = QPen(QColor(100, 130, 160))
        pen_piv.setWidthF(1.5)
        painter.setPen(pen_piv)
        painter.drawEllipse(QPointF(0, 0), 6, 6)
        painter.restore()

    # ── Valeur numérique fixe au centre du cadran ─────────────────────────────

    def _drawValueAtNeedle(self, painter):
        """Affiche la valeur et l'unité à position fixe au centre du cadran,
        avec un fond semi-transparent pour rester lisible par-dessus l'aiguille."""
        ff = self.font().family()

        val_str   = self._fmt_value()
        val_font  = QFont(ff, 18, QFont.Bold)
        fm_v      = QFontMetrics(val_font)

        unit_font = QFont(ff, 9)
        fm_u      = QFontMetrics(unit_font)

        # Zone fixe : centrée horizontalement, légèrement sous le centre (y=20)
        vx, vy = 0.0, 20.0

        tw = max(fm_v.width(val_str), fm_u.width(self.unit)) + 10
        th = fm_v.height() + fm_u.height() + 4
        bg_rect = QRectF(-tw / 2, vy - fm_v.ascent() - 4, tw, th)

        painter.save()
        painter.setBrush(QColor(0, 10, 25, 210))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(bg_rect, 5, 5)

        # Valeur
        painter.setPen(QPen(_VALUE))
        painter.setFont(val_font)
        painter.drawText(
            QPointF(-fm_v.width(val_str) / 2.0, vy),
            val_str
        )

        # Unité
        painter.setPen(QPen(_LABEL))
        painter.setFont(unit_font)
        painter.drawText(
            QPointF(-fm_u.width(self.unit) / 2.0, vy + fm_u.ascent() + 2),
            self.unit
        )
        painter.restore()

    # ── Titre en bas ──────────────────────────────────────────────────────────

    def _drawLabel(self, painter):
        ff   = self.font().family()
        font = QFont(ff, 10, QFont.Bold)
        fm   = QFontMetrics(font)
        painter.setPen(QPen(_LABEL))
        painter.setFont(font)
        painter.drawText(
            QPointF(-fm.width(self.title) / 2.0, 92),
            self.title
        )

    # ── Formatage ─────────────────────────────────────────────────────────────

    def _fmt_value(self):
        v = self.speed
        if isinstance(v, float):
            if abs(v) >= 1000:
                return f"{v:.0f}"
            if abs(v) >= 10:
                return f"{v:.1f}"
            return f"{v:.2f}"
        return str(v)

