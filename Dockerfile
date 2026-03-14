FROM node:20-slim

# Install Playwright dependencies + ffmpeg
RUN apt-get update && apt-get install -y \
  ffmpeg \
  libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
  libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
  libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
  fonts-noto-color-emoji fonts-noto-cjk \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json ./
RUN npm install

# Install Playwright Chromium
RUN npx playwright install chromium

COPY server.js ./

EXPOSE 3001

CMD ["node", "server.js"]
