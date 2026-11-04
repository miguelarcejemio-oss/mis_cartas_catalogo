import re
import json
from pathlib import Path
from collections import Counter

origen = Path("importaciones/mundial_2026.txt")
destino = Path("importaciones/mundial_2026_limpio.json")

texto = origen.read_text(encoding="utf-8-sig")
cartas = []
seccion = ""
vistos = set()
duplicados = []

patron = re.compile(r"^(?:\d+\s*[·.]\s*)?(\d+|FTS\d+)\s*\.\s*-\s*(.+)$", re.I)

for linea in texto.splitlines():
    linea = linea.strip()

    if not linea:
        continue

        resultado = patron.match(linea)

        if resultado:
            numero, nombre = resultado.groups()
            numero = numero.upper()

            nombre = re.sub(r"\s+\d+$", "", nombre).strip()

            if not seccion:
                continue

                clave = (seccion, numero)

                if clave in vistos:
                    duplicados.append(
                        clave)
                    continue

                    vistos.add(clave)

                    cartas.append({
                        "numero": numero,
                        "nombre": nombre,
                        "seccion": seccion
                    })

    elif (
                        not linea.startswith(("·", "•"))
                        and not re.match(r"^\d+\s*[·•]", linea)
                        and linea == linea.upper()
                        and len(linea) < 90
                        and not linea.startswith(("BUG", "FALTAS", "SECCIONES"))
                    ):
                        seccion = linea

                        destino.write_text(
                            json.dumps(cartas, ensure_ascii=False, indent=2),
                            encoding="utf-8"
                        )

                        numeros = {
                            int(c["numero"])
                            for c in cartas
                            if c["numero"].isdigit()
                        }

                        faltantes = sorted(set(range(1, 649)) - numeros)

                        print(
                            "Cartas numeradas:", len(numeros))
                        print(
                            "Cartas totales detectadas:", len(cartas))
                        print("Secciones detectadas:", len(
                            set(c["seccion"] for c in cartas)))
                        print(
                            "Duplicados:", len(duplicados))
                        print(
                            "Números ausentes del 1 al 648:", faltantes)
                        print(
                            "Archivo generado:", destino)
                        print(
                            "Pendiente: revisar las ediciones especiales sin número.")
