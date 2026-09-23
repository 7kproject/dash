# =============================================================================
# MainWindow.py — Dashboard tableau de bord moteur
# =============================================================================
# Ce fichier contient :
#   - Le décodage des trames CAN (ECU → CanData thread-safe)
#   - Le mode simulation (replay de simdata.txt sans matériel CAN)
#   - Les fonctions GPS (NMEA / port série)
#   - Les widgets PyQt5 : DigitalSpeed, GpsPoint, Track
#   - La fenêtre principale MainWindow
# =============================================================================

# ── Imports standard ─────────────────────────────────────────────────────────
import os
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock, Thread

# ── Imports tierces parties ───────────────────────────────────────────────────
import numpy
import can
import serial
from matplotlib import pyplot
from pylab import (close, figure, get_current_fig_manager,
                   plot, xlabel, ylabel, title, grid, connect, show, ioff)

# ── Imports PyQt5 ─────────────────────────────────────────────────────────────
from PyQt5.QtWidgets import QMainWindow, QGridLayout, QApplication
from PyQt5.QtCore import QObject, pyqtSignal, QEvent, QTimer, Qt
from PyQt5.QtGui import QIcon, QColor, QPalette

# ── Import UI générée par Qt Designer ────────────────────────────────────────
from ui_mainwindow import Ui_MainWindow

# ── Import du widget cadran ───────────────────────────────────────────────────
from Dial import Dial
from BarGauge import BarGauge


# =============================================================================
# CONFIGURATION
# =============================================================================

# Mettre à True pour tourner sans bus CAN ni port série (dev / WSL)
SIMULATION_MODE = True

# Délai entre chaque trame CAN rejouée en simulation (≈ cadence bus réel)
SIM_FRAME_DELAY = 0.02  # secondes

# Taille maximale de l'historique glissant (30 min × 20 Hz = 36 000 points)
HISTORY_MAXLEN = 36_000

# En-tête CSV — tous les signaux CAN dans l'ordre du snapshot()
LOG_CHANNEL_NAMES = [
    # 0x300
    "rpm", "tps_pct", "kfuel_map_pct", "map_mbar", "idle_learn_pct", "dthrot",
    # 0x301
    "lambda2", "inj_h_perc", "ae_usec", "iidle_pct",
    # 0x302
    "km_h", "dc_base_idle_pct", "idle_out_pct",
    # 0x303
    "ivct_angle_deg", "evct_angle_deg", "ivct_target_deg", "evct_target_deg", "dbw_tps1_pct",
    # 0x304
    "base_inj_pw_usec", "run_pw1_usec", "sa_base_deg", "sa_out_deg",
    # 0x305
    "lambda1", "target_lambda", "run_pw2_usec", "clc1_pct", "clc2_pct",
    # 0x306
    "base_boost_dc_pct", "boost_out_pct", "oil_p_kpa", "fuel_p_bar",
    # 0x307
    "sa_knock1_deg", "sa_knock2_deg", "sa_knock3_deg", "sa_knock4_deg",
    "i_boost", "target_boost_mbar",
    # 0x308
    "batt_V", "djv_batt_usec", "dwell_usec",
    # 0x309
    "tps1i_V", "pps1i_V", "pps2i_V", "tps_drv_req_pct",
    # 0x30A
    "tps2i_V", "tps_pps_fault", "pps_scaled_pct", "pps1_pct", "pps2_pct",
    "tps1_pct", "tps2_pct",
    # 0x30B
    "th2o_C", "toil_C", "kfuel_crk_pct", "tair_C",
    # 0x30C
    "erun_timer_s", "tair_i_V", "lambda_i_V", "kfuel_th2o_pct", "kfuel_tair_pct",
    # 0x30D
    "crk_cnt", "kfuel_baro_pct", "kfuel_p_pct", "osa_tair_deg", "rpm_target_idle",
    # 0x30F
    "fuel_p_target_bar", "fuel_level_V", "fuel_p_ctrl_dc_pct",
]

# Répertoire de sortie des logs (relatif au script)
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Nom du fichier de log pour cette session (numéroté séquentiellement)
# → fonctionne sans horloge RTC (ex. Raspberry Pi sans pile)
_existing     = len([f for f in os.listdir(LOG_DIR) if f.endswith("_session.csv")])
_SESSION_TAG  = f"{_existing + 1:03d}"
LOG_FILE_PATH = os.path.join(LOG_DIR, f"{_SESSION_TAG}_session.csv")


# =============================================================================
# DONNÉES CAN — structure thread-safe
# =============================================================================

