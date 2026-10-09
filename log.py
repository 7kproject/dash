import os
import subprocess
import time
import logging
from datetime import datetime

# Utilisation de chemins absolus pour éviter les problèmes lors de l'exécution par un service
BASE_DIR = "/home/pi/dash"
LOG_DIR = os.path.join(BASE_DIR, "log")
TRACE_FILE = os.path.join(BASE_DIR, "trace.log")
DURATION_SECONDS = 1800  # 30 minutes = 1800 secondes
BITRATE = 500000

# Configuration du journal de suivi (trace.log + console)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(TRACE_FILE, mode="a", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logging.info("=== Démarrage de log.py ===")

# 1. S'assurer que le dossier log existe
os.makedirs(LOG_DIR, exist_ok=True)
logging.info(f"Dossier de log vérifié : {LOG_DIR}")

# 2. Génération du nom de fichier unique avec horodatage
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
logfile_path = os.path.join(LOG_DIR, f"can_log_{timestamp}.txt")
logging.info(f"Fichier de capture CAN : {logfile_path}")

process = None

try:
    # 3. Ouvrir le fichier de log et lancer candump
    logging.info("Ouverture du fichier texte et lancement de candump sur can0...")
    with open(logfile_path, "w") as f:
        process = subprocess.Popen(["candump", "-t", "a", "can0"], stdout=f)
        logging.info(f"Processus candump démarré avec succès (PID: {process.pid})")

        logging.info(f"Capture CAN en cours pour {DURATION_SECONDS // 60} minutes...")
        time.sleep(DURATION_SECONDS)

except KeyboardInterrupt:
    logging.warning("Capture interrompue manuellement par l'utilisateur (Ctrl+C).")
except Exception as e:
    logging.error(f"Erreur inattendue pendant l'exécution : {e}")

finally:
    # 4. Arrêt propre du processus candump
    if process and process.poll() is None:
        logging.info("Arrêt de candump (SIGTERM)...")
        process.terminate()
        try:
            process.wait(timeout=5)
            logging.info("Processus candump terminé proprement.")
        except subprocess.TimeoutExpired:
            logging.warning("candump ne s'est pas arrêté à temps, arrêt forcé (SIGKILL)...")
            process.kill()
            
    logging.info(f"Fin du script. Fichier de capture généré : {logfile_path}")

