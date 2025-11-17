FROM node:20-alpine

WORKDIR /app

COPY package.json tsconfig.json ./
RUN npm install

COPY src ./src

RUN npm run build

ENV MCP_HTTP_PORT=3000
ENV APP_DB_PATH=/app/data/app.db

EXPOSE 3000

CMD ["npm", "start"]

