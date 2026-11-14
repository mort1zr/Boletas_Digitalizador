# Despliegue

## ¿Por qué no Vercel?

Vercel ejecuta funciones serverless de corta duración con un límite de 250 MB. Streamlit necesita un
servidor que permanezca encendido (usa WebSockets) y la aplicación incluye PaddlePaddle y PaddleOCR, que
pesan cientos de MB. Por eso se despliega como **contenedor Docker**, que es la imagen que ya construye
la integración continua del repositorio.

## Opción recomendada: Hugging Face Spaces (Docker, gratis)

El plan gratuito ofrece 2 vCPU y 16 GB de RAM, suficiente para PaddleOCR en CPU (unos 10 s por boleta, con variación según el largo del ticket).

1. Crea el Space en <https://huggingface.co/new-space>: **SDK = Docker**, visibilidad **Privada**.
2. En *Settings → Variables and secrets* agrega estos **secretos**:

   | Secreto | Contenido |
   |---|---|
   | `APP_USER` | Usuario de acceso (mínimo 3 caracteres). |
   | `APP_PASSWORD` | Contraseña (mínimo 10 caracteres). Se guarda solo su hash PBKDF2. |
   | `RECEIPT_ENCRYPTION_KEY` | Clave de cifrado. Genérala con `python -c "import crypto_service; print(crypto_service.generate_key())"`. Guárdala también fuera del Space: **si se pierde, los datos cifrados no se recuperan**. |
   | `ANTHROPIC_API_KEY` | *Opcional.* Activa la interpretación de preguntas con Claude; sin ella se usan reglas locales. |
   | `NL_QUERY_MODEL` | *Opcional.* Modelo de Claude para las preguntas (por defecto `claude-opus-5-5`; un modelo más pequeño cuesta menos). |

3. Publica el código (crea un token en <https://huggingface.co/settings/tokens> con permiso de escritura):

   ```bash
   HF_TOKEN=hf_xxx ./deploy/huggingface/publicar.sh TU_USUARIO/digitalizador-boletas
   ```

   El script copia **solo** el código necesario; no sube datos, pruebas ni las boletas de `experimentos/`.
4. La primera construcción tarda varios minutos (descarga PaddlePaddle y los modelos de PaddleOCR). Luego abre la
   URL del Space e inicia sesión con `APP_USER` / `APP_PASSWORD`.

## Qué tener en cuenta

- **El almacenamiento gratuito es temporal.** Los registros y las imágenes se pierden cuando el Space se
  reinicia o se reconstruye. Sirve para una **demostración**; para conservar datos hace falta el
  almacenamiento persistente de pago (se monta en `/data`, que es la carpeta que ya usa la aplicación).
- **Mantén el Space privado.** Las boletas contienen datos personales. Aunque se cifran y se enmascara el
  DNI, la autenticación de la aplicación es de demostración y no sustituye un sistema de identidad.
- **La cámara requiere HTTPS.** Los Spaces se sirven por HTTPS, así que `📷 Usar cámara` funciona desde el celular.
- **Rendimiento:** sin GPU, cada boleta tarda unos 10 s; con las instancias de pago con GPU baja a segundos.

## Otras plataformas

Cualquier servicio que ejecute contenedores sirve (Render, Railway, Fly.io, Cloud Run): usa el `Dockerfile`
de la raíz, expón el puerto 8501 y define los mismos secretos. Verifica que ofrezca al menos 2 GB de RAM.

## Probar la imagen en tu equipo

```bash
docker build -t digitalizador-boletas .
docker run --rm -p 8501:8501 -e APP_USER=operador -e APP_PASSWORD='Clave-Segura-2026' digitalizador-boletas
```
