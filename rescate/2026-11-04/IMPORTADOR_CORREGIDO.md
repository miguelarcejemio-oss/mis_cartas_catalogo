# Revisión e integración del Mundial 2026

El listado contiene 995 registros en 64 secciones. Se descarta el texto de interfaz forward_to_inbox, que antes se contaba erróneamente como una sección. Se reconocen 776 cartas con código impreso: 648 números base, 80 FTS y 48 Upgrade (U01–U48). Los 219 registros restantes se conservan en el original para revisión, sin inventar números.

La integración elimina contadores finales de nombres, corrige las secciones México, Ghana, Corea del Sur y Países Bajos y conserva los 728 IDs existentes, además de todos sus campos personales. No modifica las otras 1113 colecciones. No afirma que el checklist sea completo ni modifica retroactivamente estados personales.

Validación: 72 pruebas generales aprobadas y una nueva regresión de códigos Upgrade/texto de interfaz aprobada; catálogo validado y construcción pública completada. La segunda integración del mismo listado no produce cambios. Cambios de identidad, números duplicados o desaparición de una carta existente bloquean la escritura.

Ejecución desde la raíz: python -m scripts.integrar_mundial_2026. El workflow aplica la corrección después del enriquecimiento, antes de validar y publicar.
