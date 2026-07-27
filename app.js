(function () {
  const frame = document.getElementById("app-frame");
  const offline = document.getElementById("offline-overlay");

  document.title = CONFIG.appName;
  frame.src = CONFIG.iframeUrl;

  function syncOnline() {
    const online = navigator.onLine;
    offline.hidden = online;
    offline.style.display = online ? "none" : "flex";
    frame.style.visibility = online ? "visible" : "hidden";
  }

  window.addEventListener("online", syncOnline);
  window.addEventListener("offline", syncOnline);
  syncOnline();

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js").catch(function (err) {
      console.warn("SW register failed", err);
    });
  }
})();
