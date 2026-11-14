# syntax=docker/dockerfile:1
# Imagen del Digitalizador de boletas (Streamlit + OpenCV + PaddleOCR, solo CPU).
#
#   docker build -t digitalizador-boletas .
#   docker compose up -d
#
# BASE_IMAGE permite usar un espejo del registro (p. ej. si Docker Hub limita descargas).
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RECEIPT_DATA_DIR=/data \
    PADDLE_PDX_CACHE_HOME=/opt/paddlex \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

WORKDIR /app

# Bibliotecas del sistema que necesita OpenCV/PaddlePaddle en una imagen slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Descarga los modelos de PaddleOCR (detector y reconocedor latino, unos 13 MB) durante la
# construcción para que el contenedor funcione sin Internet. Con PRELOAD_MODELS=0 se descargan
# en el primer uso. Los servidores de modelos a veces cortan la conexión: se reintenta.
ARG PRELOAD_MODELS=1
RUN mkdir -p /opt/paddlex \
    && if [ "$PRELOAD_MODELS" = "1" ]; then \
         ok=0; \
         for intento in 1 2 3 4; do \
           if python -c "from paddleocr import PaddleOCR; PaddleOCR(text_detection_model_name='PP-OCRv5_mobile_det', text_recognition_model_name='latin_PP-OCRv5_mobile_rec', use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, enable_mkldnn=False)"; then ok=1; break; fi; \
           echo "reintento $intento"; sleep 5; \
         done; \
         [ "$ok" = "1" ]; \
       fi

COPY *.py ./
COPY .streamlit ./.streamlit

# Usuario sin privilegios; /data es el volumen con la base, las imágenes y la cuenta.
# UID 1000: es el que usan Hugging Face Spaces y la mayoría de las plataformas de contenedores.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data \
    && chown -R app:app /data /opt/paddlex
USER app
VOLUME ["/data"]

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)" || exit 1

CMD ["streamlit", "run", "main.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
