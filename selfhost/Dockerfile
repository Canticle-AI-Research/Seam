# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
ARG RUNTIME_IMAGE=gcr.io/distroless/base-debian12:nonroot@sha256:63f52bd27b6aa6555f5d56500b70d7bb0afe51c654905be88a2c1cf967a77b1a

FROM ${PYTHON_IMAGE} AS build

ARG NUITKA_VERSION=4.1.3
ARG SEAM_ENTITLEMENT_PUBLIC_KEY_B64

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential patchelf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY pyproject.toml README.md LICENSE NOTICE COMMERCIAL_LICENSE.md MANIFEST.in ./
COPY LICENSES/ ./LICENSES/
COPY seam.py ./
COPY seam_runtime/ ./seam_runtime/
COPY selfhost/entrypoint.py ./selfhost/entrypoint.py

RUN python -m pip install --no-cache-dir \
      ".[server]" \
      "cryptography>=45,<50" \
      "Nuitka==${NUITKA_VERSION}" \
      "ordered-set>=4.1,<5" \
      "zstandard>=0.23,<1"

RUN test -n "${SEAM_ENTITLEMENT_PUBLIC_KEY_B64}" \
    && python -m nuitka \
      --mode=standalone \
      --deployment \
      --assume-yes-for-downloads \
      --python-flag=isolated \
      --python-flag=no_docstrings \
      --include-package=seam_runtime \
      --output-dir=/out \
      --output-filename=seam-selfhost \
      selfhost/entrypoint.py \
    && python -c "import base64, os, pathlib; pathlib.Path('/out/entitlement-public-key.pem').write_bytes(base64.b64decode(os.environ['SEAM_ENTITLEMENT_PUBLIC_KEY_B64'], validate=True))" \
    && ! find /out/entrypoint.dist -type f \( -name '*.py' -o -name '*.pyc' -o -name '*.pyo' \) -print -quit | grep -q .

RUN cp --dereference \
      /lib/x86_64-linux-gnu/libz.so.1 \
      /lib/x86_64-linux-gnu/libgcc_s.so.1 \
      /out/entrypoint.dist/

FROM ${RUNTIME_IMAGE}

LABEL org.opencontainers.image.title="SEAM Proprietary Compiled Self-Host" \
      org.opencontainers.image.description="Opaque /v1-only proprietary SEAM MIRL engine" \
      org.opencontainers.image.licenses="LicenseRef-SEAM-Proprietary AND Apache-2.0" \
      com.seam.edition="compiled-self-host" \
      com.seam.public-api="v1"

WORKDIR /var/lib/seam
COPY --from=build --chown=65532:65532 /out/entrypoint.dist/ /opt/seam/app/
COPY --from=build --chown=65532:65532 /out/entitlement-public-key.pem /opt/seam/entitlement-public-key.pem
COPY --from=build --chown=65532:65532 /src/LICENSE /licenses/SEAM-LICENSE
COPY --from=build --chown=65532:65532 /src/NOTICE /licenses/SEAM-NOTICE
COPY --from=build --chown=65532:65532 /src/LICENSES/Apache-2.0.txt /licenses/Apache-2.0.txt

USER 65532:65532
EXPOSE 8765
VOLUME ["/var/lib/seam"]
ENTRYPOINT ["/opt/seam/app/seam-selfhost"]
