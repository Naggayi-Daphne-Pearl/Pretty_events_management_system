from .base import *  # noqa

DEBUG = False

SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

# Railway assigns the public domain at provision time, so it can't be baked
# into ALLOWED_HOSTS/CSRF_TRUSTED_ORIGINS ahead of deploy — pick it up from
# the platform-provided env var instead of requiring a manual redeploy.
RAILWAY_PUBLIC_DOMAIN = env('RAILWAY_PUBLIC_DOMAIN', default='')
if RAILWAY_PUBLIC_DOMAIN:
    ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)
    CSRF_TRUSTED_ORIGINS.append(f'https://{RAILWAY_PUBLIC_DOMAIN}')

# If neither is set, Django answers every request with "400 Bad Request". Say so loudly
# in the deploy log instead of leaving it to be discovered from a broken site.
if not RAILWAY_PUBLIC_DOMAIN and set(ALLOWED_HOSTS) <= {'localhost', '127.0.0.1'}:
    import sys
    print(
        'WARNING: no public hostname configured (RAILWAY_PUBLIC_DOMAIN / ALLOWED_HOSTS are empty), '
        'so every web request will get 400 Bad Request. Set ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS '
        'on the Railway service, or redeploy after generating the domain.',
        file=sys.stderr,
    )
