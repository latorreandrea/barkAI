# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# BarkAI -- production image.
#
# Two stages on purpose: the builder installs the dependencies into a private
# directory and the runtime stage copies only that. Nothing used to install or
# compile survives into the final image (no pip, no setuptools, no build cache).
#
# The link to COST is the cold start: Cloud Run bills startup time, so a smaller
# image starts sooner and costs less. That is also why --no-compile is NOT used:
# the .pyc files cost a few MB but avoid compiling ~100 packages on the first
# request. Paying in MB beats paying in billed seconds.
#
# One image, two uses: the web service (default CMD) and the scheduled
# maintenance job (same artifact, command overridden by Cloud Run Jobs).
#
# No environment variable and no secret is defined here on purpose: they are set
# from Cloud Run, and the service and the job each carry their own.
# ---------------------------------------------------------------------------

FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements.txt ./

# --target keeps the whole install in one directory that can be copied at once.
RUN python -m pip install --target=/install -r requirements.txt


FROM python:3.11-slim AS runtime

# PYTHONDONTWRITEBYTECODE: at runtime the app must not write caches.
# PYTHONUNBUFFERED: logs reach Cloud Logging immediately instead of sitting in a
# buffer (without it, a failing job looks silent).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Dependencies installed by the builder stage.
COPY --from=builder /install /usr/local/lib/python3.11/site-packages

# Drop the packaging tools: unused at runtime and worth ~25-30 MB.
RUN rm -rf \
      /usr/local/lib/python3.11/site-packages/pip \
      /usr/local/lib/python3.11/site-packages/pip-* \
      /usr/local/lib/python3.11/site-packages/setuptools \
      /usr/local/lib/python3.11/site-packages/setuptools-* \
      /usr/local/lib/python3.11/site-packages/wheel \
      /usr/local/lib/python3.11/site-packages/wheel-* \
      /usr/local/lib/python3.11/ensurepip

WORKDIR /app

# Application source. .dockerignore keeps .env, .venv, node_modules and the local
# database out of the build context (see that file for the full list).
COPY . .

# Build-time steps. DEBUG is scoped to this RUN on purpose and must NOT be baked
# into the image: as an ENV it would make the app start in debug mode in
# production whenever the variable is missing on Cloud Run.
# No credential is needed here: collectstatic does not touch the database and
# compile_messages is a plain script.
RUN python scripts/compile_messages.py \
 && DEBUG=True python manage.py collectstatic --noinput

EXPOSE 8080

# Two workers are enough: the app is I/O-bound and the latency comes from the LLM
# call. A 120 s timeout covers a slow reasoning-model answer.
CMD ["sh", "-c", "exec gunicorn barkai.wsgi:application --bind 0.0.0.0:${PORT} --workers 2 --timeout 120 --access-logfile - --error-logfile -"]