@dataclass
class CanData:
    """Valeurs courantes lues depuis le bus CAN (tous signaux GDI4).

    Toutes les lectures/écritures doivent se faire sous `lock` pour éviter
    les lectures partielles entre le thread CAN et le thread Qt.
    """
    lock:             Lock  = field(default_factory=Lock, repr=False)
    # ── 0x300 ────────────────────────────────────────────────────────
    rpm:              int   = 0      # Régime moteur (tr/min)
    tps:              float = 0.0    # Position papillon (%)
    kfuel_map:        float = 0.0    # Correction carburant MAP (%)
    map_:             float = 0.0    # Pression collecteur (mbar)
    idle_learn:       float = 0.0    # Valeur apprentissage ralenti (%)
    dthrot:           float = 0.0    # Delta position papillon
    # ── 0x301 ────────────────────────────────────────────────────────
    lambda2:          float = 0.0    # Lambda sonde 2 (AFR)
    inj_h_perc:       float = 0.0    # Injection étagée (%)
    ae:               float = 0.0    # Enrichissement accélération (µs)
    iidle:            float = 0.0    # Intégrateur ralenti (%)
    # ── 0x302 ────────────────────────────────────────────────────────
    km:               float = 0.0    # Vitesse roue (km/h)
    dc_base_idle:     float = 0.0    # Rapport cyclique ralenti base (%)
    idle_out:         float = 0.0    # Rapport cyclique ralenti final (%)
    # ── 0x303 ────────────────────────────────────────────────────────
    ivct_angle:       float = 0.0    # Position arbre à cames admission (deg)
    evct_angle:       float = 0.0    # Position arbre à cames échappement (deg)
    ivct_target:      float = 0.0    # Cible admission (deg)
    evct_target:      float = 0.0    # Cible échappement (deg)
    dbw_tps1:         float = 0.0    # TPS fil de gaz primaire (%)
    # ── 0x304 ────────────────────────────────────────────────────────
    base_inj_pw:      float = 0.0    # Durée injection base (µs)
    run_pw1:          float = 0.0    # Durée injection finale banque 1 (µs)
    sa_base:          float = 0.0    # Avance allumage base (deg)
    sa_out:           float = 0.0    # Avance allumage finale (deg)
    # ── 0x305 ────────────────────────────────────────────────────────
    lambda1:          float = 0.0    # Lambda sonde 1 (AFR)
    target_lambda:    float = 0.0    # Lambda cible
    run_pw2:          float = 0.0    # Durée injection finale banque 2 (µs)
    clc1:             float = 0.0    # Boucle fermée banque 1 (%)
    clc2:             float = 0.0    # Boucle fermée banque 2 (%)
    # ── 0x306 ────────────────────────────────────────────────────────
    base_boost_dc:    float = 0.0    # Rapport cyclique boost base (%)
    boost_out:        float = 0.0    # Rapport cyclique boost final (%)
    oil_p:            float = 0.0    # Pression huile (kPa)
    fuel:             float = 0.0    # Pression carburant (bar)
    # ── 0x307 ────────────────────────────────────────────────────────
    sa_knock1:        float = 0.0    # Retard cliquetis cylindre 1 (deg)
    sa_knock2:        float = 0.0    # Retard cliquetis cylindre 2 (deg)
    sa_knock3:        float = 0.0    # Retard cliquetis cylindre 3 (deg)
    sa_knock4:        float = 0.0    # Retard cliquetis cylindre 4 (deg)
    i_boost:          float = 0.0    # Terme intégral boost
    target_boost:     float = 0.0    # Pression boost cible (mbar)
    # ── 0x308 ────────────────────────────────────────────────────────
    volt:             float = 0.0    # Tension batterie (V)
    djv_batt:         float = 0.0    # Correction tension injecteurs (µs)
    dwell:            float = 0.0    # Temps de charge bobine (µs)
    # ── 0x309 ────────────────────────────────────────────────────────
    tps1i:            float = 0.0    # Tension brute TPS1 (V)
    pps1i:            float = 0.0    # Tension brute pédale 1 (V)
    pps2i:            float = 0.0    # Tension brute pédale 2 (V)
    tps_drv_req:      float = 0.0    # Consigne position papillon (%)
    # ── 0x30A ────────────────────────────────────────────────────────
    tps2i:            float = 0.0    # Tension brute TPS2 (V)
    tps_pps_fault:    int   = 0      # Code défaut TPS/pédale
    pps_scaled:       float = 0.0    # Position pédale finale (%)
    pps1:             float = 0.0    # Position pédale 1 (%)
    pps2:             float = 0.0    # Position pédale 2 (%)
    tps1:             float = 0.0    # Position papillon 1 (%)
    tps2:             float = 0.0    # Position papillon 2 (%)
    # ── 0x30B ────────────────────────────────────────────────────────
    temp:             float = 0.0    # Température eau moteur (°C)
    toil:             float = 0.0    # Température huile (°C)
    kfuel_crk:        float = 0.0    # Correction carburant démarrage (%)
    air:              float = 0.0    # Température air admission (°C)
    # ── 0x30C ────────────────────────────────────────────────────────
    erun_timer:       float = 0.0    # Durée de fonctionnement moteur (s)
    tair_i:           float = 0.0    # Tension brute capteur air (V)
    lambda_i:         float = 0.0    # Tension brute sonde lambda (V)
    kfuel_th2o:       float = 0.0    # Correction carburant eau (%)
    kfuel_tair:       float = 0.0    # Correction carburant air (%)
    # ── 0x30D ────────────────────────────────────────────────────────
    crk_cnt:          int   = 0      # Compteur rotations vilebrequin
    kfuel_baro:       float = 0.0    # Correction carburant baro (%)
    kfuel_p:          float = 0.0    # Correction carburant pression (%)
    osa_tair:         float = 0.0    # Correction avance temp air (deg)
    rpm_target_idle:  int   = 0      # Régime cible ralenti (tr/min)
    # ── 0x30F ────────────────────────────────────────────────────────
    fuel_p_target:    float = 0.0    # Pression carburant cible (bar)
    fuel_level:       float = 0.0    # Niveau carburant brut (V)
    fuel_p_ctrl_dc:   float = 0.0    # Rapport cyclique pompe carburant (%)

    def snapshot(self):
        """Retourne un tuple ordonné de toutes les valeurs (même ordre que LOG_CHANNEL_NAMES)."""
        with self.lock:
            return (
                self.rpm, self.tps, self.kfuel_map, self.map_, self.idle_learn, self.dthrot,
                self.lambda2, self.inj_h_perc, self.ae, self.iidle,
                self.km, self.dc_base_idle, self.idle_out,
                self.ivct_angle, self.evct_angle, self.ivct_target, self.evct_target, self.dbw_tps1,
                self.base_inj_pw, self.run_pw1, self.sa_base, self.sa_out,
                self.lambda1, self.target_lambda, self.run_pw2, self.clc1, self.clc2,
                self.base_boost_dc, self.boost_out, self.oil_p, self.fuel,
                self.sa_knock1, self.sa_knock2, self.sa_knock3, self.sa_knock4,
                self.i_boost, self.target_boost,
                self.volt, self.djv_batt, self.dwell,
                self.tps1i, self.pps1i, self.pps2i, self.tps_drv_req,
                self.tps2i, self.tps_pps_fault, self.pps_scaled, self.pps1, self.pps2,
                self.tps1, self.tps2,
                self.temp, self.toil, self.kfuel_crk, self.air,
                self.erun_timer, self.tair_i, self.lambda_i, self.kfuel_th2o, self.kfuel_tair,
                self.crk_cnt, self.kfuel_baro, self.kfuel_p, self.osa_tair, self.rpm_target_idle,
                self.fuel_p_target, self.fuel_level, self.fuel_p_ctrl_dc,
            )


