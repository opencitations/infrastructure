
# How to Build a Custom WordPress Docker Image Using a Dockerfile

This guide explains how to create and update a custom WordPress Docker image starting from the official `wordpress:latest` image. The Dockerfile will install sendmail and the Redis PHP extension in a fully automated, non-interactive way.

---

## Step 1: Create a Dockerfile

Create a file named `Dockerfile` with the following content:

```Dockerfile
FROM wordpress:latest

USER root

# Avoid interactive prompts, install packages, and Redis PHP extension
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y sendmail && \
    printf "\n\n\n\n\n" | pecl install redis && \
    docker-php-ext-enable redis && \
    service sendmail start || true && \
    service apache2 restart

USER www-data
```

---

## Step 2: Build the custom image

Run this command in the directory where your Dockerfile is saved:

```bash
docker build -t yourusername/oc_wordpress:wp-custom01 .
```

Replace `yourusername` with your Docker Hub username or preferred tag.

---

## Step 3: Test your image locally

Start a container from your custom image:

```bash
docker run -it --rm -p 8080:80 yourusername/oc_wordpress:wp-custom01
```

Check that WordPress loads and that sendmail and Redis extension are installed.

---

## Step 4: Push your image to Docker Hub

Login first if not already done:

```bash
docker login
```

Push the image:

```bash
docker push yourusername/oc_wordpress:wp-custom01
```

