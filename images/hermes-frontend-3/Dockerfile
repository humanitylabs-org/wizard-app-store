FROM nginx:stable-alpine@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94
LABEL org.opencontainers.image.source="https://github.com/humanitylabs-org/wizard-app-store"       org.opencontainers.image.description="Unmodified przbadu/hermes-ui browser frontend; separate Hermes backend required"       org.opencontainers.image.licenses="MIT"
COPY dist/ /usr/share/nginx/html/
COPY LICENSE.upstream /usr/share/nginx/html/LICENSE.upstream
COPY nginx.conf.template /opt/frontend/nginx.conf.template
COPY start.sh /opt/frontend/start.sh
USER 101:101
EXPOSE 8080
ENTRYPOINT ["/bin/sh", "/opt/frontend/start.sh"]
