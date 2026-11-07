# Immagine della prova Docker dell'anonymizer, ormai abbandonata e conservata solo
# come riferimento. Esegue il servizio web in modalita solo locale, offline, con
# OCR Tesseract e NER ONNX su CPU, come utente non privilegiato.

FROM python:3.12-slim-bookworm

# Niente rete verso il hub dei modelli, cache in /tmp e un solo thread di calcolo.

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_IMPLICIT_TOKEN=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HOME=/tmp/huggingface \
    XDG_CACHE_HOME=/tmp/cache \
    HOME=/tmp \
    OMP_NUM_THREADS=1 \
    OMP_THREAD_LIMIT=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    TOKENIZERS_PARALLELISM=false \
    ANONYMIZER_TESSERACT=/usr/bin/tesseract

# Tesseract con lingua italiana, runtime OpenMP e utente dedicato senza home.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tesseract-ocr tesseract-ocr-ita libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 anonymizer \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp anonymizer

# Vincoli di versione condivisi da tutte le installazioni pip successive.
WORKDIR /opt/anonymizer
COPY tools/deploy/constraints.trial.txt deploy/constraints.trial.txt

# Install the CPU wheel first so dependency resolution cannot pull CUDA packages.
RUN python -m pip install --index-url https://download.pytorch.org/whl/cpu \
      'torch==2.7.1+cpu'

# Installa le dipendenze del progetto e degli extra necessari leggendole da
# pyproject.toml, prima di copiare il sorgente per sfruttare la cache dei layer.
COPY pyproject.toml ./
RUN python -c "import subprocess, sys, tomllib; \
    project = tomllib.load(open('pyproject.toml', 'rb'))['project']; \
    groups = project['optional-dependencies']; \
    dependencies = list(dict.fromkeys(project['dependencies'] + sum((groups[name] for name in ('web', 'visual', 'ocr', 'ner-onnx')), []))); \
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--constraint', 'deploy/constraints.trial.txt', *dependencies])"

# Sorgente del pacchetto e script di controllo di salute.
COPY src/anonymizer/ src/anonymizer/
COPY tools/deploy/healthcheck.py deploy/healthcheck.py
RUN python -m pip install --no-deps . \
    && python -m pip check

# Utente non privilegiato, controllo di salute e avvio del servizio solo locale.
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD ["python", "/opt/anonymizer/deploy/healthcheck.py"]
CMD ["anonymizer", "serve", "--local-only", "--port", "18765", "--ner-model", "/models/gliner", "--ner-runtime", "onnx", "--ner-threads", "1"]