# Instance unique partagée entre les threads
can_data = CanData()


# =============================================================================
# DÉCODAGE TRAMES CAN
# =============================================================================

def _u16(d, b):
    """Unsigned short 16 bits à partir de l'octet b (MSB) dans la chaîne hex d."""
    return int(d[b*2:b*2+2], 16) * 256 + int(d[b*2+2:b*2+4], 16)

def _s16(d, b):
    """Signed short 16 bits (complément à 2) à partir de l'octet b dans la chaîne hex d."""
    v = _u16(d, b)
    return v - 65536 if v > 32767 else v

def _u8(d, b):
    """Unsigned byte à partir de l'octet b dans la chaîne hex d."""
    return int(d[b*2:b*2+2], 16)


def decodeData(message):
    """Décode une trame CAN brute et met à jour can_data (thread-safe).

    Format attendu (python-can str(message)) :
      - canid  : caractères [41:44]
      - données: caractères [69:]  (octets hex séparés par espaces)
    """
    message = str(message)
    canid   = message[41:44].strip().lower().lstrip('0') or '0'
    data    = message[69:].replace(' ', '')
    if len(data) < 16:
        return  # trame trop courte, on ignore

    with can_data.lock:

        if canid == '300':
            can_data.rpm        = _u16(data, 0)                          # tr/min
            can_data.tps        = _u8(data, 2) * 100.0 / 255.0           # %
            can_data.kfuel_map  = _u8(data, 3) * 400.0 / 255.0           # %
            can_data.map_       = _s16(data, 4)                          # mbar
            can_data.idle_learn = _u16(data, 6) * 0.00038696             # %

        elif canid == '301':
            can_data.dthrot     = _s16(data, 0)                          # delta papillon
            can_data.lambda2    = _u8(data, 2) * 2.0 / 255.0 * 14.7     # AFR
            can_data.inj_h_perc = _u8(data, 3) * 100.0 / 255.0          # %
            can_data.ae         = _u16(data, 4)                          # µs
            can_data.iidle      = _s16(data, 6) * 0.001                  # %

        elif canid == '302':
            can_data.km           = _u16(data, 0) * 0.1                  # km/h
            can_data.dc_base_idle = _u16(data, 2) * 100.0 / 255.0        # %
            can_data.idle_out     = _u16(data, 4) * 100.0 / 255.0        # %

        elif canid == '303':
            can_data.ivct_angle  = _s16(data, 0) * 0.25                  # deg
            can_data.evct_angle  = _s16(data, 2) * 0.25                  # deg
            can_data.ivct_target = _u8(data, 4) * 0.25                   # deg
            can_data.evct_target = _u8(data, 5) * 0.25                   # deg
            can_data.dbw_tps1    = _s16(data, 6) * 100.0 / 1023.0        # %

        elif canid == '304':
            can_data.base_inj_pw = _u16(data, 0)                         # µs
            can_data.run_pw1     = _u16(data, 2)                         # µs
            can_data.sa_base     = _s16(data, 4) * 0.25                  # deg
            can_data.sa_out      = _s16(data, 6) * 0.25                  # deg

        elif canid == '305':
            can_data.lambda1       = _u8(data, 0) * 2.0 / 255.0 * 14.7  # AFR
            can_data.target_lambda = _u8(data, 1) * 2.55 / 255.0         # lambda
            can_data.run_pw2       = _u16(data, 2)                        # µs
            can_data.clc1          = _s16(data, 4) * 0.05                 # %
            can_data.clc2          = _s16(data, 6) * 0.05                 # %

        elif canid == '306':
            can_data.base_boost_dc = _u8(data, 1) * 100.0 / 255.0        # %
            can_data.boost_out     = _u16(data, 2) * 100.0 / 255.0       # %
            can_data.oil_p         = _u16(data, 4) * 0.01                 # kPa
            can_data.fuel          = _u16(data, 6) * 0.1                  # bar

        elif canid == '307':
            can_data.sa_knock1    = _u8(data, 0) * 0.25                  # deg
            can_data.sa_knock2    = _u8(data, 1) * 0.25                  # deg
            can_data.sa_knock3    = _u8(data, 2) * 0.25                  # deg
            can_data.sa_knock4    = _u8(data, 3) * 0.25                  # deg
            can_data.i_boost      = _u16(data, 4)
            can_data.target_boost = _u16(data, 6)                        # mbar

        elif canid == '308':
            can_data.volt      = _u16(data, 0) * 18.0 / 1023.0           # V
            can_data.djv_batt  = _u16(data, 2)                           # µs
            can_data.dwell     = _u16(data, 6)                           # µs

        elif canid == '309':
            can_data.tps1i       = _u16(data, 0) * 5.0 / 1023.0          # V
            can_data.pps1i       = _u16(data, 2) * 5.0 / 1023.0          # V
            can_data.pps2i       = _u16(data, 4) * 5.0 / 1023.0          # V
            can_data.tps_drv_req = _u16(data, 6) * 100.0 / 1023.0        # %

        elif canid == '30a':
            can_data.tps2i         = _u16(data, 0) * 5.0 / 1023.0        # V
            can_data.tps_pps_fault = _u8(data, 2)
            can_data.pps_scaled    = _u8(data, 3) * 100.0 / 255.0        # %
            can_data.pps1          = _u8(data, 4) * 100.0 / 255.0        # %
            can_data.pps2          = _u8(data, 5) * 100.0 / 255.0        # %
            can_data.tps1          = _u8(data, 6) * 100.0 / 255.0        # %
            can_data.tps2          = _u8(data, 7) * 100.0 / 255.0        # %

        elif canid == '30b':
            can_data.temp      = _u8(data, 0) * 160.0 / 255.0 - 10.0    # °C
            can_data.toil      = _u8(data, 1) * 160.0 / 255.0 - 10.0    # °C
            can_data.kfuel_crk = _u8(data, 2) * 800.0 / 255.0           # %
            can_data.air       = _u8(data, 3) * 160.0 / 255.0 - 10.0    # °C

        elif canid == '30c':
            can_data.erun_timer = _u16(data, 0) * 0.05                   # s
            can_data.tair_i     = _u16(data, 2) * 5.0 / 1023.0           # V
            can_data.lambda_i   = _u16(data, 4) * 5.0 / 1023.0           # V
            can_data.kfuel_th2o = _u8(data, 6) * 400.0 / 255.0           # %
            can_data.kfuel_tair = _u8(data, 7) * 200.0 / 255.0           # %

        elif canid == '30d':
            can_data.crk_cnt         = _u16(data, 0)                     # rev
            can_data.kfuel_baro      = _u8(data, 2) * 400.0 / 255.0      # %
            can_data.kfuel_p         = _u8(data, 3) * 400.0 / 255.0      # %
            can_data.osa_tair        = _s16(data, 4) * 0.25              # deg
            can_data.rpm_target_idle = _u16(data, 6)                     # tr/min

        elif canid == '30f':
            can_data.fuel_p_target  = _s16(data, 0) * 0.1                # bar
            can_data.fuel_level     = _u16(data, 2) * 5.0 / 1023.0       # V
            can_data.fuel_p_ctrl_dc = _u16(data, 4) * 100.0 / 1023.0     # %


