# ---- 构建阶段 ----
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
# `npm ci` 要求存在 package-lock.json；在 CI 构建或开发环境可能缺失。
# 使用 `npm install` 提高构建健壮性（如果需要严格锁版本，可在构建前生成 lock 文件）。
RUN npm install --no-audit --prefer-offline --no-fund

COPY . .
RUN npm run build

# ---- 生产阶段 ----
FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx-spa.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
