FROM node:20-slim

# System deps:
#   git    — clone user repos
#   procps — provides `ps`, required by tree-kill to enumerate child PIDs when
#            we kill the Next.js dev server tree. Without it tree-kill emits
#            ENOENT and crashes the whole node process.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        procps \
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
