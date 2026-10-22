/* Service worker de «Acta de Visita de Campo» (TEAMBIMCIVIL).
 * Guarda en el teléfono todos los archivos de la versión publicada para que la app
 * se abra y genere el PDF sin cobertura.
 * AL PUBLICAR UNA VERSIÓN NUEVA: cambiar VERSION aquí y en index.html (deben coincidir). */
const VERSION = '2.3';
const CACHE = `acta-tbc-v${VERSION}`;
const ARCHIVOS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './lib/jspdf.umd.min.js',
  './lib/fuentes-pdf.js',
  './icons/icono-192.png',
  './icons/icono-512.png',
  './icons/icono-maskable-512.png',
  './icons/apple-touch-icon.png',
];

// Instalación: descarga la versión completa (sin pasar por la caché HTTP del navegador).
self.addEventListener('install', evento => {
  evento.waitUntil(
    caches.open(CACHE)
      .then(cache => cache.addAll(ARCHIVOS.map(url => new Request(url, { cache: 'reload' }))))
      .then(() => self.skipWaiting())
  );
});

// Activación: borra las versiones anteriores y toma el control de las pestañas abiertas.
self.addEventListener('activate', evento => {
  evento.waitUntil(
    caches.keys()
      .then(claves => Promise.all(claves
        .filter(clave => clave.startsWith('acta-tbc-') && clave !== CACHE)
        .map(clave => caches.delete(clave))))
      .then(() => self.clients.claim())
  );
});

// Peticiones: primero la copia guardada (arranque inmediato y sin cobertura); si no está, la red.
self.addEventListener('fetch', evento => {
  const peticion = evento.request;
  if (peticion.method !== 'GET' || new URL(peticion.url).origin !== self.location.origin) return;
  evento.respondWith(
    caches.match(peticion, { ignoreSearch: true }).then(copia => copia || fetch(peticion))
  );
});
