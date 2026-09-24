import subprocess
import time
from datetime import datetime

# Génération d'un nom de fichier unique avec timestamp
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
logfile = f"can_log_{timestamp}.txt"

print(f"Fichier de log : {logfile}")

# 1. Activer l'interface CAN
subprocess.run(["sudo", "ip", "link", "set", "can0", "up", "type", "can", "bitrate", "500000"])

# 2. Ouvrir le fichier de log
with open(logfile, "w") as f:
    # 3. Lancer candump
    process = subprocess.Popen(["candump", "-t", "a", "can0"], stdout=f)

    print("Capture CAN en cours pendant 30 minutes...")
    time.sleep(1800)  # 1800 secondes = 30 minutes

    # 4. Arrêter candump
    process.terminate()
    print("Capture terminée.")

