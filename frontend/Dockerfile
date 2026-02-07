FROM node:20-slim

WORKDIR /app

# Install dependencies (copy lock file for deterministic installs)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source
COPY . .

EXPOSE 5173

# Run dev server
CMD ["npm", "run", "dev", "--", "--host"]
