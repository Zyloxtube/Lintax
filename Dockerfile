FROM python:3.11-slim

# Install essential system dependencies for Chromium (headless mode)
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    gnupg \
    && apt-get install -y \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libxkbcommon-x11-0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libxtst6 \
    libasound2 \
    libx11-xcb1 \
    libxcb1 \
    libxcb-dri3-0 \
    libxcb-shm0 \
    libxfixes3 \
    libxrender1 \
    libxshmfence1 \
    libgl1-mesa-glx \
    libgl1-mesa-dri \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libfreetype6 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libx11-6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright (without running `install-deps`)
RUN pip install --no-cache-dir playwright==1.48.0

# Install Chromium browser (this downloads the browser binary)
RUN playwright install chromium

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run the app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
