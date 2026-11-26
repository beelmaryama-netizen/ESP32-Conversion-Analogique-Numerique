"""Pilote SSD1306 I2C minimal pour MicroPython / ESP32.

Version fonctionnelle de remplacement, creee pour cette sauvegarde.
Elle expose SSD1306_I2C(128, 64, i2c), fill(), text(), show().
Pour retrouver votre pilote original, exporter ssd1306.py depuis Thonny.
"""
import framebuf


class SSD1306_I2C(framebuf.FrameBuffer):
    def __init__(self, width, height, i2c, addr=0x3C):
        self.width = width
        self.height = height
        self.i2c = i2c
        self.addr = addr
        self.pages = height // 8
        self.buffer = bytearray(width * self.pages)
        super().__init__(self.buffer, width, height, framebuf.MONO_VLSB)
        self._command = bytearray(2)
        self._data_parts = [b"\x40", self.buffer]
        self._initialize()

    def _write_command(self, value):
        self._command[0] = 0x80
        self._command[1] = value
        self.i2c.writeto(self.addr, self._command)

    def _initialize(self):
        commands = (
            0xAE,              # Affichage desactive
            0x20, 0x00,        # Adressage horizontal
            0x40,              # Premiere ligne
            0xA1,              # Ordre des colonnes
            0xA8, self.height - 1,
            0xC8,              # Sens des lignes
            0xD3, 0x00,        # Decalage vertical
            0xDA, 0x12 if self.height == 64 else 0x02,
            0xD5, 0x80,        # Horloge
            0xD9, 0xF1,        # Precharge
            0xDB, 0x30,        # VCOMH
            0x81, 0xFF,        # Contraste
            0xA4,              # Utiliser la RAM
            0xA6,              # Polarite normale
            0x8D, 0x14,        # Pompe de charge
            0xAF,              # Affichage active
        )
        for command in commands:
            self._write_command(command)
        self.fill(0)
        self.show()

    def show(self):
        for command in (
            0x21, 0, self.width - 1,
            0x22, 0, self.pages - 1,
        ):
            self._write_command(command)
        self.i2c.writevto(self.addr, self._data_parts)

    def poweroff(self):
        self._write_command(0xAE)

    def poweron(self):
        self._write_command(0xAF)

    def contrast(self, value):
        self._write_command(0x81)
        self._write_command(value)
