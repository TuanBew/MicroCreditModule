# Stage 1: Build the React/Vite app
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
# npm install instead of npm ci: lock file may have Windows-native binaries from local dev
RUN npm install --prefer-offline 2>/dev/null || npm install

COPY . .
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine

# Remove default nginx static content
RUN rm -rf /usr/share/nginx/html/*

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
