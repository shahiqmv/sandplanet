# Deploying Sand Planet (M8) — DigitalOcean droplet + Docker Compose

The production stack is **Postgres + app (gunicorn) + Caddy (auto-HTTPS)** in
Docker Compose, with uploaded files on **DigitalOcean Spaces**. Django serves
the built SPA, so there is one web service, not two.

## 1. One-time cloud setup

1. **Droplet** — Ubuntu 22.04+, 2 GB RAM min (PDF rendering + Postgres).
   Install Docker Engine + the compose plugin.
2. **DNS** — point an A record for your domain (e.g. `app.sandplanet.mv`) at
   the droplet's IP. Caddy needs this resolving before it can get a cert.
3. **Spaces** — create a Spaces bucket (e.g. `sandplanet`) and a Spaces
   access key/secret. Note the regional endpoint
   (e.g. `https://sgp1.digitaloceanspaces.com`).

## 2. Configure

```sh
git clone <repo> sandplanet && cd sandplanet
cp .env.prod.example .env
# generate a real secret key:
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
nano .env      # fill DOMAIN, DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS,
               # CSRF_TRUSTED_ORIGINS, POSTGRES_PASSWORD, S3_* , SEED_ADMIN_PASSWORD
```

## 3. First deploy

```sh
# build + start db, app, caddy; Caddy fetches the TLS cert automatically
RUN_SEED=1 docker compose -f docker-compose.prod.yml up -d --build
```

`RUN_SEED=1` seeds starter sites, the worker-category list, company
parameters, and the `admin` user (password = `SEED_ADMIN_PASSWORD`). It is
idempotent. After the first boot, drop `RUN_SEED` (normal restarts should not
re-seed). Then:

```sh
# confirm health and log in
curl -s https://$DOMAIN/api/v1/health
# change the admin password from the app, or:
docker compose -f docker-compose.prod.yml exec web \
  python manage.py changepassword admin
```

Edit the seeded sites/categories to your real ones from the app (Admin →
Site Setup, People → Worker Categories, Procurement → Item Categories).

## 4. Turn on HSTS (after HTTPS is confirmed)

Once `https://$DOMAIN` loads with a valid cert, set in `.env` and redeploy:

```
SECURE_HSTS_SECONDS=31536000
```
```sh
docker compose -f docker-compose.prod.yml up -d
```

## 5. Backups

- **Database** — nightly `pg_dump` off the droplet:
  ```sh
  docker compose -f docker-compose.prod.yml exec -T db \
    pg_dump -U sandplanet sandplanet | gzip > sp-$(date +%F).sql.gz
  ```
  Add it to cron and copy the dump to Spaces or another host.
- **Files** — already on Spaces (durable); enable Spaces versioning if wanted.

## 6. Updates

One command on the droplet, from `~/sandplanet`:
```sh
bash update.sh
```
It pulls the latest code and rebuilds/restarts. Equivalent to:
```sh
git pull
docker compose -f docker-compose.prod.yml up -d --build
```
Migrations and `collectstatic` run automatically on container start; the
database volume and Spaces files are untouched.

## 7. Notes

- Uploaded documents (payment slips, receipts, photos) are served from Spaces
  via time-limited signed URLs — no media reverse-proxy needed.
- Only Caddy exposes ports (80/443); Postgres and the app are not published to
  the host.
- `manage.py check --deploy` should be clean once `DJANGO_SECRET_KEY` and
  (optionally) HSTS are set.
- Docker was not available in the build environment, so the image has not been
  built here — the first `up --build` on the droplet is the first real build.
  If the WeasyPrint apt list needs a tweak for your base image, it's the
  `apt-get install` line in `Dockerfile`.
