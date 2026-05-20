self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(clients.claim()));

self.addEventListener("push", (e) => {
  let data = {};
  if (e.data) {
    try { data = e.data.json(); } catch (_) { data = { body: e.data.text() }; }
  }

  const title = data.title || "Course Alert";
  const options = {
    body: data.body || "A watched course now has upcoming run dates.",
    icon: "/static/icon.svg",
    tag: data.tgs_ref || "course-alert",
    renotify: true,
    data: { url: data.url || "/" },
  };

  e.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = e.notification.data.url;
  e.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((list) => {
        for (const c of list) {
          if (c.url === url && "focus" in c) return c.focus();
        }
        if (clients.openWindow) return clients.openWindow(url);
      })
  );
});
