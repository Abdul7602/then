// Then — Service Worker
// Handles background notification delivery

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(clients.claim()));

// Active notification timers
const timers = new Map();

self.addEventListener('message', e => {
  const { type } = e.data;

  if (type === 'SCHEDULE') {
    // Clear previous timers
    timers.forEach(id => clearTimeout(id));
    timers.clear();

    // Schedule each notification
    (e.data.items || []).forEach((item, i) => {
      const delay = Math.max(500, item.fireAt - Date.now());
      const id = setTimeout(async () => {
        timers.delete(i);
        const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
        if (all.length > 0) {
          // Tab is open — tell the page to show it in-app
          all[0].postMessage({ type: 'SHOW_NOTIFICATION', text: item.text });
        } else {
          // No tab open — show native OS notification
          await self.registration.showNotification('Then', {
            body: item.text,
            icon: '/logo/then-icon.png',
            tag: 'then-' + i,
            silent: true,
            data: { url: '/' },
          });
        }
      }, delay);
      timers.set(i, id);
    });
  }

  if (type === 'CANCEL') {
    timers.forEach(id => clearTimeout(id));
    timers.clear();
  }
});

// Open/focus app when notification is clicked
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(
    self.clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then(all => {
        if (all.length) return all[0].focus();
        return self.clients.openWindow('/');
      })
  );
});
