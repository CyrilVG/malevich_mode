#!/usr/bin/env python3
"""Run the one-shot Malevich X/XL AutoDetect v0.6 serial protocol."""
import os
import re
import select
import sys
import termios
import time
import tty


class DetectionError(RuntimeError):
    pass


def parse_model(report):
    match = re.search(r"BOARD: DESIGNER (X|XL) / .* \(CONFIRMED\)", report)
    if match:
        return match.group(1)
    if "BOARD: UNKNOWN" in report:
        return None
    raise DetectionError("AutoDetect не прислал итоговую строку BOARD")


def scan_printer(serial_path, confirm_voltage=input, timeout=40):
    """Scan once after AutoDetect is flashed; never retries active bus probing."""
    fd = os.open(serial_path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    saved = termios.tcgetattr(fd)
    output = bytearray()

    def take(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], min(0.25, deadline - time.monotonic()))
            if not ready:
                continue
            try:
                data = os.read(fd, 4096)
            except BlockingIOError:
                continue
            if data:
                output.extend(data)
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()

    def wait_for(marker, seconds):
        deadline = time.monotonic() + seconds
        while marker.encode() not in output and time.monotonic() < deadline:
            take(min(0.25, deadline - time.monotonic()))
        if marker.encode() not in output:
            raise DetectionError("Тайм-аут AutoDetect, не найдено: " + marker)

    def send(command):
        os.write(fd, command.encode("ascii"))

    try:
        tty.setraw(fd)
        settings = termios.tcgetattr(fd)
        settings[4] = settings[5] = termios.B115200
        settings[2] = (settings[2] & ~termios.CSIZE) | termios.CS8 | termios.CLOCAL | termios.CREAD
        settings[2] &= ~(termios.PARENB | termios.CSTOPB)
        termios.tcsetattr(fd, termios.TCSANOW, settings)

        # Read the startup banner and cached passive report before issuing commands.
        take(1.0)
        if b"Malevich STM32F407 X/XL AutoDetect v0.6.0" not in output:
            send("R")
            take(0.5)
        if b"Malevich STM32F407 X/XL AutoDetect v0.6.0" not in output:
            raise DetectionError("На serial-порту не обнаружен AutoDetect v0.6.0")

        # The operator must inspect the rail while it is enabled. Firmware cuts it
        # automatically after 45 seconds and also releases it after a completed scan.
        output.clear()
        send("E")
        wait_for("[POWER] PE14 HIGH", 3)
        voltage_ok = confirm_voltage("Измерьте PE14: около 3,3 В, без нагрева/аномального тока. Подтвердите [y/N]: ")
        if str(voltage_ok).strip().lower() not in ("y", "yes", "д", "да"):
            send("X")
            raise DetectionError("Проверка питания PE14 не подтверждена; сканирование отменено")
        output.clear()
        send("P")
        wait_for("PASSIVE runs=", 3)
        take(0.15)
        passive = output.decode("ascii", errors="replace")
        expected_passive = "PB10=1 B1 PC3=1 PB10=1 B0 PC3=0 PB10=1"
        if expected_passive not in passive:
            raise DetectionError("Пассивная проверка линий не прошла; активное сканирование отменено")
        output.clear()
        send("A")
        wait_for("ARMED. Y runs ONE X/XL autodetection", 3)
        output.clear()
        send("Y")
        wait_for("No additional active scans without power-cycle", timeout)
        report = output.decode("ascii", errors="replace")
        model = parse_model(report)
        if model is None:
            raise DetectionError("AutoDetect вернул UNKNOWN; прошивка принтера не будет выбрана")
        return model
    finally:
        # Best effort only; the firmware also enforces a 45 s PE14 timeout.
        try:
            send("X")
        except (OSError, UnboundLocalError):
            pass
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        os.close(fd)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 autodetect.py /dev/serial/by-id/<FT232R>")
    try:
        print("Результат: Designer", scan_printer(sys.argv[1]))
    except DetectionError as exc:
        raise SystemExit("Ошибка AutoDetect: " + str(exc))
