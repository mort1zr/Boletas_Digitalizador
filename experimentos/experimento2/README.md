# Experimento 2: tiempo de registro manual frente al prototipo

**Estado: no ejecutado.** Este experimento requiere medir a personas reales; el informe final no
afirma ninguna reducción de tiempo. Aquí está todo lo necesario para ejecutarlo.

## Protocolo

1. Al menos 5 participantes.
2. Cada participante registra 5 boletas de forma manual (hoja de cálculo) y otras 5 con el prototipo.
3. Alternar entre participantes el método que se usa primero (controla el aprendizaje).
4. Medir con cronómetro el tiempo desde que se toma la boleta hasta que el registro queda
   guardado; en el prototipo se incluye la revisión y la corrección de los campos.
5. Contar los campos erróneos en los datos finales de cada método.

## Cómo usarlo

1. Copia `plantilla_tiempos.csv` y agrega una fila por boleta y participante (`metodo` = `manual`
   o `prototipo`).
2. Completa `tiempo_segundos` y `errores_en_datos_finales` con las mediciones reales.
3. Ejecuta `python experimentos/experimento2/analizar_experimento2.py tu_archivo.csv`.
