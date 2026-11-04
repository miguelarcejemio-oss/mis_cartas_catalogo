# Compatibilidad de actualización con la APK 1.25

La APK intenta catalog-index.json antes que su índice local y catalogo.json. El servidor no emitía catalog-index.json, así que la copia incluida en la APK ocultaba el catálogo completo actualizado.

build_site.py publica ahora ese endpoint. Conserva las 1205 referencias del índice de la APK 1.25 y sustituye únicamente la edición Mundial Adrenalyn 2026 por las cartas actuales de catalogo.json, incluidas en la respuesta. Se omite la referencia al fragmento antiguo de 728 cartas, evitando que su caché sustituya las 776 actuales. Los demás fragmentos y colecciones mantienen sus referencias originales. Las futuras publicaciones regeneran este endpoint con el Mundial del catálogo actual.

Pruebas: 76 pruebas Python aprobadas, construcción correcta y ejecución real del runtime JS sin modificar de la APK 1.25: recibe 776 cartas, incorpora U01–U48 y conserva dos marcas guardadas exactamente iguales, con una sola petición al índice. No requiere desinstalar ni borrar datos.
