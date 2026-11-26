"""TP ESP32 - Maryem Belouaar.
Broches conservees : ADC34, SDA21, SCL22 et PWM25.
Version asynchrone : les attentes reseau laissent fonctionner l'OLED.
"""
from machine import Pin, ADC, PWM, SoftI2C
import network
import time
import uasyncio as asyncio
import ssd1306
from config import WIFI_SSID, WIFI_PASSWORD

pot = ADC(Pin(34))
pot.atten(ADC.ATTN_11DB)
pot.width(ADC.WIDTH_12BIT)
i2c = SoftI2C(sda=Pin(21), scl=Pin(22), freq=100000)
oled = ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3C)
led = PWM(Pin(25), freq=1000)
led.duty(0)
tension_led = 0.0
wifi = network.WLAN(network.STA_IF)
valeurs_valides = ("0", "0.5", "1", "1.5", "2", "2.5", "3.3")
clients_actifs = 0


def convertir_adc(brut):
    """Conversion nominale demandee au TP, sans etalonnage de l'ADC."""
    return brut * 3.3 / 4095


def lire_potentiometre():
    brut = pot.read()
    return brut, convertir_adc(brut)


def convertir_pwm(tension):
    return round(tension * 1023 / 3.3)


def regler_del(tension):
    global tension_led
    led.duty(convertir_pwm(tension))
    tension_led = tension
    print("DEL:", tension_led, "V; PWM:", convertir_pwm(tension))


def afficher_oled(brut, tension, ip):
    oled.fill(0)
    oled.text("ADC: " + str(brut), 0, 0)
    oled.text("POT: %.2f V" % tension, 0, 12)
    oled.text("DEL: %.1f V" % tension_led, 0, 24)
    oled.text("IP:", 0, 36)
    oled.text(ip[:16], 0, 48)
    oled.show()


async def tache_mesure():
    """Rafraichissement nominal de 200 ms, meme sans Wi-Fi."""
    while True:
        debut = time.ticks_ms()
        brut, tension = lire_potentiometre()
        ip = wifi.ifconfig()[0] if wifi.isconnected() else "DECONNECTE"
        try:
            afficher_oled(brut, tension, ip)
        except OSError as erreur:
            print("Erreur OLED:", erreur)
        duree = time.ticks_diff(time.ticks_ms(), debut)
        await asyncio.sleep_ms(max(1, 200 - duree))


async def connecter_wifi():
    """Demande une connexion; aucune boucle bloquante d'attente."""
    wifi.active(True)
    try:
        wifi.config(reconnects=0)
    except (OSError, ValueError):
        pass
    dernier_essai = None
    while True:
        maintenant = time.ticks_ms()
        if not wifi.isconnected():
            if (dernier_essai is None or
                    time.ticks_diff(maintenant, dernier_essai) >= 20000):
                dernier_essai = maintenant
                try:
                    wifi.disconnect()
                    wifi.connect(WIFI_SSID, WIFI_PASSWORD)
                    print("Connexion Wi-Fi en cours...")
                except OSError as erreur:
                    print("Erreur Wi-Fi:", erreur)
        else:
            dernier_essai = None
        await asyncio.sleep_ms(500)


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



def traiter_chemin(methode, chemin):
    """Valider avant de modifier la DEL; refuser les autres valeurs."""
    if methode != "GET":
        return "405 Method Not Allowed", "Methode refusee"
    if chemin == "/":
        return "200 OK", page_web()
    if chemin.startswith("/set?"):
        if chemin.startswith("/set?v=") and chemin[7:] in valeurs_valides:
            regler_del(float(chemin[7:]))
            return "200 OK", page_web()
        return "400 Bad Request", "Tension invalide"
    return "404 Not Found", "Page introuvable"


async def lire_entetes(reader):
    """Lecture bornee a 1024 octets, jusqu'a la fin des entetes HTTP."""
    donnees = b""
    while b"\r\n\r\n" not in donnees:
        bloc = await reader.read(min(128, 1024 - len(donnees)))
        if not bloc:
            raise ValueError("Requete incomplete")
        donnees += bloc
        if len(donnees) >= 1024 and b"\r\n\r\n" not in donnees:
            raise ValueError("Requete trop longue")
    return donnees


async def traiter_client(reader, writer):
    """Client lent : delai asynchrone de 2 s, mesure toujours active."""
    global clients_actifs
    if clients_actifs >= 3:
        writer.close()
        try:
            await asyncio.wait_for_ms(writer.wait_closed(), 200)
        except (OSError, asyncio.TimeoutError):
            pass
        return
    clients_actifs += 1
    try:
        try:
            donnees = await asyncio.wait_for_ms(lire_entetes(reader), 2000)
            ligne = donnees.split(b"\r\n", 1)[0].decode("utf-8")
            parties = ligne.split()
            if len(parties) != 3 or parties[2] not in ("HTTP/1.0", "HTTP/1.1"):
                raise ValueError("Ligne HTTP invalide")
            statut, contenu = traiter_chemin(parties[0], parties[1])
        except (ValueError, UnicodeError):
            statut, contenu = "400 Bad Request", "Requete invalide"
        corps = contenu.encode("utf-8")
        entete = ("HTTP/1.1 %s\r\n"
                  "Content-Type: text/html; charset=utf-8\r\n"
                  "Content-Length: %d\r\n"
                  "Connection: close\r\n\r\n") % (statut, len(corps))
        writer.write(entete.encode("utf-8") + corps)
        await asyncio.wait_for_ms(writer.drain(), 2000)
    except (OSError, asyncio.TimeoutError) as erreur:
        print("Client ferme ou trop lent:", erreur)
    finally:
        writer.close()
        try:
            await asyncio.wait_for_ms(writer.wait_closed(), 200)
        except (OSError, asyncio.TimeoutError):
            pass
        clients_actifs -= 1


async def tache_serveur():
    serveur = None
    try:
        while True:
            if wifi.isconnected() and serveur is None:
                try:
                    serveur = await asyncio.start_server(
                        traiter_client, "0.0.0.0", 80, backlog=3)
                    print("Ouvrir http://" + wifi.ifconfig()[0])
                except OSError as erreur:
                    print("Erreur serveur:", erreur)
                    await asyncio.sleep_ms(5000)
            elif not wifi.isconnected() and serveur is not None:
                serveur.close()
                await serveur.wait_closed()
                serveur = None
            await asyncio.sleep_ms(500)
    finally:
        if serveur is not None:
            serveur.close()
            await serveur.wait_closed()


async def main():
    print("Demarrage du TP ESP32")
    await asyncio.gather(tache_mesure(), connecter_wifi(), tache_serveur())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        led.duty(0)
        asyncio.new_event_loop()
