from machine import Pin, ADC, PWM, SoftI2C
import network
import socket
import time
import ssd1306
from config import WIFI_SSID, WIFI_PASSWORD

# ==================================
# 1. CONFIGURATION DES COMPOSANTS
# ==================================

# Potentiometre sur GPIO34
pot = ADC(Pin(34))
pot.atten(ADC.ATTN_11DB)
pot.width(ADC.WIDTH_12BIT)

# Ecran OLED
i2c = SoftI2C(scl=Pin(22), sda=Pin(21))
oled = ssd1306.SSD1306_I2C(128, 64, i2c)

# DEL sur GPIO25
led = PWM(Pin(25), freq=1000)
led.duty(0)
tension_led = 0.0

# Reseau Wi-Fi
wifi = network.WLAN(network.STA_IF)
serveur = None
dernier_essai_wifi = None
dernier_essai_serveur = None

valeurs_valides = [
    "0", "0.5", "1", "1.5",
    "2", "2.5", "3.3"
]


# ==================================
# 2. LECTURE DU POTENTIOMETRE
# ==================================

def lire_potentiometre():
    brut = pot.read()
    tension = brut * 3.3 / 4095
    return brut, tension


# ==================================
# 3. AFFICHAGE OLED
# ==================================

def afficher_oled(brut, tension, ip):
    oled.fill(0)

    oled.text("ADC: " + str(brut), 0, 0)
    oled.text("POT: %.2f V" % tension, 0, 12)
    oled.text("DEL: %.1f V" % tension_led, 0, 24)
    oled.text("IP:", 0, 36)
    oled.text(ip[:16], 0, 48)

    oled.show()


# ==================================
# 4. CONTROLE PWM DE LA DEL
# ==================================

def regler_del(tension):
    global tension_led

    duty = round(tension * 1023 / 3.3)
    led.duty(duty)
    tension_led = tension

    print("DEL:", tension_led, "V")
    print("PWM:", duty)


# ==================================
# 5. CONNEXION WIFI
# ==================================

def connecter_wifi():
    if wifi.isconnected():
        return

    try:
        wifi.active(False)
        time.sleep_ms(300)
        wifi.active(True)
        time.sleep_ms(300)

        # Initialisation du Wi-Fi
        wifi.scan()
        wifi.connect(WIFI_SSID, WIFI_PASSWORD)

        print("Connexion Wi-Fi en cours...")

    except OSError as erreur:
        print("Erreur Wi-Fi:", erreur)


# ==================================
# 6. PAGE WEB HTML
# ==================================

def page_web():
    boutons = ""

    for v in valeurs_valides:
        classe = "actif" if float(v) == tension_led else ""

        boutons += (
            '<a class="bouton %s" href="/set?v=%s">%s V</a>'
            % (classe, v, v)
        )

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
        <title>ESP32 Controle DEL</title>
        <style>
            body {
                background: #111827;
                color: white;
                font-family: Arial;
                text-align: center;
                padding: 30px;
            }
            h1 {
                color: #93c5fd;
            }
            .valeur {
                font-size: 32px;
                margin: 25px;
            }
            .bouton {
                display: inline-block;
                padding: 18px;
                margin: 8px;
                background: #2563eb;
                color: white;
                text-decoration: none;
                border-radius: 10px;
                font-size: 19px;
            }
            .actif {
                background: #16a34a;
            }
        </style>
    </head>
    <body>
        <h1>Controle DEL ESP32</h1>
        <p>Tension actuelle :</p>
        <div class="valeur">%.1f V</div>
        %s
    </body>
    </html>
    """ % (tension_led, boutons)

    return html


# ==================================
# 7. SERVEUR WEB
# ==================================

def demarrer_serveur():
    s = socket.socket()

    try:
        s.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1
        )

        s.bind(("0.0.0.0", 80))
        s.listen(2)
        s.settimeout(0.05)

        print("Serveur web demarre!")
        print("IP:", wifi.ifconfig()[0])

        return s

    except OSError as erreur:
        print("Erreur serveur:", erreur)
        s.close()
        return None


def traiter_client(client):
    try:
        client.settimeout(0.5)
        requete = client.recv(1024).decode()
        chemin = requete.split(" ")[1]

        statut = "200 OK"
        contenu = ""

        if chemin.startswith("/set?v="):
            valeur = chemin[7:]

            if valeur in valeurs_valides:
                regler_del(float(valeur))
                contenu = page_web()
            else:
                statut = "400 Bad Request"
                contenu = "Tension invalide"

        elif chemin == "/":
            contenu = page_web()

        else:
            statut = "404 Not Found"
            contenu = "Page introuvable"

        corps = contenu.encode("utf-8")

        entete = (
            "HTTP/1.1 " + statut + "\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "Content-Length: %d\r\n"
            "Connection: close\r\n\r\n"
        ) % len(corps)

        client.sendall(entete.encode())
        client.sendall(corps)

    except Exception as erreur:
        print("Erreur requete:", erreur)

    finally:
        client.close()


# ==================================
# 8. BOUCLE PRINCIPALE
# ==================================

print("Demarrage du projet ESP32")

dernier_oled = None
wifi_etait_connecte = False

while True:
    maintenant = time.ticks_ms()

    # Lecture ADC et OLED toutes les 200 ms
    if (dernier_oled is None or
        time.ticks_diff(maintenant, dernier_oled) >= 200):

        brut, tension = lire_potentiometre()

        if wifi.isconnected():
            ip = wifi.ifconfig()[0]
        else:
            ip = "DECONNECTE"

        afficher_oled(brut, tension, ip)
        dernier_oled = maintenant

    # Surveillance du Wi-Fi
    if not wifi.isconnected():

        if serveur is not None:
            serveur.close()
            serveur = None
            print("Serveur arrete: Wi-Fi perdu")

        if (dernier_essai_wifi is None or
            time.ticks_diff(
                maintenant, dernier_essai_wifi
            ) >= 20000):

            dernier_essai_wifi = maintenant
            connecter_wifi()

        wifi_etait_connecte = False

    else:
        if not wifi_etait_connecte:
            print("Wi-Fi connecte!")
            print("IP:", wifi.ifconfig()[0])
            wifi_etait_connecte = True

        # Demarrer le serveur si necessaire
        if (serveur is None and
            (dernier_essai_serveur is None or
             time.ticks_diff(
                 maintenant, dernier_essai_serveur
             ) >= 5000)):

            dernier_essai_serveur = maintenant
            serveur = demarrer_serveur()

        # Attente courte: ne bloque pas l'OLED
        if serveur is not None:
            try:
                client, adresse = serveur.accept()
            except OSError:
                client = None

            if client is not None:
                traiter_client(client)

    time.sleep_ms(10)
