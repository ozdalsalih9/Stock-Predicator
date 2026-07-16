FROM node:22-alpine AS build
WORKDIR /app
COPY web/probora-web/package*.json ./
RUN npm ci
COPY web/probora-web/ .
RUN npm run build

FROM nginx:1.29-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY infra/nginx/default.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
