FROM python:3.11-slim

# Chromium'un headless çalışabilmesi için gerekli Linux sistem kütüphaneleri
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    ca-certificates \
    libglib2.0-0 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Önce paketleri yükle (Docker cache optimizasyonu)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# CloakBrowser binary dosyasını build anında indir
RUN python -c "import cloakbrowser; cloakbrowser.ensure_binary()"

# Kodları kopyala
COPY . .

# Render $PORT ortam değişkenini dinler, varsayılan 10000
ENV PORT=10000
EXPOSE 10000

CMD ["sh", "-c", "gunicorn --workers 1 --threads 100 --timeout 0 -b 0.0.0.0:${PORT:-10000} app:app"]
