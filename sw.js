importScripts("./config.js");

const CACHE_NAME = CONFIG.appShortName + "-" + CONFIG.cacheVersion;
const urlsToCache = [
  "./",
  "./index.html",
  "./config.js",
  "./app.js",
  "./style.css",
  "./icon-192.png",
  "./icon-512.png",
  "./apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(urlsToCache))
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names.map((name) => {
            if (name !== CACHE_NAME) return caches.delete(name);
          })
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Streamlit·manifest는 항상 최신 네트워크 우선
  if (
    url.hostname.includes("streamlit.app") ||
    url.pathname.endsWith("/manifest.json") ||
    url.pathname.endsWith("manifest.json")
  ) {
    event.respondWith(fetch(event.request));
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
