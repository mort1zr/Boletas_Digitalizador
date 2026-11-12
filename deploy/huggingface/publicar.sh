#!/usr/bin/env bash
# Publica la aplicación en un Space de Hugging Face (SDK Docker).
# Copia SOLO el código necesario: no sube datos, pruebas ni las boletas de experimentos.
#
# Uso:  HF_TOKEN=hf_xxx ./deploy/huggingface/publicar.sh USUARIO/NOMBRE-DEL-SPACE
set -euo pipefail

SPACE="${1:?Indica el Space: USUARIO/NOMBRE (créalo antes en https://huggingface.co/new-space, SDK Docker, PRIVADO)}"
: "${HF_TOKEN:?Define HF_TOKEN con un token de acceso con permiso de escritura}"
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

git clone "https://user:${HF_TOKEN}@huggingface.co/spaces/${SPACE}" "$TMP/space"
cd "$TMP/space"
git rm -rq --ignore-unmatch . >/dev/null 2>&1 || true
cp "$RAIZ"/*.py "$RAIZ/requirements.txt" "$RAIZ/Dockerfile" "$RAIZ/.dockerignore" .
mkdir -p .streamlit && cp "$RAIZ/.streamlit/config.toml" .streamlit/
cp "$RAIZ/deploy/huggingface/README.md" README.md
git add -A
git -c user.name="${GIT_AUTHOR_NAME:-deploy}" -c user.email="${GIT_AUTHOR_EMAIL:-deploy@users.noreply.hf.co}" \
    commit -qm "Despliegue de la aplicación" || { echo "Sin cambios que publicar."; exit 0; }
git push -q origin HEAD:main
echo "Publicado. Hugging Face construirá la imagen (la primera vez tarda varios minutos): https://huggingface.co/spaces/${SPACE}"
