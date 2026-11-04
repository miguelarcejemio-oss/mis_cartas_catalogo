# Importador corregido

Desde la raíz del repositorio:

```bash
python3 -m unittest discover -s tests -p test_importar_mundial_2026.py -v
python3 scripts/importar_mundial_2026.py --origen rescate/2026-11-04/importaciones/mundial_2026.txt
```

Genera importaciones/mundial_2026_limpio.json y un informe independiente. No escribe catalogo.json ni estados personales. Resultado del listado recuperado: 995 registros, 65 secciones, 267 registros sin número impreso, todos los números 1–648 presentes; sin filas idénticas repetidas ni conflictos sección/número. Las cifras no certifican que nombres y variantes sean correctos. Debe revisarse antes de integrar el catálogo. Se preservan los nombres del original y las variantes sin número se identifican como tales, sin asignar números inventados.
