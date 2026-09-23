# Deployment Guide — Pretty Events

Two supported deployment routes, using the same Dockerfile either way:

- **Option A — Railway** (what's actually live right now): a managed PaaS —
  no server admin, HTTPS and Postgres handled for you, ~$5-15/month.
- **Option B — VPS + docker-compose + Nginx**: full control, more manual
  maintenance (SSL renewal, backups, patching), similar or lower raw cost.

---

## Option A: Railway (current production setup)

Project name on Railway: **stellar-appreciation**, environment **production**.
Live URL: `https://management.prettyeventslimited.co.ug` (custom domain, CNAME to Railway).
The service has `ALLOWED_HOSTS=management.prettyeventslimited.co.ug` and
`CSRF_TRUSTED_ORIGINS=https://management.prettyeventslimited.co.ug` set explicitly, so the old
`…up.railway.app` address deliberately answers 400.

### 1. Create the project and connect the repo

1. On [railway.app](https://railway.app), **New Project → Deploy from GitHub repo**.
2. Select `Pretty_events_management_system` (authorize Railway's GitHub app
   if prompted). Railway detects the `Dockerfile` and builds from it
   automatically — no buildpack config needed.

### 2. Add a Postgres database

In the same project: **+ New → Database → PostgreSQL**. This creates a
separate `Postgres` service alongside the web service.

### 3. Set environment variables on the web service

Web service → **Variables** tab → add:

| Variable | Value |
|---|---|
| `SECRET_KEY` | a long random string — generate with `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DEBUG` | `False` |
| `DJANGO_SETTINGS_MODULE` | `config.settings.production` |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (use **Add Reference** to pull this from the Postgres service rather than typing it by hand) |

Don't set `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` manually — `config/settings/production.py`
reads Railway's own `RAILWAY_PUBLIC_DOMAIN` variable (visible under the
collapsed **"N variables added by Railway"** section on the same Variables
tab) and adds it automatically.

### 4. Generate the public domain

Web service → **Settings → Networking → Generate Domain**.

⚠️ **Gotcha we hit**: if the container was already running *before* you
generate the domain, it won't have `RAILWAY_PUBLIC_DOMAIN` in its environment
yet (env vars are read once at process start) — you'll get a `400 Bad
Request` (Django's `ALLOWED_HOSTS` check failing) even though the variable
shows correctly in the dashboard. Fix: **Deployments tab → latest deployment
→ ⋮ → Redeploy** to restart the container with the current env.

### 5. First deploy already runs migrations for you

`entrypoint.sh` runs `migrate`, `collectstatic`, and `setup_groups` on every
container start — no manual step needed here, unlike the VPS route.

### 6. Create the first admin login

Web service → **Console** tab, run (non-interactive, since the web console
doesn't reliably support interactive prompts):

```bash
DJANGO_SUPERUSER_PASSWORD=YourStrongPasswordHere python manage.py createsuperuser --username admin --email you@example.com --noinput
```

Then log in at the generated domain's `/login/`.

### 7. Redeploying after future code changes

Just `git push` to `main` — Railway watches the connected branch and
redeploys automatically on every push (including running the entrypoint
steps again).

### Cost

Railway bills usage-based on top of a plan (Hobby: $5/month base, which
includes $5 of usage credit). For this app's expected traffic (internal
staff use, not high public traffic): roughly **$5-15/month total** for the
web service + Postgres combined. Watch actual usage in the dashboard for
the first month to confirm.

---

## Option B: VPS + docker-compose + Nginx

Target: one small VPS (~$46/yr tier, e.g. a 1-2GB DigitalOcean/Hetzner/Linode
droplet) running Django + Gunicorn + Nginx via docker-compose, talking to a
managed Neon Postgres database over the network. No local Postgres container.

### 1. Provision the VPS and harden it

```bash
# As root, right after provisioning:
adduser deploy
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy   # copy your SSH key over

# Then disable password/root login — edit /etc/ssh/sshd_config:
#   PermitRootLogin no
#   PasswordAuthentication no
systemctl restart sshd

# Firewall — only SSH, HTTP, HTTPS
ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw enable

# fail2ban for SSH brute-force protection
apt-get update && apt-get install -y fail2ban
systemctl enable --now fail2ban
```

From here on, log in as `deploy`, not root.

### 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker deploy
# log out and back in for the group change to apply
```

### 3. Point the domain at the server (Namecheap)

In Namecheap's DNS settings for the domain, add an **A record**:
`@` (or a subdomain like `app`) → the VPS's public IP address. Propagation
can take a few minutes to a few hours.

### 4. Get the code onto the server

```bash
git clone <your-repo-url> pretty_events
cd pretty_events
cp .env.example .env
```

Edit `.env` with real production values:
- `SECRET_KEY` — generate one, e.g. `python -c "import secrets; print(secrets.token_urlsafe(50))"`
- `DEBUG=False`
- `ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com`
- `CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com`
- `DATABASE_URL=postgres://<user>:<password>@<neon-host>/<db>?sslmode=require`
  (copy the exact connection string from the Neon dashboard — Project → Connect)

### 5. Bootstrap TLS (first time only)

Nginx needs a certificate before it can serve HTTPS, and Certbot needs a
running webserver to complete the HTTP challenge — so bootstrap in two steps:

```bash
# Step 1: start with the HTTP-only nginx config
cp nginx/default.conf.http-only nginx/default.conf
# replace YOUR_DOMAIN_HERE with the real domain in nginx/default.conf

docker compose up -d --build

# Step 2: obtain the certificate via the webroot method
docker run --rm \
  -v pretty_events_certbot_www:/var/www/certbot \
  -v pretty_events_certbot_certs:/etc/letsencrypt \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d yourdomain.com -d www.yourdomain.com \
  --email you@example.com --agree-tos --no-eff-email
```

Then switch to the real TLS config:

```bash
git checkout nginx/default.conf   # restore the TLS version from the repo
# replace YOUR_DOMAIN_HERE with the real domain (three occurrences)
docker compose restart nginx
```

**Renewal**: certificates expire every 90 days. Add a cron job on the host:

```bash
(crontab -l 2>/dev/null; echo "0 3 * * 1 docker run --rm -v pretty_events_certbot_www:/var/www/certbot -v pretty_events_certbot_certs:/etc/letsencrypt certbot/certbot renew --webroot -w /var/www/certbot --quiet && docker compose -f /home/deploy/pretty_events/docker-compose.yml restart nginx") | crontab -
```

### 6. Run migrations and collect static files

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py setup_groups
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py collectstatic --noinput
```

### 7. Verify

Visit `https://yourdomain.com` — you should see the login page. Log in with
the superuser account you just created.

### 8. Uptime monitoring (basic, no dedicated IT staff needed)

Use a free tier of an external uptime checker (e.g. UptimeRobot or
Better Stack) pointed at `https://yourdomain.com/login/`, checking every 5
minutes with email/SMS alerting. This needs no server-side setup.

### Notes

- **Database backups**: Neon's free tier retains point-in-time recovery for
  a limited window (check the current limit on the Neon dashboard before
  relying on it as the sole copy of financial data — if the free tier's
  retention isn't enough, a simple `pg_dump` cron job piping to the VPS or
  to cheap object storage is a reasonable Phase 2 addition).
- **Updating the app**: `git pull && docker compose up -d --build && docker compose exec web python manage.py migrate`
- **No Postgres container**: the database is Neon, reached over the network
  via `DATABASE_URL` — don't add a `postgres` service to docker-compose.