# =============================================================================
# SIMULATION CAN (rejeu de simdata.txt)
# =============================================================================

def parse_can_log(filepath):
    """Lit simdata.txt et retourne une liste de tuples (canid, data_hex).

    Format attendu de chaque ligne :
        can0  300   [8]  00 00 FF 00 00 00 00 00
    """
    entries = []
    with open(filepath, 'r') as f:
        for line in f:
            parts = line.split()
            if len(parts) < 11 or parts[0] != 'can0':
                continue
            try:
                canid    = parts[1].lstrip('0').lower() or '0'
                data_hex = ''.join(parts[3:11])
                entries.append((canid, data_hex))
            except Exception:
                continue
    return entries


def simulate_can_data():
    """Thread de simulation : rejoue en boucle les trames de simdata.txt."""
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'simdata.txt')
    while True:
        entries = parse_can_log(log_path)
        if not entries:
            time.sleep(1)
            continue
        for canid, data_hex in entries:
            # Reconstruit un faux str(message) compatible avec decodeData()
            # [41:44] = canid (3 chars), [69:] = octets hex séparés par espaces
            fake = (' ' * 41
                    + canid.rjust(3)
                    + ' ' * (69 - 44)
                    + ' '.join(data_hex[i:i+2] for i in range(0, len(data_hex), 2)))
            decodeData(fake)
            time.sleep(SIM_FRAME_DELAY)


