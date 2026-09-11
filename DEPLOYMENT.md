# Deployment Guide — Pretty Events

Target: one small VPS (~$46/yr tier, e.g. a 1-2GB DigitalOcean/Hetzner/Linode
droplet) running Django + Gunicorn + Nginx via docker-compose, talking to a
managed Neon Postgres database over the network. No local Postgres container.

## 1. Provision the VPS and harden it

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

## 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker deploy
# log out and back in for the group change to apply
```

## 3. Point the domain at the server (Namecheap)

In Namecheap's DNS settings for the domain, add an **A record**:
`@` (or a subdomain like `app`) → the VPS's public IP address. Propagation
can take a few minutes to a few hours.

## 4. Get the code onto the server

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

## 5. Bootstrap TLS (first time only)

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

## 6. Run migrations and collect static files

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py setup_groups
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py collectstatic --noinput
```

## 7. Verify

Visit `https://yourdomain.com` — you should see the login page. Log in with
the superuser account you just created.

## 8. Uptime monitoring (basic, no dedicated IT staff needed)

Use a free tier of an external uptime checker (e.g. UptimeRobot or
Better Stack) pointed at `https://yourdomain.com/login/`, checking every 5
minutes with email/SMS alerting. This needs no server-side setup.

## Notes

- **Database backups**: Neon's free tier retains point-in-time recovery for
  a limited window (check the current limit on the Neon dashboard before
  relying on it as the sole copy of financial data — if the free tier's
  retention isn't enough, a simple `pg_dump` cron job piping to the VPS or
  to cheap object storage is a reasonable Phase 2 addition).
- **Updating the app**: `git pull && docker compose up -d --build && docker compose exec web python manage.py migrate`
- **No Postgres container**: the database is Neon, reached over the network
  via `DATABASE_URL` — don't add a `postgres` service to docker-compose.
