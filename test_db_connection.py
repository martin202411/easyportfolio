# /opt/easyportfolio_django_app/test_db_connection.py
import os
import MySQLdb # Django nutzt diese Bibliothek (oder einen kompatiblen Wrapper)
from dotenv import load_dotenv

# BASE_DIR ist das Verzeichnis, in dem dieses Skript liegt
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOTENV_PATH = os.path.join(BASE_DIR, '.env')

if os.path.exists(DOTENV_PATH):
    print(f"INFO: Lade .env Datei von: {DOTENV_PATH}")
    load_dotenv(dotenv_path=DOTENV_PATH)
else:
    print(f"FATAL: .env Datei nicht gefunden unter {DOTENV_PATH}")
    exit()

db_host = os.getenv('DB_HOST')
db_user = os.getenv('DB_USER')
db_password = os.getenv('DB_PASSWORD')
db_name = os.getenv('DB_NAME')
db_port_str = os.getenv('DB_PORT', '3306') # Standardmäßig 3306, falls nicht in .env



print(f"\nINFO: Versuche Verbindung mit folgenden Daten herzustellen:")
print(f"  Host: {db_host}")
print(f"  User: {db_user}")

# --- START DEBUGGING: RAW-PASSWORT UND LÄNGE ANZEIGEN ---
if db_password:
    # Wichtig: Das Passwort wird hier im Klartext ausgegeben. Nur für Debugging verwenden!
    print(f"  DEBUG_RAW_PASSWORD: >>>{db_password}<<<") # In Anführungszeichen, um Leerzeichen zu sehen
    print(f"  DEBUG_PASSWORD_LENGTH: {len(db_password)}")
else:
    print(f"  DEBUG_RAW_PASSWORD: None (nicht gesetzt)")
    print(f"  DEBUG_PASSWORD_LENGTH: 0")
# --- ENDE DEBUGGING ---

print(f"  Database: {db_name}")
print(f"  Port: {db_port_str}")





# Validierung der geladenen Werte (optional, aber gut für Debugging)
if not all([db_host, db_user, db_password, db_name, db_port_str]):
    print("FATAL: Nicht alle notwendigen DB-Variablen wurden aus .env geladen.")
    print(f"  Host: {db_host}")
    print(f"  User: {db_user}")
    print(f"  Password: {' vorhanden' if db_password else 'FEHLT!'}")
    print(f"  Database: {db_name}")
    print(f"  Port: {db_port_str}")
    exit()

print(f"\nINFO: Versuche Verbindung mit folgenden Daten herzustellen:")
print(f"  Host: {db_host}")
print(f"  User: {db_user}")
# Aus Sicherheitsgründen das Passwort nicht direkt ausgeben, nur dessen Länge oder ob es existiert
print(f"  Password: {'*' * len(db_password) if db_password else 'None'}")
print(f"  Database: {db_name}")
print(f"  Port: {db_port_str}")

try:
    # MySQLdb.connect erwartet, dass der Port ein Integer ist, falls angegeben
    conn_params = {
        'host': db_host,
        'user': db_user,
        'passwd': db_password,
        'db': db_name
    }
    if db_port_str:
        conn_params['port'] = int(db_port_str)

    db_connection = MySQLdb.connect(**conn_params)
    
    print("\nSUCCESS: Erfolgreich mit MariaDB verbunden!")
    
    cursor = db_connection.cursor()
    cursor.execute("SELECT VERSION()")
    version = cursor.fetchone()
    print(f"Datenbank Version: {version[0]}")
    
    cursor.close()
    db_connection.close()
    print("INFO: Verbindung wieder geschlossen.")

except MySQLdb.OperationalError as e: # Speziell für Verbindungsfehler etc.
    print(f"\nERROR: Verbindung zu MariaDB fehlgeschlagen (OperationalError).")
    print(f"Fehlercode: {e.args[0]}")    # e.args[0] ist der Fehlercode (z.B. 1045)
    print(f"Fehlermeldung: {e.args[1]}") # e.args[1] ist die Fehlermeldung
except ValueError as e_val: # Falls Port-Konvertierung fehlschlägt
    print(f"\nERROR: Ungültiger Wert für DB_PORT: '{db_port_str}'. Muss eine Zahl sein.")
    print(f"Detail: {e_val}")
except Exception as e_gen: # Für alle anderen unerwarteten Fehler
    print(f"\nERROR: Ein unerwarteter Fehler ist aufgetreten: {e_gen}")
    print(f"Typ des Fehlers: {type(e_gen)}")