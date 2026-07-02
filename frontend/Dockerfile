FROM node:20-alpine AS build

WORKDIR /app

ARG VITE_API_URL=/api
ARG APP_VERSION=0.1.0-beta.2
ARG BUILD_SHA=development
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_APP_VERSION=$APP_VERSION
ENV VITE_BUILD_SHA=$BUILD_SHA

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

FROM nginx:alpine

ARG APP_VERSION=0.1.0-beta.2
ARG BUILD_SHA=development
LABEL org.opencontainers.image.title="EasySales Frontend" \
      org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$BUILD_SHA

RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
