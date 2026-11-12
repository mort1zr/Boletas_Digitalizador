# syntax=docker/dockerfile:1
# Imagen del Digitalizador de boletas (Streamlit + OpenCV + EasyOCR, solo CPU).
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
    EASYOCR_MODULE_PATH=/opt/easyocr

WORKDIR /app

# PyTorch solo-CPU: la app usa gpu=False y la variante CPU pesa varios GB menos
# que la predeterminada con CUDA. Se instala antes que EasyOCR para que este la reutilice.
# TORCH_INDEX_URL permite usar un espejo si download.pytorch.org no es accesible.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --index-url "${TORCH_INDEX_URL}" torch torchvision

COPY requirements.txt .
RUN pip install -r requirements.txt

# Descarga los modelos de EasyOCR (es/en) durante la construcción para que el
# contenedor funcione sin Internet. Con PRELOAD_MODELS=0 se descargan en el primer uso.
ARG PRELOAD_MODELS=1
RUN mkdir -p /opt/easyocr \
    && if [ "$PRELOAD_MODELS" = "1" ]; then \
         python -c "import easyocr; easyocr.Reader(['es', 'en'], gpu=False, verbose=False)"; \
       fi

COPY *.py ./
COPY .streamlit ./.streamlit

# Usuario sin privilegios; /data es el volumen con la base, las imágenes y la cuenta.
# UID 1000: es el que usan Hugging Face Spaces y la mayoría de las plataformas de contenedores.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data \
    && chown -R app:app /data /opt/easyocr
USER app
VOLUME ["/data"]

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)" || exit 1

CMD ["streamlit", "run", "main.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
