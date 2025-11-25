# Etherpad Deployment

## Docker Compose

Docker Compose configuration for deploying Etherpad on an external server:

```yaml
services:
  app:
    user: "0:0"
    image: etherpad/etherpad:latest
    tty: true
    stdin_open: true
    volumes:
      - ./plugins:/opt/etherpad-lite/src/plugin_packages
      - ./etherpad-var:/opt/etherpad-lite/var
    depends_on:
      - postgres
    environment:
      NODE_ENV: production
      ADMIN_PASSWORD: REDACTED
      DB_TYPE: "postgres"
      DB_CHARSET: utf8mb4
      DB_HOST: postgres
      DB_NAME: etherpad
      DB_PASS: REDACTED
      DB_PORT: 5432
      DB_USER: admin
      DEFAULT_PAD_TEXT: " "
      DISABLE_IP_LOGGING: false
      SOFFICE: null
      TRUST_PROXY: true
    restart: always
    ports:
      - "80:9001"

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: etherpad
      POSTGRES_PASSWORD: REDACTED
      POSTGRES_PORT: 5432
      POSTGRES_USER: admin
      PGDATA: /var/lib/postgresql/data/pgdata
    restart: always
    volumes:
      - ./postgres_data:/var/lib/postgresql/data
```

## Kubernetes

Kubernetes manifests to expose Etherpad via Traefik ingress controller:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: etherpad-service
  namespace: default
  labels:
    app: etherpad
spec:
  ports:
    - name: http
      port: 80          
      protocol: TCP
      targetPort: 80  
  type: ClusterIP

---

apiVersion: v1
kind: Endpoints
metadata:
  name: etherpad-service
  namespace: default
subsets:
  - addresses:
      - ip: 100.100.100.100
    ports:
      - name: http
        port: 80
        protocol: TCP

---

apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: etherpad-route
  namespace: default
  labels:
    app: etherpad
spec:
  entryPoints:
    - websecure
  routes:
    - kind: Rule
      match: Host(`etherpad.your-domain.com`)
      services:
        - name: etherpad-service
          port: 80
  tls:
    certResolver: myresolver

---

apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: etherpad-route-http
  namespace: default
spec:
  entryPoints:
    - web
  routes:
    - kind: Rule
      match: Host(`etherpad.your-domain.com`)
      middlewares:
        - name: redirect-to-https
      services:
        - name: etherpad-service
          port: 80
```

## Configuration Notes

- Replace `100.100.100.100` with the external server IP
- Replace `etherpad.your-domain.com` with your actual domain
- Ensure the `redirect-to-https` middleware is configured in Traefik
- The `myresolver` certificate resolver must be set up (e.g., Let's Encrypt)