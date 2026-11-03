"""
Installable app: the web app manifest, a service worker and an offline page.

The service worker never caches the app's pages or data (they're private and change
constantly). It only keeps the offline page, shown when a page can't load because
the phone has no connection.
"""
import json

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control

OFFLINE_URL = '/offline/'
SW_VERSION = 'pe-offline-v1'


@cache_control(max_age=3600)
def manifest(request):
    icons = settings.COMPANY_ICONS_STATIC_DIR
    data = {
        'name': settings.COMPANY_NAME,
        'short_name': settings.COMPANY_NAME,
        'description': settings.CLIENT_PROFILE.app_description,
        'start_url': '/?source=app',
        'scope': '/',
        'display': 'standalone',
        'background_color': '#ffffff',
        'theme_color': settings.CLIENT_PROFILE.theme_color,
        'icons': [
            {'src': static(f'{icons}/icon-192.png'), 'sizes': '192x192', 'type': 'image/png'},
            {'src': static(f'{icons}/icon-512.png'), 'sizes': '512x512', 'type': 'image/png'},
            {'src': static(f'{icons}/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png',
             'purpose': 'maskable'},
        ],
    }
    return HttpResponse(json.dumps(data), content_type='application/manifest+json')


SERVICE_WORKER = """
const CACHE = '%(version)s';
const OFFLINE = '%(offline)s';
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.add(OFFLINE)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key !== CACHE).map(key => caches.delete(key))
  )).then(() => self.clients.claim()));
});
// Pages always come from the network; only when that fails is the offline page shown.
self.addEventListener('fetch', event => {
  if (event.request.mode !== 'navigate') return;
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
});
"""


@cache_control(no_cache=True)
def service_worker(request):
    body = SERVICE_WORKER % {'version': SW_VERSION, 'offline': OFFLINE_URL}
    return HttpResponse(body, content_type='application/javascript')


def offline(request):
    return render(request, 'core/offline.html', {'auth_page': True})