# =============================================================================
# RÉCEPTION CAN RÉELLE (socketcan)
# =============================================================================

def can_rx_task():
    """Thread de réception CAN sur bus réel (socketcan / can0, 500 kbit/s)."""
    bus = can.interface.Bus(interface='socketcan', channel='can0', bitrate=500000)
    while True:
        message = bus.recv()
        decodeData(message)


# ── Démarrage du thread CAN (simulation ou réel) ─────────────────────────────
if SIMULATION_MODE:
    _can_thread = Thread(target=simulate_can_data, daemon=True)
else:
    _can_thread = Thread(target=can_rx_task, daemon=True)
_can_thread.start()


# =============================================================================
# PORT SÉRIE GPS (NMEA)
# =============================================================================

# En mode simulation le port série n'est pas ouvert
if SIMULATION_MODE:
    ser = None
else:
    ser = serial.Serial(
        port='/dev/ttyACM0',
        baudrate=9600,
        parity=serial.PARITY_ODD,
        stopbits=serial.STOPBITS_TWO,
        bytesize=serial.SEVENBITS
    )
    ser.isOpen()


def readString():
    """Lit une trame NMEA complète depuis le port série (commence par '$').
    Retourne une chaîne vide en mode simulation.
    """
    if SIMULATION_MODE:
        return ""
    while True:
        while ser.read().decode("utf-8") != '$':
            pass
        return ser.readline().decode("utf-8")


def checksum(line):
    """Vérifie le checksum XOR d'une trame NMEA.
    Retourne True si le checksum est correct, False sinon.
    """
    checkString = line.partition("*")
    computed    = 0
    for c in checkString[0]:
        computed ^= ord(c)
    try:
        expected = int(checkString[2].rstrip(), 16)
    except Exception:
        print("Checksum: chaîne invalide")
        return False
    if computed != expected:
        print(f"Checksum error: {hex(computed)} != {hex(expected)}")
        return False
    return True


def getLatLng(latString, lngString):
    """Convertit les chaînes NMEA DDMM.MMMMM en degrés décimaux."""
    lat = lng = ""
    if len(latString) > 0:
        lat = latString[:2].lstrip('0') + "." + "%.7s" % str(
            float(latString[2:]) * 1.0 / 60.0).lstrip("0.")
        lng = lngString[:3].lstrip('0') + "." + "%.7s" % str(
            float(lngString[3:]) * 1.0 / 60.0).lstrip("0.")
    return (lat, lng)


def getGpsSpeed(lines):
    """Retourne la vitesse GPS en km/h à partir d'une trame NMEA décodée."""
    ch = lines[7] if lines[7] != '' else '0'
    return int(float(ch) * 1.852)


# =============================================================================
# WIDGETS
# =============================================================================

def clickable(widget):
    """Rend un widget quelconque cliquable et tactile via un event filter.
    Retourne un signal clicked() utilisable comme un QPushButton.
    """
    widget.setAttribute(Qt.WA_AcceptTouchEvents, True)

    class Filter(QObject):
        clicked = pyqtSignal()

        def eventFilter(self, obj, event):
            if obj == widget:
                if event.type() == QEvent.MouseButtonRelease:
                    if obj.rect().contains(event.pos()):
                        self.clicked.emit()
                        return True
                elif event.type() == QEvent.TouchEnd:
                    self.clicked.emit()
                    return True
            return False

    tfilter = Filter(widget)
    widget.installEventFilter(tfilter)
    return tfilter.clicked


# =============================================================================
# CLASSES GPS
# =============================================================================

class GpsPoint:
    """Représente un point GPS (latitude / longitude en degrés décimaux)."""

    def __init__(self, Lat=0.0, Long=0.0):
        self.latitude  = Lat
        self.longitude = Long


