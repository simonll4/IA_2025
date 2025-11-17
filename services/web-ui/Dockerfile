FROM nginx:alpine

WORKDIR /usr/share/nginx/html

# Copiamos la UI estática
COPY static/ /usr/share/nginx/html/

# Configuración de Nginx para proxy a los servicios backend
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

