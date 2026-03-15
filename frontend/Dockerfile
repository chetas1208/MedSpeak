FROM node:22-alpine

WORKDIR /app

COPY package.json package.json
COPY tsconfig.json tsconfig.json
COPY next.config.js next.config.js
COPY postcss.config.mjs postcss.config.mjs
COPY next-env.d.ts next-env.d.ts
COPY src src
COPY public public

RUN npm install

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