class Track:
    """Gestion du circuit : détection du passage sur la ligne d'arrivée.

    Coordonnées par défaut : circuit de Sussargues.
    """

    finishLinePoint1 = GpsPoint(43.7112163, 4.011291)
    finishLinePoint2 = GpsPoint(43.7112131, 4.0025198)

    def isFinishLinePassed(self, start, finish):
        """Retourne 1 si le segment [start, finish] coupe la ligne d'arrivée,
        0 sinon. Utilise le test d'intersection de segments.
        """
        delta0 = ((self.finishLinePoint1.latitude  - self.finishLinePoint2.latitude)
                  * (finish.longitude - start.longitude)
                  - (self.finishLinePoint1.longitude - self.finishLinePoint2.longitude)
                  * (finish.latitude  - start.latitude))
        if delta0 == 0.0:
            return 0  # segments parallèles

        delta1 = ((self.finishLinePoint1.longitude - self.finishLinePoint2.longitude)
                  * (start.latitude  - self.finishLinePoint2.latitude)
                  - (self.finishLinePoint1.latitude  - self.finishLinePoint2.latitude)
                  * (start.longitude - self.finishLinePoint2.longitude))
        delta2 = ((finish.longitude - start.longitude)
                  * (start.latitude  - self.finishLinePoint2.latitude)
                  - (finish.latitude  - start.latitude)
                  * (start.longitude - self.finishLinePoint2.longitude))

        ka = delta1 / delta0
        kb = delta2 / delta0

        if ka < 0 or ka > 1 or kb < 0 or kb > 1:
            return 0  # intersection hors des segments
        return 1


# =============================================================================
# FENÊTRE PRINCIPALE
# =============================================================================

