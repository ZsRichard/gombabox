/* Server Web Push plus in-app monitoring and event history. */
(() => {
    const defaults = { enabled: true, system: false, temp_margin: 2, humidity_margin: 10, co2_limit: 1500, delay: 120, recovery: true };
    const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };
    let prefs = { ...defaults, ...read('gombabox-notification-settings', {}) };
    let history = read('gombabox-notification-history', []);
    if (!Array.isArray(history)) history = [];
    const states = new Map();
    let busy = false;
    let previousPhase = null;
    let deviceToken = read('gombabox-push-token', null);
    if (!deviceToken) { deviceToken = crypto.randomUUID() + crypto.randomUUID(); try { localStorage.setItem('gombabox-push-token', JSON.stringify(deviceToken)); } catch { /* Enable handler requires persistent storage. */ } }
    async function pushApi(path, method = 'GET', body) {
        const response = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-Notification-Token': deviceToken }, body: body ? JSON.stringify(body) : undefined });
        let data;
        try { data = await response.json(); }
        catch { throw new Error(`A szerver nem megfelelő választ adott (HTTP ${response.status}). Frissítsd az alkalmazást, majd próbáld újra.`); }
        if (!response.ok) throw new Error(data.error || 'A szerver nem érhető el.');
        return data;
    }
    async function syncPush() {
        const registration = await navigator.serviceWorker.ready;
        const subscription = await registration.pushManager.getSubscription();
        if (!subscription) throw new Error('A push-feliratkozás hiányzik; engedélyezd újra.');
        await pushApi('/api/push/device', 'POST', { subscription: subscription.toJSON(), prefs });
    }
    const panel = document.getElementById('notification-center');
    if (!panel) return;
    const indicator = document.getElementById('notification-indicator');
    const indicatorIcon = document.getElementById('notification-indicator-icon');
    const indicatorCount = document.getElementById('notification-indicator-count');
    const optInModalElement = document.getElementById('notification-opt-in-modal');
    const optInEnable = document.getElementById('notification-opt-in-enable');
    const optInLater = document.getElementById('notification-opt-in-later');
    const optInInfo = document.getElementById('notification-opt-in-info');
    const promptDismissedKey = 'gombabox-notification-prompt-dismissed';
    const store = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Private browsing may disable storage. */ } };
    panel.innerHTML = `<div class="card-header"><i class="fas fa-bell"></i> Értesítések</div>
        <div class="card-body">
        <p class="small text-muted">Web Push engedélyezése után a Pi bezárt alkalmazás mellett is küld riasztásokat. A teljes Pi-kieséshez később külső felügyelet szükséges. A megnyitott felület kapcsolatjelzése hálózati hibát is jelenthet. A beállítások eszközönként érvényesek.</p>
        <form id="notification-preferences" class="row g-3">
        <label class="col-12"><input type="checkbox" name="enabled"> Állapotfigyelés bekapcsolása</label>
        <label class="col-md-4">Hőmérséklet-tűrés a célértékhez (± °C)<input class="form-control" name="temp_margin" type="number" min="0.1" max="20" step="0.1" required></label>
        <label class="col-md-4">Páratartalom-tűrés (± százalékpont)<input class="form-control" name="humidity_margin" type="number" min="1" max="100" required></label>
        <label class="col-md-4">CO₂ felső határ (ppm)<input class="form-control" name="co2_limit" type="number" min="400" max="10000" required></label>
        <label class="col-md-4">Tartós eltérés késleltetése (másodperc)<input class="form-control" name="delay" type="number" min="30" max="3600" required></label>
        <label class="col-md-8 align-self-center"><input type="checkbox" name="recovery"> Értesítés a helyreállásról is</label>
        <div class="col-12 d-flex flex-wrap gap-2"><button class="btn btn-primary" type="submit">Mentés</button><button class="btn btn-outline-primary" type="button" id="notification-permission">Telefonos értesítések engedélyezése</button><button class="btn btn-outline-secondary" type="button" id="notification-test">Próbaértesítés</button><button class="btn btn-outline-secondary" type="button" id="notification-mute">Telefonos értesítések kikapcsolása</button></div>
        </form><p id="notification-info" class="small mt-3" role="status"></p>
        <div id="notification-active" aria-live="polite"></div><h6 class="mt-3">Legutóbbi események</h6><ul id="notification-history" class="list-unstyled small"></ul>
        </div>`;
    const form = panel.querySelector('form');
    for (const key of ['enabled', 'recovery', 'temp_margin', 'humidity_margin', 'co2_limit', 'delay']) {
        const field = form.elements.namedItem(key);
        if (field.type === 'checkbox') field.checked = Boolean(prefs[key]); else field.value = prefs[key];
    }
    const info = text => { document.getElementById('notification-info').textContent = text; };
    const supportsSystemNotifications = () => 'Notification' in window && 'serviceWorker' in navigator && 'PushManager' in window;
    function setIndicatorState(state, label, icon) {
        if (!indicator || !indicatorIcon) return;
        indicator.className = `navbar-notification status-${state}`;
        indicatorIcon.className = `fas ${icon}`;
        indicator.setAttribute('aria-label', label);
        indicator.title = label;
    }
    async function updateNotificationIndicator(activeCount = [...states.values()].filter(s => s.sent).length) {
        if (indicatorCount) {
            indicatorCount.textContent = activeCount > 99 ? '99+' : String(activeCount);
            indicatorCount.classList.toggle('d-none', activeCount === 0);
        }
        if (!supportsSystemNotifications()) {
            setIndicatorState('unsupported', 'A rendszerértesítések nem támogatottak – beállítások megnyitása', 'fa-bell-slash');
            return;
        }
        if (Notification.permission === 'denied') {
            setIndicatorState('blocked', 'Az értesítések le vannak tiltva – beállítások megnyitása', 'fa-bell-slash');
            return;
        }
        if (Notification.permission !== 'granted' || !prefs.system || !prefs.enabled) {
            setIndicatorState('disabled', 'Az értesítések ki vannak kapcsolva – bekapcsolás', 'fa-bell-slash');
            return;
        }
        try {
            const registration = await navigator.serviceWorker.getRegistration();
            const subscription = registration && await registration.pushManager.getSubscription();
            if (subscription) {
                setIndicatorState('enabled', 'Az értesítések be vannak kapcsolva – beállítások megnyitása', 'fa-bell');
            } else {
                setIndicatorState('disabled', 'Az értesítési feliratkozás hiányzik – újraengedélyezés', 'fa-bell-slash');
            }
        } catch {
            setIndicatorState('disabled', 'Az értesítési állapot nem ellenőrizhető – beállítások megnyitása', 'fa-bell-slash');
        }
    }
    function render() {
        const active = [...states.values()].filter(s => s.sent);
        void updateNotificationIndicator(active.length);
        const target = document.getElementById('notification-active');
        target.replaceChildren();
        for (const s of active) {
            const item = document.createElement('p');
            item.className = 'alert alert-custom alert-warning-custom';
            item.textContent = `${s.alert.title}: ${s.alert.detail}`;
            target.append(item);
        }
        const list = document.getElementById('notification-history');
        list.replaceChildren();
        for (const entry of history.slice(0, 30)) {
            const item = document.createElement('li');
            item.className = 'border-bottom py-2';
            item.textContent = `${new Date(entry.time).toLocaleString('hu-HU')} — ${entry.title}: ${entry.detail}`;
            list.append(item);
        }
    }
    function showNotificationPrompt(force = false) {
        if (!optInModalElement || !supportsSystemNotifications() || Notification.permission !== 'default' || prefs.system) return;
        if (!force && read(promptDismissedKey, false)) return;
        bootstrap.Modal.getOrCreateInstance(optInModalElement).show();
    }
    async function enableSystemNotifications() {
        if (optInInfo) optInInfo.textContent = '';
        if (!supportsSystemNotifications()) {
            const message = 'Ez a böngésző nem támogatja a rendszerértesítéseket. iPhone-on a főképernyőre telepített PWA-t használd.';
            info(message);
            if (optInInfo) optInInfo.textContent = message;
            void updateNotificationIndicator();
            return false;
        }
        try {
            if (read('gombabox-push-token', null) !== deviceToken) throw new Error('Engedélyezd a böngésző helyi adattárolását.');
            if (await Notification.requestPermission() !== 'granted') {
                const message = 'Az értesítési engedély nincs megadva. A böngésző webhelybeállításaiban később engedélyezheted.';
                info(message);
                if (optInInfo) optInInfo.textContent = message;
                void updateNotificationIndicator();
                return false;
            }
            const data = await pushApi('/api/push/key');
            const key = Uint8Array.from(atob(data.publicKey.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - data.publicKey.length % 4) % 4)), c => c.charCodeAt(0));
            const registration = await navigator.serviceWorker.ready;
            await registration.pushManager.getSubscription() || await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
            await syncPush();
            prefs.system = true;
            store('gombabox-notification-settings', prefs);
            store(promptDismissedKey, true);
            info('Web Push aktív: a Pi bezárt alkalmazás mellett is küldhet értesítést.');
            await updateNotificationIndicator();
            return true;
        } catch (error) {
            const message = 'A Web Push bekapcsolása nem sikerült: ' + error.message;
            info(message);
            if (optInInfo) optInInfo.textContent = message;
            void updateNotificationIndicator();
            return false;
        }
    }
    async function publish(alert) {
        history.unshift({ ...alert, time: Date.now() });
        history = history.slice(0, 100);
        store('gombabox-notification-history', history);
        render();
        // System notifications are delivered by the server, avoiding duplicates.
    }
    function update(alerts) {
        const now = Date.now();
        const keys = new Set(alerts.map(a => a.key));
        for (const alert of alerts) {
            let state = states.get(alert.key);
            if (!state) { state = { since: now, sent: false, alert }; states.set(alert.key, state); }
            state.alert = alert;
            if (!state.sent && now - state.since >= prefs.delay * 1000) {
                state.sent = true;
                publish(alert);
            }
        }
        for (const [key, state] of states) {
            if (!keys.has(key)) {
                states.delete(key);
                if (state.sent && prefs.recovery) publish({ key, title: 'Helyreállt az állapot', detail: state.alert.title });
            }
        }
        render();
    }
    async function poll() {
        if (busy || !prefs.enabled) return;
        busy = true;
        try {
            const query = new URLSearchParams({ temp_margin: prefs.temp_margin, humidity_margin: prefs.humidity_margin, co2_limit: prefs.co2_limit });
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 10000);
            let response;
            try { response = await fetch(`/api/notifications/status?${query}`, { signal: controller.signal, cache: 'no-store' }); }
            finally { clearTimeout(timeout); }
            if (!response.ok) throw new Error('unavailable');
            const data = await response.json();
            if (!Array.isArray(data.alerts)) throw new Error('invalid');
            if (previousPhase !== null && data.phase !== previousPhase) {
                publish({ key: 'phase', title: 'Üzemmód változott', detail: ({ stopped: 'A termesztés szünetel.', colonization: 'Inkubáció elindítva.', fruiting: 'Termő szakasz elindítva.' })[data.phase] || data.phase });
            }
            previousPhase = data.phase;
            if (prefs.system) {
                const remote = await pushApi('/api/push/device');
                if (!remote.subscribed) info('A szerveres feliratkozás nem aktív. Engedélyezd újra a Web Push értesítéseket.');
                history = remote.events.map(e => ({ time: e.created * 1000, title: e.title, detail: e.detail + (e.delivered ? '' : ' (Kézbesítés sikertelen; újrapróbálkozás.)') }));
            }
            if (data.phase === 'stopped') {
                // Stopping is intentional, not evidence that a sensor recovered.
                for (const key of states.keys()) if (key !== 'connection') states.delete(key);
            }
            update(data.alerts);
        } catch {
            // Preserve unresolved sensor alarms while their state cannot be checked.
            update([...states.values()].filter(s => s.alert.key !== 'connection').map(s => s.alert).concat({ key: 'connection', title: 'A Pi nem érhető el', detail: 'Nincs kapcsolat a szerverrel. Ellenőrizd a hálózatot, a Tailscale-t és a Pi tápellátását.' }));
        } finally { busy = false; }
    }
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (!form.reportValidity()) return;
        for (const key of ['enabled', 'recovery', 'temp_margin', 'humidity_margin', 'co2_limit', 'delay']) {
            const field = form.elements.namedItem(key);
            prefs[key] = field.type === 'checkbox' ? field.checked : Number(field.value);
        }
        store('gombabox-notification-settings', prefs);
        states.clear(); render();
        try { if (prefs.system) await syncPush(); info('Beállítások elmentve.'); }
        catch (error) { info('A helyi beállítás mentve, de a szerver frissítése nem sikerült: ' + error.message); }
        poll();
    });
    document.getElementById('notification-permission').addEventListener('click', enableSystemNotifications);
    document.getElementById('notification-mute').addEventListener('click', async () => {
        try { await pushApi('/api/push/device', 'DELETE'); const registration = await navigator.serviceWorker.getRegistration(); const sub = registration && await registration.pushManager.getSubscription(); if (sub) await sub.unsubscribe(); prefs.system = false; store('gombabox-notification-settings', prefs); info('Web Push kikapcsolva ezen az eszközön.'); void updateNotificationIndicator(); }
        catch (error) { info('Nem sikerült a kikapcsolás: ' + error.message); }
    });
    document.getElementById('notification-test').addEventListener('click', async () => {
        try { await pushApi('/api/push/test', 'POST'); info('A push-szolgáltató átvette a próbaértesítést. Ellenőrizd a telefon értesítéseit.'); }
        catch (error) { info(error.message); }
    });
    indicator.addEventListener('click', () => {
        const tab = document.querySelector('a[href="#settings-tab"]');
        bootstrap.Tab.getOrCreateInstance(tab).show();
        panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    if (optInEnable) optInEnable.addEventListener('click', async () => {
        optInEnable.disabled = true;
        const enabled = await enableSystemNotifications();
        optInEnable.disabled = false;
        if (enabled) bootstrap.Modal.getOrCreateInstance(optInModalElement).hide();
    });
    if (optInLater) optInLater.addEventListener('click', () => store(promptDismissedKey, true));
    if (optInModalElement) optInModalElement.addEventListener('hidden.bs.modal', () => store(promptDismissedKey, true));
    window.addEventListener('gombabox:appinstalled', () => {
        try { localStorage.removeItem(promptDismissedKey); } catch { /* Ignore unavailable storage. */ }
        setTimeout(() => showNotificationPrompt(true), 500);
    });
    window.addEventListener('focus', () => void updateNotificationIndicator());
    if (navigator.permissions && navigator.permissions.query) {
        navigator.permissions.query({ name: 'notifications' }).then(status => {
            status.addEventListener('change', () => void updateNotificationIndicator());
        }).catch(() => { /* Notification permission changes are still checked on focus. */ });
    }
    info('A határértékek kiinduló beállítások; igazítsd őket a termesztési fázishoz.');
    render(); poll(); setInterval(poll, 30000);
    setTimeout(showNotificationPrompt, 1400);
    if (location.hash === '#settings-tab') bootstrap.Tab.getOrCreateInstance(document.querySelector('a[href="#settings-tab"]')).show();
    window.addEventListener('online', poll);
})();
