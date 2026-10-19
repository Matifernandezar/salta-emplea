#!/usr/bin/env python3
"""Ensayo OCR opcional, aislado y sin red con imágenes propias de PRUEBA.

No inicia Flask, no usa credenciales ni toca ninguna base de datos. Requiere
Pillow y un binario Tesseract ya instalado con el idioma solicitado. No instala
ni descarga modelos. Los resultados no certifican calidad en otros dispositivos.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import shutil
import subprocess
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def normalized(text: str) -> str:
    """Ignora caja/espacios; conserva acentos, signos, números y orden."""
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def distance(expected, actual) -> int:
    previous = list(range(len(actual) + 1))
    for i, left in enumerate(expected, 1):
        current = [i]
        for j, right in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def cases(font_path: Path):
    lines = [
        "AVISO DE PRUEBA - NO ES UNA OFERTA REAL",
        "Puesto: atención al público y administración",
        "Empresa: Comercio de PRUEBA",
        "Localidad: Salta Capital",
        "Modalidad: presencial",
        "Jornada: lunes a viernes de 8 a 16 horas",
        "Requisitos: organización y manejo de planillas",
        "Sueldo de PRUEBA: $ 850.000 ARS por mes",
        "Contacto de PRUEBA: pruebas@example.test",
        "Fecha de cierre de PRUEBA: 31/12/2026",
    ]
    image = Image.new("RGB", (1000, 500), "white")
    draw = ImageDraw.Draw(image)
    small = ImageFont.truetype(str(font_path), 17)
    for index, line in enumerate(lines):
        draw.text((35, 35 + index * 36), line, font=small, fill="#142a3b")
    yield "texto-pequeno", image, "\n".join(lines), [
        "atención", "administración", "850.000", "pruebas@example.test", "31/12/2026"]

    image = Image.new("RGB", (1000, 650), "white")
    draw = ImageDraw.Draw(image)
    medium = ImageFont.truetype(str(font_path), 25)
    for index, line in enumerate(lines):
        draw.text((35, 35 + index * 52), line, font=medium, fill="#142a3b")
    yield "desenfoque", image.filter(ImageFilter.GaussianBlur(1.2)), "\n".join(lines), [
        "atención", "administración", "850.000", "pruebas@example.test", "31/12/2026"]

    image = Image.new("RGB", (1100, 750), "#f3f7f7")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(str(font_path), 37)
    body = ImageFont.truetype(str(font_path), 23)
    draw.rectangle((0, 0, 1100, 150), fill="#122c49")
    title = ["AVISO DE PRUEBA", "NO ES UNA OFERTA REAL"]
    draw.text((40, 26), title[0], font=title_font, fill="white")
    draw.text((40, 83), title[1], font=body, fill="white")
    left = ["PUESTO", "Atención al público", "Salta Capital", "Presencial", "Lunes a viernes", "8 a 16 horas"]
    right = ["REQUISITOS", "Organización", "Planillas de cálculo", "SUELDO DE PRUEBA", "$ 850.000 ARS", "por mes"]
    for x, block in ((40, left), (590, right)):
        draw.rounded_rectangle((x - 10, 190, x + 460, 560), radius=20, fill="white", outline="#0b7777", width=3)
        for index, line in enumerate(block):
            draw.text((x + 15, 215 + index * 49), line, font=body, fill="#142a3b")
    footer = ["Empresa: Comercio de PRUEBA", "pruebas@example.test", "Cierre de PRUEBA: 31/12/2026"]
    for index, line in enumerate(footer):
        draw.text((40, 590 + index * 43), line, font=body, fill="#142a3b")
    # Orden de lectura editorial deseado: encabezado, columna izquierda,
    # columna derecha, pie. Un motor puede intercalar columnas incorrectamente.
    truth = "\n".join(title + left + right + footer)
    yield "diseno-columnas", image, truth, [
        "atención", "organización", "850.000", "pruebas@example.test", "31/12/2026"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="Directorio nuevo, fuera del repositorio")
    parser.add_argument("--language", default="eng", help="Modelo instalado; eng NO valida español")
    parser.add_argument("--psm", default=3, type=int, choices=range(14))
    parser.add_argument("--font", type=Path, default=Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    args = parser.parse_args()
    binary = shutil.which("tesseract")
    if not binary or not args.font.is_file():
        parser.error("Falta Tesseract o la fuente. El ensayo no instala ni descarga dependencias.")
    output = args.output.resolve()
    repository = Path(__file__).resolve().parents[1]
    if output == repository or repository in output.parents:
        parser.error("Guardá las imágenes de PRUEBA fuera del repositorio.")
    if output.exists():
        parser.error("El directorio de salida debe ser nuevo; no se sobrescriben resultados.")
    version = subprocess.run([binary, "--version"], check=True, capture_output=True, text=True, timeout=10)
    languages = subprocess.run([binary, "--list-langs"], check=True, capture_output=True, text=True, timeout=10)
    installed = languages.stdout.strip().splitlines()[1:]
    if any(language not in installed for language in args.language.split("+")):
        parser.error(f"Modelo solicitado no instalado. Disponibles: {', '.join(installed)}.")
    output.mkdir(parents=True)
    report = {
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "PRUEBA SINTÉTICA AISLADA; no representa ofertas reales ni valida Vercel/navegador",
        "engine": version.stdout.splitlines()[0], "language": args.language,
        "installed_languages": installed, "psm": args.psm,
        "platform": platform.system(), "architecture": platform.machine(),
        "font_sha256": hashlib.sha256(args.font.read_bytes()).hexdigest(),
        "normalization": "NFC, minúsculas y espacios colapsados; conserva acentos, signos y orden",
        "results": [],
    }
    for name, image, truth, critical in cases(args.font):
        path = output / f"PRUEBA-{name}.png"
        image.save(path)
        (output / f"PRUEBA-{name}.esperado.txt").write_text(truth + "\n", encoding="utf-8")
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.perf_counter()
        result = subprocess.run([binary, str(path), "stdout", "-l", args.language,
                                 "--psm", str(args.psm)], check=True,
                                capture_output=True, text=True, timeout=20)
        elapsed = time.perf_counter() - start
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        actual = result.stdout
        (output / f"PRUEBA-{name}.ocr.txt").write_text(actual, encoding="utf-8")
        expected_text, actual_text = normalized(truth), normalized(actual)
        row = {
            "case": name, "pixels": list(image.size), "png_bytes": path.stat().st_size,
            "seconds": round(elapsed, 3),
            "cpu_seconds_children": round((after.ru_utime + after.ru_stime)
                                           - (before.ru_utime + before.ru_stime), 3),
            "character_error_rate": round(distance(expected_text, actual_text) / len(expected_text), 4),
            "word_error_rate": round(distance(expected_text.split(), actual_text.split()) / len(expected_text.split()), 4),
            "critical_literal_matches": {value: normalized(value) in actual_text for value in critical},
        }
        report["results"].append(row)
    # Linux informa KiB; es el pico observado de TODOS los hijos del proceso,
    # no una medición por caso ni memoria de un navegador o función Vercel.
    report["children_peak_rss_kib_linux"] = (
        resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss if platform.system() == "Linux" else None)
    report["memory_scope"] = "Pico de procesos hijos de todo el ensayo; no suma imágenes/Python ni mide navegador/Vercel"
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    (output / "resultado.json").write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
