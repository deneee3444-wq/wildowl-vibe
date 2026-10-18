FROM python:3.11-slim

# Temel ortam değişkenleri
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    CLOAKBROWSER_AUTO_UPDATE=false \
    CLOAKBROWSER_SUPPRESS_FONT_WARNING=1 \
    PORT=10000 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_SKIP_BROWSER_GC=1

# Sistem kütüphaneleri (minimal set)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg ca-certificates \
    libglib2.0-0 libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libdbus-1-3 libxcb1 libxkbcommon0 \
    libx11-6 libxcomposite1 libxdamage1 libxext6 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

WORKDIR /app

# Önce paketleri yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium'u minimal flag'lerle kur
RUN playwright install chromium --with-deps || true

# CloakBrowser binary'sini build anında indir
RUN python -c "import cloakbrowser; cloakbrowser.ensure_binary()" || true

# Kodları kopyala
COPY . .

# Render $PORT'u dinler
EXPOSE 10000

# 1 worker, 4 thread, 120sn timeout, max-requests ile bellek sızıntısı kontrolü
CMD ["sh", "-c", "gunicorn --workers 1 --threads 4 --timeout 120 --max-requests 100 --max-requests-jitter 20 -b 0.0.0.0:${PORT:-10000} app:app"]
