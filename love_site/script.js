/* ============================================================
   Для тебя ❤️ — сердечки, лайтбокс, плавные переходы между страницами
   ============================================================ */
(function () {
    'use strict';

    var calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    /* ---------- летающие сердечки ---------- */
    function hearts() {
        if (calm) return;
        var box = document.createElement('div');
        box.className = 'hearts';
        box.setAttribute('aria-hidden', 'true');

        var glyphs = ['❤', '❤', '❥', '❤', '✦', '✧'];
        for (var i = 0; i < 16; i++) {
            var s = document.createElement('i');
            s.textContent = glyphs[i % glyphs.length];
            s.style.left = (Math.random() * 96 + 2).toFixed(2) + 'vw';
            s.style.fontSize = (Math.random() * 13 + 10).toFixed(1) + 'px';
            s.style.color = i % 3 === 0
                ? 'rgba(94,231,255,.55)'
                : (i % 2 === 0 ? 'rgba(255,61,129,.6)' : 'rgba(160,107,255,.55)');
            s.style.animationDuration = (Math.random() * 12 + 14).toFixed(1) + 's';
            s.style.animationDelay = (-Math.random() * 22).toFixed(1) + 's';
            s.style.setProperty('--dx', (Math.random() * 120 - 60).toFixed(0) + 'px');
            s.style.setProperty('--rot', (Math.random() * 90 - 45).toFixed(0) + 'deg');
            box.appendChild(s);
        }
        document.body.appendChild(box);
    }

    /* ---------- лайтбокс ---------- */
    function lightbox() {
        var shots = Array.prototype.slice.call(document.querySelectorAll('.shot img[data-full]'));
        if (!shots.length) return;

        var lb = document.createElement('div');
        lb.className = 'lightbox';
        lb.setAttribute('role', 'dialog');
        lb.setAttribute('aria-modal', 'true');
        lb.innerHTML =
            '<button class="lb-btn lb-close" type="button" aria-label="Закрыть">✕</button>' +
            '<button class="lb-btn lb-prev" type="button" aria-label="Предыдущее фото">‹</button>' +
            '<img alt="">' +
            '<button class="lb-btn lb-next" type="button" aria-label="Следующее фото">›</button>' +
            '<span class="lb-count"></span>' +
            '<span class="lb-hint">← → листать · Esc закрыть</span>';
        document.body.appendChild(lb);

        var img = lb.querySelector('img');
        var count = lb.querySelector('.lb-count');
        var order = [];
        var index = 0;

        function groupOf(el) {                       // фото внутри той же галереи
            var g = el.closest('.gallery');
            return (g ? Array.prototype.slice.call(g.querySelectorAll('img[data-full]')) : shots);
        }

        function show(i, dir) {
            index = (i + order.length) % order.length;
            var src = order[index].dataset.full || order[index].src;
            img.classList.remove('is-loaded');
            lb.classList.remove('is-loaded');
            var next = new Image();
            next.onload = function () {
                img.src = src;
                img.alt = order[index].alt || '';
                lb.classList.add('is-loaded');
                count.textContent = (index + 1) + ' / ' + order.length;
            };
            next.src = src;

            // предзагрузка соседних кадров
            [1, -1].forEach(function (d) {
                var n = order[(index + d + order.length) % order.length];
                if (!n) return;
                var p = new Image();
                p.src = n.dataset.full || n.src;
            });
            if (dir) count.textContent = (index + 1) + ' / ' + order.length;
        }

        function open(el) {
            order = groupOf(el);
            var i = order.indexOf(el);
            lb.classList.add('is-open');
            document.body.style.overflow = 'hidden';
            show(i < 0 ? 0 : i);
            lb.querySelector('.lb-close').focus();
        }

        function close() {
            lb.classList.remove('is-open', 'is-loaded');
            document.body.style.overflow = '';
            if (lastFocused) lastFocused.focus();
        }

        var lastFocused = null;

        shots.forEach(function (el) {
            var host = el.closest('.shot') || el;
            host.addEventListener('click', function () { lastFocused = host; open(el); });
            host.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); lastFocused = host; open(el); }
            });
        });

        lb.querySelector('.lb-close').addEventListener('click', close);
        lb.querySelector('.lb-prev').addEventListener('click', function (e) { e.stopPropagation(); show(index - 1, 1); });
        lb.querySelector('.lb-next').addEventListener('click', function (e) { e.stopPropagation(); show(index + 1, 1); });
        lb.addEventListener('click', function (e) { if (e.target === lb) close(); });

        document.addEventListener('keydown', function (e) {
            if (!lb.classList.contains('is-open')) return;
            if (e.key === 'Escape') close();
            else if (e.key === 'ArrowLeft') show(index - 1, 1);
            else if (e.key === 'ArrowRight') show(index + 1, 1);
        });

        // свайпы на телефоне
        var x0 = null, y0 = null;
        lb.addEventListener('touchstart', function (e) {
            x0 = e.changedTouches[0].clientX;
            y0 = e.changedTouches[0].clientY;
        }, { passive: true });
        lb.addEventListener('touchend', function (e) {
            if (x0 === null) return;
            var dx = e.changedTouches[0].clientX - x0;
            var dy = e.changedTouches[0].clientY - y0;
            if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy)) show(index + (dx < 0 ? 1 : -1), 1);
            else if (dy > 90 && Math.abs(dy) > Math.abs(dx)) close();
            x0 = y0 = null;
        }, { passive: true });
    }

    /* ---------- переход между страницами (обычный + одностраничная сборка) ---------- */
    function navigate(url) {
        if (!url) return;
        if (url.charAt(0) === '#' && typeof window.__spaGo === 'function') {   // все страницы в одном файле
            window.__spaGo(url);
            return;
        }
        if (calm) { location.href = url; return; }
        document.body.classList.add('is-leaving');
        setTimeout(function () { location.href = url; }, 240);
    }

    function transitions() {
        document.addEventListener('click', function (e) {
            var a = e.target.closest('a[href$=".html"], a[href^="#p"]');
            if (!a) return;
            if (a.target === '_blank' || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
            var url = a.getAttribute('href');
            if (url.indexOf('.html') > -1 && url === location.pathname.split('/').pop()) return; // уже здесь
            if (url.charAt(0) === '#' && typeof window.__spaGo !== 'function') return;            // обычные якоря
            e.preventDefault();
            navigate(url);
        });

        window.addEventListener('pageshow', function (e) {
            if (e.persisted) document.body.classList.remove('is-leaving');
        });

        // стрелки влево/вправо — между страницами
        document.addEventListener('keydown', function (e) {
            if (document.querySelector('.lightbox.is-open')) return;
            var btn = e.key === 'ArrowRight'
                ? document.querySelector('.btn--primary')
                : (e.key === 'ArrowLeft' ? document.querySelector('.btn--back') : null);
            if (!btn) return;
            e.preventDefault();
            navigate(btn.getAttribute('href'));
        });
    }

    /* ============================================================
       Статистика переписки (данные приходят с сервиса stats_service)
       ============================================================ */
    var STATS_API_DEFAULT = 'https://i-love-you-anya.onrender.com';   // ← адрес своего сервиса статистики

    function apiBase() {
        var fromQuery = new URLSearchParams(location.search).get('api');
        if (fromQuery) { try { localStorage.setItem('stats_api', fromQuery); } catch (e) {} }
        var saved = null;
        try { saved = localStorage.getItem('stats_api'); } catch (e) {}
        return String(fromQuery || saved || window.STATS_API || STATS_API_DEFAULT).replace(/\/+$/, '');
    }

    function plural(n, one, few, many) {
        var m10 = n % 10, m100 = n % 100;
        if (m10 === 1 && m100 !== 11) return one;
        if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
        return many;
    }

    function spaced(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' '); }

    function timeAgo(iso) {
        if (!iso) return '';
        var diff = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
        if (diff < 45) return 'только что';
        if (diff < 3600) { var m = Math.round(diff / 60); return m + ' ' + plural(m, 'минуту', 'минуты', 'минут') + ' назад'; }
        if (diff < 86400) { var h = Math.round(diff / 3600); return h + ' ' + plural(h, 'час', 'часа', 'часов') + ' назад'; }
        var d = Math.round(diff / 86400);
        return d + ' ' + plural(d, 'день', 'дня', 'дней') + ' назад';
    }

    function countUp(el, to) {
        if (!el) return;
        var from = parseInt(el.dataset.value || '0', 10) || 0;
        el.dataset.value = to;
        if (calm || from === to) { el.textContent = spaced(to); return; }
        var start = performance.now(), dur = 750;
        function tick(now) {
            var k = Math.min(1, (now - start) / dur);
            var eased = 1 - Math.pow(1 - k, 3);
            el.textContent = spaced(Math.round(from + (to - from) * eased));
            if (k < 1) requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
    }

    function stats() {
        var box = document.getElementById('stats');
        if (!box) return;

        var ui = {
            me: document.getElementById('statMe'),
            meSub: document.getElementById('statMeSub'),
            barMe: document.getElementById('barMe'),
            other: document.getElementById('statOther'),
            otherSub: document.getElementById('statOtherSub'),
            barOther: document.getElementById('barOther'),
            total: document.getElementById('statTotal'),
            who: document.getElementById('statsWho'),
            when: document.getElementById('statsUpdated'),
            verdict: document.getElementById('statsVerdict'),
            hint: document.getElementById('statsHint'),
            days: document.getElementById('statsDays'),
            refresh: document.getElementById('statsRefresh')
        };

        var base = apiBase();
        var busy = false, slowTimer = null;

        function render(d, stale) {
            if (!d) return;
            var me = (d.me && d.me.messages) || 0;
            var other = (d.other && d.other.messages) || 0;
            var total = d.total || (me + other);
            var mePct = total ? Math.round(me / total * 100) : 0;
            var herPct = total ? 100 - mePct : 0;

            countUp(ui.me, me);
            countUp(ui.other, other);
            if (ui.meSub) ui.meSub.textContent = mePct + '% сообщений';
            if (ui.otherSub) ui.otherSub.textContent = herPct + '% сообщений';
            if (ui.barMe) ui.barMe.style.width = mePct + '%';
            if (ui.barOther) ui.barOther.style.width = herPct + '%';
            if (ui.total) ui.total.textContent = spaced(total);
            if (ui.who) ui.who.textContent = (d.chat && d.chat.title ? 'Диалог с ' + d.chat.title : 'Наш диалог') + ' 💬';

            if (ui.verdict) {
                if (!total) ui.verdict.textContent = 'пока считаю…';
                else if (me === other) ui.verdict.textContent = 'ровно поровну — красиво! ⚖️';
                else if (me > other) ui.verdict.textContent = 'Пишу чаще я — на ' + spaced(me - other) + ' ' + plural(me - other, 'сообщение', 'сообщения', 'сообщений') + ' 💬';
                else ui.verdict.textContent = 'Ты пишешь чаще меня — на ' + spaced(other - me) + ' ' + plural(other - me, 'сообщение', 'сообщения', 'сообщений') + ' ❤️';
            }

            if (ui.days && d.first_message_at) {
                var days = Math.round((Date.now() - new Date(d.first_message_at).getTime()) / 86400000) + 1;
                ui.days.textContent = 'первое сообщение ' + days + ' ' + plural(days, 'день', 'дня', 'дней') + ' назад';
            }

            if (ui.when) {
                var when = timeAgo(d.updated_at);
                ui.when.textContent = d.status === 'syncing'
                    ? 'считаю историю…' + (d.progress && d.progress.processed ? ' (' + spaced(d.progress.processed) + ')' : '')
                    : (stale ? 'данные от ' + when : 'обновлено ' + when);
            }

            box.classList.remove('is-error');
            box.classList.toggle('is-stale', !!stale);
            try { localStorage.setItem('stats_cache', JSON.stringify({ t: Date.now(), d: d })); } catch (e) {}
        }

        function fail(msg) {
            box.classList.add('is-error');
            if (ui.when) ui.when.textContent = 'нет связи';
            if (ui.hint) ui.hint.textContent = msg + ' Проверить: ' + base + '/api/stats';
        }

        function restore() {
            try {
                var raw = localStorage.getItem('stats_cache');
                if (!raw) return;
                var c = JSON.parse(raw);
                if (c && c.d) { render(c.d, true); if (ui.when) ui.when.textContent = 'последние данные: ' + timeAgo(new Date(c.t).toISOString()); }
            } catch (e) {}
        }

        function load() {
            if (busy) return;
            busy = true;
            box.classList.add('is-stale');
            if (ui.when && !ui.when.textContent) ui.when.textContent = 'обновляю…';

            var ctrl = new AbortController();
            slowTimer = setTimeout(function () {
                if (ui.when) ui.when.textContent = 'сервер просыпается…';
                if (ui.hint) ui.hint.textContent = 'Бесплатный сервер спит после 15 минут простоя и просыпается до минуты. Подожди немного — цифры появятся сами.';
            }, 4000);

            fetch(base + '/api/stats', { signal: ctrl.signal, cache: 'no-store' })
                .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
                .then(function (d) { render(d, false); })
                .catch(function (e) {
                    if (e && e.name === 'AbortError') return;
                    fail('Цифры не пришли: ' + (e && e.message ? e.message : 'ошибка сети') + '.');
                })
                .finally(function () {
                    clearTimeout(slowTimer);
                    busy = false;
                });

            setTimeout(function () { if (busy) ctrl.abort(); }, 90000);   // ждём холодный старт
        }

        if (ui.refresh) ui.refresh.addEventListener('click', load);

        restore();
        load();

        setInterval(function () {
            if (document.visibilityState === 'visible') load();
        }, 45000);

        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'visible') load();
        });
    }

    /* ============================================================
       Кнопка от грусти
       ============================================================ */
    function mood() {
        var btn = document.getElementById('magicBtn');
        if (!btn) return;

        var textEl = document.getElementById('messageText');
        var badge = document.getElementById('phraseCount');
        var holder = document.getElementById('phrases');
        var phrases = [];
        try { phrases = JSON.parse(holder ? holder.textContent : '[]') || []; } catch (e) { phrases = []; }
        if (!phrases.length) return;

        var clicks = 0;
        try { clicks = parseInt(localStorage.getItem('mood_clicks') || '0', 10) || 0; } catch (e) {}
        if (badge) badge.textContent = 'нажатий: ' + clicks;

        var last = -1;

        function burst() {
            if (calm) return;
            var r = btn.getBoundingClientRect();
            var layer = document.createElement('div');
            layer.className = 'burst';
            var glyphs = ['❤', '💖', '✦', '🌸', '❥', '✨'];
            for (var i = 0; i < 14; i++) {
                var s = document.createElement('i');
                s.textContent = glyphs[i % glyphs.length];
                s.style.left = (r.left + r.width / 2) + 'px';
                s.style.top = (r.top + r.height / 2) + 'px';
                s.style.setProperty('--tx', (Math.random() * 320 - 160).toFixed(0) + 'px');
                s.style.setProperty('--ty', (-Math.random() * 300 - 60).toFixed(0) + 'px');
                s.style.animationDelay = (Math.random() * 0.18).toFixed(2) + 's';
                s.style.fontSize = (Math.random() * 12 + 14).toFixed(0) + 'px';
                layer.appendChild(s);
            }
            document.body.appendChild(layer);
            setTimeout(function () { layer.remove(); }, 2000);
        }

        btn.addEventListener('click', function () {
            burst();
            textEl.classList.add('is-out');

            setTimeout(function () {
                var i;
                do { i = Math.floor(Math.random() * phrases.length); }
                while (i === last && phrases.length > 1);
                last = i;
                textEl.textContent = phrases[i];

                clicks++;
                try { localStorage.setItem('mood_clicks', String(clicks)); } catch (e) {}
                if (badge) badge.textContent = 'нажатий: ' + clicks;

                textEl.classList.remove('is-out');
                textEl.classList.add('is-in');
            }, 260);
        });
    }

    function init() { hearts(); lightbox(); transitions(); stats(); mood(); }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
