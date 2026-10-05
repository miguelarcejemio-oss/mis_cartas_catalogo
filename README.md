# Servidor de catálogo — Mis Cartas

Este paquete está preparado para publicarse como sitio estático en GitHub Pages. GitHub Pages publica archivos estáticos del repositorio y puede desplegarlos automáticamente con GitHub Actions.

## Estructura
- `catalogo.json`: catálogo actual (117 colecciones).
- `portadas/manifest.json`: relación colección → portada y URL de origen.
- `portadas/`: carpeta destinada a las copias locales de las portadas.
- `scripts/validate_catalog.py`: valida IDs y cantidades antes de publicar.
- `scripts/descargar_portadas.py`: descarga las portadas cuando se ejecuta en un entorno con Internet.
- `.github/workflows/deploy.yml`: valida y publica cada cambio en `main`.
- `.nojekyll`: evita el procesamiento Jekyll innecesario para archivos estáticos.
- `servidor.config.json`: parámetros para conectar la app con este servidor.

## URL que usará la app
Después de crear el repositorio, la URL será: `https://TU_USUARIO.github.io/mis-cartas-catalogo/catalogo.json`.
Sustituir `CATALOG_BASE_URL` en `servidor.config.json` por la URL real antes de conectar la app.

## Actualización
1. Modificar `catalogo.json`.
2. Ejecutar `python scripts/validate_catalog.py catalogo.json`.
3. Hacer push a `main`.
4. GitHub Actions valida y publica automáticamente.
5. La app descarga el nuevo catálogo al abrirse/actualizarse.

No se deben guardar datos personales ni progreso de usuario en este repositorio.
