FROM node:20-slim

WORKDIR /app

# Install dependencies
COPY package.json .
RUN npm install

# Copy source
COPY . .

EXPOSE 5173

# Run dev server
CMD ["npm", "run", "dev", "--", "--host"]
