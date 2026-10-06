# Mis Cartas catálogo v2
Servidor para catálogo, checklists y portadas.

## Portadas
Sube una imagen a `portadas/` con el ID exacto de la colección, por ejemplo:
`panini-megacracks-2627.jpg`

La app v53 prueba `.webp`, `.jpg` y `.png` como respaldo. Para forzar prioridad absoluta desde `catalogo.json`, añade `cover_local` con la URL publicada de esa imagen.

## Actualizaciones
Cada push a `main` valida `catalogo.json` y, si es válido, despliega GitHub Pages.