class MainWindow(QMainWindow):
    """Fenêtre principale du tableau de bord.

    Layout (QGridLayout 7 lignes × 12 colonnes) :
      Grands cadrans (rows 0-5) :
        Col 0-3  / Row 0-4 : AFR   (gauche)
        Col 4-7  / Row 0-5 : RPM   (centre dominant, 6 lignes)
        Col 8-11 / Row 0-4 : BOOST (droite)
        Col 0-3  / Row 4-5 : TEMP  (gauche bas)
        Col 8-11 / Row 4-5 : (vide ou futur)
      Jauges BarGauge (row 6, bande inférieure) :
        Col 0-2  : AIR
        Col 3-5  : FUEL
        Col 6-8  : TPS
        Col 9-11 : BATT
    """

    # ── Définition des canaux ─────────────────────────────────────────────────
    # Chaque entrée : (attribut can_data, label figure, xlabel, ylabel, titre graphe)
    _CHANNELS = [
        ('temp',    'TEMPERATURE', 'time(s)',     'Température', 'Eau °C'),
        ('lambda1', 'AFR',         'events',      'AFR',         'AFR'),
        ('volt',    'VOLTAGE',     'events',      'Volts',       'Tension V'),
        ('air',     'AIR',         'events',      'Air °C',      'Température air'),
        ('fuel',    'FUEL',        'events',      'Carburant',   'Pression carburant'),
        ('rpm',     'RPM',         'events',      'tr/min',      'Régime moteur'),
        ('map_',    'BOOST',       'events',      'Boost',       'Boost bar'),
        ('tps',     'TPS',         'events',      'TPS %',       'Position papillon'),
    ]

    myTrack = Track()
    start   = GpsPoint(0, 0)

    # ------------------------------------------------------------------
    def myShutDown(self):
        """Éteint le système (Raspberry Pi / Linux embarqué)."""
        os.system("sudo /sbin/halt")

    # ------------------------------------------------------------------
    def __init__(self):
        super().__init__()

        # ── Support écran tactile ──────────────────────────────────────
        self.setAttribute(Qt.WA_AcceptTouchEvents, True)

        # ── Interface Qt Designer ──────────────────────────────────────
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.move(0, 0)

        # ── Fond noir profond sur toute la fenêtre ────────────────────
        _bg = QColor(10, 10, 10)
        pal = self.palette()
        pal.setColor(QPalette.Window, _bg)
        pal.setColor(QPalette.Base,   _bg)
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        self.ui.centralwidget.setAutoFillBackground(True)
        self.ui.centralwidget.setPalette(pal)

        # ── Layout principal ───────────────────────────────────────────
        layout = QGridLayout(self.ui.centralwidget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        # 12 colonnes égales
        for col in range(12):
            layout.setColumnStretch(col, 1)
        # rows 0-3 : cadrans (stretch égal)
        for row in range(4):
            layout.setRowStretch(row, 1)
        # row 4 : BarGauges hauteur fixe
        layout.setRowStretch(4, 0)
        layout.setRowMinimumHeight(4, 58)
        self.ui.centralwidget.setLayout(layout)

        # ── Historique glissant : une deque par canal (taille bornée) ──
        # Ordre : temp, afr, batt, air, fuel, rpm, boost, tps
        self._history = [deque([0, 0], maxlen=HISTORY_MAXLEN)
                         for _ in self._CHANNELS]

        # ── Log CSV de session ─────────────────────────────────────────
        self._log_file = None
        self._open_log()

        # ── Cadrans (Dial) ─────────────────────────────────────────────
        # TEMP : plage 0-130°C, rouge > 110°C  → threshold = 110/130 ≈ 0.846
        self.dial_temp  = Dial("TEMP",  "°C",     0,    130,  red_threshold=0.846)
        # AFR  : plage 8-20, rouge < 11 et > 16
        #   red_low  = (11 - 8) / (20 - 8) = 0.25
        #   red_high = (16 - 8) / (20 - 8) = 0.667
        self.dial_afr   = Dial("AFR",   "",        8,    20,
                               red_threshold=0.667, red_low=0.25)
        self.dial_tps   = Dial("TPS",   "%",       0,   100,   red_threshold=1.01)
        self.dial_rpm   = Dial("RPM",   "tr/min",  0,  7500,   red_threshold=0.80)
        self.dial_boost = Dial("BOOST", "bar",    -0.5,  2.0,  red_threshold=0.83)

        # Historique : temp(0) afr(1) batt(2) air(3) fuel(4) rpm(5) boost(6) tps(7)
        self._dials = [self.dial_temp, self.dial_afr,
                       None, None, None,
                       self.dial_rpm, self.dial_boost,
                       self.dial_tps]

        # ── Jauges BarGauge (bande inférieure) ────────────────────────
        self.bar_air  = BarGauge("AIR",  "°C",  -10,  80,  red_threshold=0.83)
        self.bar_fuel = BarGauge("FUEL", "bar",   0,  10,  red_threshold=0.80)
        self.bar_batt = BarGauge("BATT", "V",    10,  16,  red_threshold=0.10)

        # Connexion clics → graphe
        clickable(self.dial_rpm).connect(self._showGraphRpmBoostTps)
        clickable(self.dial_afr).connect(lambda: self._showGraph(1))
        clickable(self.dial_tps).connect(lambda: self._showGraph(7))
        clickable(self.dial_temp).connect(lambda: self._showGraph(0))
        clickable(self.dial_boost).connect(lambda: self._showGraph(6))

        # ── Layout 5 lignes × 12 colonnes ─────────────────────────────
        #
        #   Col 0-3      │  Col 4-7   │  Col 8-11
        #   TPS  (0-1)   │  RPM (0-3) │  BOOST (0-1)
        #   AFR  (2-3)   │  RPM (0-3) │  TEMP  (2-3)
        #   ─────────────────────────────────────────
        #   AIR  (4)     │  FUEL (4)  │  BATT  (4)    ← hauteur fixe
        #
        layout.addWidget(self.dial_rpm,   0, 4,  4, 4)   # centre, pleine hauteur

        layout.addWidget(self.dial_tps,   0, 0,  2, 4)   # gauche haut
        layout.addWidget(self.dial_afr,   2, 0,  2, 4)   # gauche bas

        layout.addWidget(self.dial_boost, 0, 8,  2, 4)   # droite haut
        layout.addWidget(self.dial_temp,  2, 8,  2, 4)   # droite bas

        # BarGauges — même row, même hauteur fixe, 4 colonnes chacune
        layout.addWidget(self.bar_air,  4, 0,  1, 4)
        layout.addWidget(self.bar_fuel, 4, 4,  1, 4)
        layout.addWidget(self.bar_batt, 4, 8,  1, 4)

        print("Démarrage" + (" [MODE SIMULATION]" if SIMULATION_MODE else " [MODE RÉEL]"))
        QTimer.singleShot(50, self.increment)

    # ------------------------------------------------------------------
    # Graphes matplotlib — méthode générique
    # ------------------------------------------------------------------

    def _on_graph_click(self, event):
        """Ferme la fenêtre matplotlib sur clic gauche."""
        if event.button == 1:
            ioff()
            close()

    def _showGraph(self, channel_idx):
        """Affiche le graphe de l'historique pour le canal donné."""
        _, fig_label, x_label, y_label, win_title = self._CHANNELS[channel_idx]
        history = list(self._history[channel_idx])

        t = numpy.arange(0.0, len(history), 1)
        figure(num=fig_label, figsize=(12, 10))
        plot(t, history, color="red", linewidth=1, linestyle="-")
        xlabel(x_label)
        ylabel(y_label)
        title(win_title)
        grid(True)
        connect('button_press_event', self._on_graph_click)
        pyplot.get_current_fig_manager().window.showMaximized()
        show()

    def _showGraphRpmBoostTps(self):
        """Affiche RPM, Boost et TPS superposés sur le même graphe.
        Axes secondaires : RPM sur l'axe gauche, Boost et TPS sur l'axe droit.
        Mise à l'échelle automatique sur chaque axe. Clic gauche pour fermer.
        """
        # _CHANNELS index : RPM=5, BOOST=6, TPS=7
        rpm_hist   = list(self._history[5])
        boost_hist = list(self._history[6])
        tps_hist   = list(self._history[7])
        n = max(len(rpm_hist), len(boost_hist), len(tps_hist))
        t = numpy.arange(0.0, n, 1)

        fig, ax1 = pyplot.subplots(figsize=(12, 10))
        fig.canvas.mpl_connect('button_press_event', self._on_graph_click)

        # RPM — axe gauche (rouge)
        ax1.set_xlabel('time (1/20s)')
        ax1.set_ylabel('RPM (tr/min)', color='red')
        ax1.plot(t[:len(rpm_hist)], rpm_hist,
                 color='red', linewidth=1, linestyle='-', label='RPM')
        ax1.tick_params(axis='y', labelcolor='red')
        ax1.autoscale(enable=True, axis='y', tight=False)
        ax1.margins(y=0.05)  # 5 % de marge en haut et en bas

        # Boost et TPS — axe droit
        ax2 = ax1.twinx()
        ax2.set_ylabel('Boost (bar) / TPS (%)', color='steelblue')
        ax2.plot(t[:len(boost_hist)], boost_hist,
                 color='steelblue', linewidth=1, linestyle='-', label='Boost')
        ax2.plot(t[:len(tps_hist)], tps_hist,
                 color='orange', linewidth=1, linestyle='--', label='TPS %')
        ax2.tick_params(axis='y', labelcolor='steelblue')
        ax2.autoscale(enable=True, axis='y', tight=False)
        ax2.margins(y=0.05)  # 5 % de marge en haut et en bas

        # Mise à l'échelle automatique de l'axe X (temps)
        ax1.autoscale(enable=True, axis='x', tight=True)

        # Légende commune
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

        pyplot.title('RPM / Boost / TPS')
        pyplot.grid(True)
        pyplot.get_current_fig_manager().window.showMaximized()
        pyplot.show()

    # ------------------------------------------------------------------
    # Sauvegarde des données
    # ------------------------------------------------------------------

    def saveAll(self):
        """Sauvegarde tous les historiques dans leurs fichiers respectifs."""
        print("Sauvegarde des données...")
        filenames = ["temp.txt", "afr.txt", "batt.txt", "air.txt", "fuel.txt",
                     "rpm.txt",  "boost.txt", "tps.txt", "km.txt"]
        for history, filename in zip(self._history, filenames):
            with open(filename, 'w') as f:
                f.writelines(str(v) + '\n' for v in history)

    # ------------------------------------------------------------------
    # Événements Qt
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        """Quitte l'application sur pression de la touche Échap."""
        if event.key() == Qt.Key_Escape:
            QApplication.quit()

    def closeEvent(self, evt):
        """Sauvegarde la log de session puis accepte la fermeture."""
        self._flush_log()
        evt.accept()

    # ------------------------------------------------------------------
    # Boucle de rafraîchissement (toutes les 50 ms)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Log de session (CSV, écriture en continu)
    # ------------------------------------------------------------------

    def _open_log(self):
        """Ouvre le fichier CSV de session et écrit l'en-tête."""
        self._log_file = open(LOG_FILE_PATH, 'w', buffering=1)  # buffering=1 → flush par ligne
        self._log_file.write(','.join(LOG_CHANNEL_NAMES) + '\n')
        print(f"Log démarrée : {LOG_FILE_PATH}")

    def _flush_log(self):
        """Ferme proprement le fichier de log."""
        if self._log_file and not self._log_file.closed:
            self._log_file.close()
            print(f"Log fermée : {LOG_FILE_PATH}")

    # ------------------------------------------------------------------
    # Boucle de rafraîchissement (toutes les 50 ms)
    # ------------------------------------------------------------------

    def increment(self):
        """Lit un snapshot atomique des valeurs CAN, met à jour les cadrans
        et les jauges, enregistre l'historique, écrit la log CSV.
        """
        snap = can_data.snapshot()  # tuple de 75 valeurs (ordre LOG_CHANNEL_NAMES)

        # Index dans snapshot() :
        #   0=rpm  1=tps  3=map_  22=lambda1  30=fuel  35=volt  49=temp  52=air
        v_temp  = snap[49]
        v_afr   = snap[22]
        v_batt  = snap[35]
        v_air   = snap[52]
        v_fuel  = snap[30]
        v_rpm   = snap[0]
        v_boost = (snap[3] - 1013.0) / 1000.0
        v_tps   = snap[1]

        # Mise à jour cadrans principaux
        self.dial_temp.setSpeed(v_temp)
        self.dial_afr.setSpeed(v_afr)
        self.dial_tps.setSpeed(v_tps)
        self.dial_rpm.setSpeed(v_rpm)
        self.dial_boost.setSpeed(v_boost)

        # Mise à jour jauges BarGauge
        self.bar_air.setValue(v_air)
        self.bar_fuel.setValue(v_fuel)
        self.bar_batt.setValue(v_batt)

        # Historique glissant (ordre _CHANNELS : temp/afr/batt/air/fuel/rpm/boost/tps)
        for i, v in enumerate([v_temp, v_afr, v_batt, v_air,
                                v_fuel, v_rpm, v_boost, v_tps]):
            self._history[i].append(v)

        # Écriture CSV
        self._log_file.write(','.join(f"{v:.2f}" for v in snap) + '\n')

        QTimer.singleShot(50, self.increment)

