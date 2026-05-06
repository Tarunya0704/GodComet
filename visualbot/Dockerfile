FROM node:20-slim

# System deps: git for cloning user repos, plus libs Playwright/chromium needs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install node deps first for better layer caching.
COPY package*.json ./
RUN npm ci

# Install chromium + its OS deps via Playwright.
RUN npx --yes playwright install --with-deps chromium

COPY tsconfig.json ./
COPY src ./src
RUN npm run build

ENV NODE_ENV=production
ENV PORT=3000
EXPOSE 3000

CMD ["npm", "start"]
