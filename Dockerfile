FROM python:3.11-slim

# Temel ortam değişkenleri (Render & CloakBrowser optimizasyonu)
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    CLOAKBROWSER_AUTO_UPDATE=false \
    PORT=10000

# Chromium ve CloakBrowser için gerekli tam Linux sistem kütüphaneleri
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    gnupg \
    ca-certificates \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Önce paketleri yükle (Docker cache optimizasyonu)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium bağımlılıklarını doğrula ve CloakBrowser binary dosyasını build anında indir
RUN playwright install chromium || true
RUN python -c "import cloakbrowser; cloakbrowser.ensure_binary()"

# Kodları kopyala
COPY . .

# Render $PORT ortam değişkenini dinler, varsayılan 10000
EXPOSE 10000

CMD ["sh", "-c", "gunicorn --workers 1 --threads 4 --timeout 0 -b 0.0.0.0:${PORT:-10000} app:app"]
