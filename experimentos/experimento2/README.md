# Experimento 2: tiempo de registro manual frente al prototipo

Participaron 2 personas. Cada una registró 10 boletas: 5 de forma manual (hoja de cálculo con fecha, comercio y total) y 5 con el
prototipo (Formato A). El primer participante empezó con el método manual y el segundo con el prototipo.

## Protocolo

1. Cada participante registra 5 boletas de forma manual y otras 5 con el prototipo.
2. Se alterna entre participantes el método que se usa primero (controla el aprendizaje).
3. El tiempo se mide con cronómetro desde que se toma la boleta hasta que el registro queda guardado; en el prototipo incluye buscar y
   subir la foto, esperar el procesamiento, revisar y corregir.
4. Se cuentan los campos erróneos (de fecha, comercio y total) en los datos finales de cada método, comparados con `referencia.csv`.

## Archivos

- `datos_experimento2.csv`: mediciones (una fila por boleta y participante).
- `Experimento2_registro_tiempos.xlsx`: libro de registro con el resumen calculado.
- `analizar_experimento2.py`: calcula tiempo medio por método, reducción de tiempo y errores
  (`python experimentos/experimento2/analizar_experimento2.py experimentos/experimento2/datos_experimento2.csv`).
- `graficar_experimento2.py`: genera `experimentos/diagramas/exp2_tiempos.png`.

## Resultado

Tiempo medio por boleta: 39,2 s manual y 20,1 s con el prototipo (48,8 % menos). Campos erróneos en los datos finales: 0 de 30
con el registro manual y 2 de 30 con el prototipo (R30: total 78 en lugar de 79; R12: texto de un sticker registrado como comercio).
