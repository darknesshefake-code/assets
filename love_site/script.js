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
        var base = String(fromQuery || saved || window.STATS_API || STATS_API_DEFAULT).replace(/\/+$/, '');
        // авто-подмена для превью в E2B (когда сайт открыт как 8000-xxx.e2b.app, а api на 8010-xxx)
        if (!fromQuery && !saved && location.hostname.indexOf('e2b.app') !== -1 && base.indexOf('render.com') !== -1) {
            try {
                if (location.hostname.indexOf('8000-') === 0) {
                    var cand = location.protocol + '//' + location.hostname.replace(/^8000-/, '8010-');
                    // быстрый probe не делаем — просто берём как приоритетный кандидат, фетч сам упадёт если не туда и вернётся на render
                    // но чтобы не ломать прод — оставим base как был, а fallback сделаем в fetchSeries
                    // поэтому тут ничего не меняем, логика fallback внизу
                }
            } catch(e){}
        }
        return base;
    }

    function previewApiBase() {
        try {
            if (location.hostname.indexOf('e2b.app') !== -1 && location.hostname.indexOf('8000-') === 0) {
                return (location.protocol + '//' + location.hostname.replace(/^8000-/, '8010-')).replace(/\/+$/, '');
            }
        } catch(e){}
        return null;
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

            var previewBase = previewApiBase();
            function tryStats(fetchBase){
                return fetch(fetchBase + '/api/stats', { signal: ctrl.signal, cache: 'no-store' })
                    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
            }
            tryStats(base)
                .then(function (d) { render(d, false); })
                .catch(function (e) {
                    if (e && e.name === 'AbortError') throw e;
                    if (previewBase && previewBase !== base) {
                        return tryStats(previewBase).then(function(d){ render(d, false); });
                    }
                    throw e;
                })
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
       График просадок — динамика по дням
       ============================================================ */
    function talkDynamics() {
        var section = document.getElementById('chartSection');
        if (!section) return;

        var canvas = document.getElementById('talkChart');
        var tip = document.getElementById('chartTip');
        var empty = document.getElementById('chartEmpty');
        var statusEl = document.getElementById('chartStatus');
        var heat = document.getElementById('heatmap');
        var dipsWrap = document.getElementById('dipsWrap');
        var dipsList = document.getElementById('dipsList');
        var dipsCount = document.getElementById('dipsCount');
        var peaksWrap = document.getElementById('peaksWrap');
        var peaksList = document.getElementById('peaksList');
        var metaAvg = document.getElementById('metaAvg');
        var metaPeak = document.getElementById('metaPeak');
        var metaPeakSub = document.getElementById('metaPeakSub');
        var metaLow = document.getElementById('metaLow');
        var metaLowSub = document.getElementById('metaLowSub');
        var footnote = document.getElementById('chartFootnote');

        var base = apiBase();
        var currentDays = 30;
        var currentData = null;
        var hoverIndex = -1;
        var busy = false;

        function formatDate(iso) {
            try {
                var d = new Date(iso + 'T12:00:00');
                return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
            } catch(e) { return iso; }
        }
        function formatLong(iso) {
            try {
                var d = new Date(iso + 'T12:00:00');
                return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', weekday: 'short' });
            } catch(e) { return iso; }
        }

        function niceMax(v) {
            if (v <= 10) return 10;
            if (v <= 20) return 20;
            if (v <= 50) return Math.ceil(v/10)*10;
            if (v <= 100) return Math.ceil(v/20)*20;
            return Math.ceil(v/25)*25;
        }

        function levelClass(total, max) {
            if (total === 0) return '';
            var r = total / Math.max(1, max);
            if (r < 0.25) return 'heat--1';
            if (r < 0.5) return 'heat--2';
            if (r < 0.78) return 'heat--3';
            return 'heat--4';
        }

        function fetchSeries(days) {
            if (busy) return;
            busy = true;
            currentDays = days;
            if (statusEl) statusEl.textContent = 'загружаю…';
            if (empty) empty.hidden = true;
            // подсвечиваем активную кнопку
            section.querySelectorAll('.period').forEach(function(b){
                var isActive = String(b.dataset.days) === String(days);
                b.classList.toggle('is-active', isActive);
                b.setAttribute('aria-selected', isActive ? 'true' : 'false');
            });

            var url = base + '/api/series?days=' + encodeURIComponent(days);
            var previewBase = previewApiBase();
            var triedPreview = false;
            var ctrl = new AbortController();
            var slow = setTimeout(function(){
                if (statusEl) statusEl.textContent = 'сервер просыпается…';
            }, 3500);

            function doFetch(fetchBase) {
                var u = fetchBase + '/api/series?days=' + encodeURIComponent(days);
                return fetch(u, { signal: ctrl.signal, cache: 'no-store' })
                    .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
                    .then(function(data){
                        if ((!data.series || !data.series.length) && !data.is_demo) {
                            return fetch(fetchBase + '/api/series?days='+days+'&demo=1', {cache:'no-store'})
                                .then(function(r2){ return r2.json(); })
                                .then(function(demo){ demo._emptyReal = true; return demo; });
                        }
                        return data;
                    });
            }

            function handleData(data){
                currentData = data;
                render(data);
                if (statusEl) {
                    var upd = data.updated_at ? timeAgo(data.updated_at) : '';
                    var note = data.is_demo ? 'демо · ' : '';
                    statusEl.textContent = note + (upd ? 'обновлено ' + upd : (data._emptyReal ? 'пока нет реальных данных — показано как будет' : 'готово'));
                }
                try { localStorage.setItem('series_cache_' + days, JSON.stringify({t:Date.now(), d:data})); } catch(e){}
            }

            doFetch(base)
                .then(handleData)
                .catch(function(e){
                    if (e && e.name === 'AbortError') throw e;
                    // пробуем preview api если мы на e2b и base был render
                    if (!triedPreview && previewBase && previewBase !== base) {
                        triedPreview = true;
                        if (statusEl) statusEl.textContent = 'пробую локальный api…';
                        return doFetch(previewBase).then(handleData);
                    }
                    throw e;
                })
                .catch(function(e){
                    if (e && e.name === 'AbortError') return;
                    // пробуем кэш
                    try {
                        var raw = localStorage.getItem('series_cache_' + days);
                        if (raw) {
                            var c = JSON.parse(raw);
                            if (c && c.d) { render(c.d); if(statusEl) statusEl.textContent = 'кэш · нет связи'; return; }
                        }
                    } catch(err){}
                    if (statusEl) statusEl.textContent = 'нет связи — проверь api: ' + base + '/api/series';
                    if (empty) empty.hidden = false;
                    console.warn('series fail', e);
                })
                .finally(function(){ clearTimeout(slow); busy=false; });

            setTimeout(function(){ if(busy) ctrl.abort(); }, 90000);
        }

        function render(data) {
            if (!data || !data.series) return;
            var series = data.series;
            var moving = data.moving_avg_7 || [];
            var max = data.max || 0;

            if (!series.length) {
                if (empty) empty.hidden = false;
                canvas.style.opacity = '0.25';
                return;
            }
            if (empty) empty.hidden = true;
            canvas.style.opacity = '1';

            // метрики
            if (metaAvg) metaAvg.textContent = (data.average_per_day != null ? data.average_per_day : '—') + (data.average_per_day ? ' / день' : '');
            // пик
            if (metaPeak && data.peaks && data.peaks.length) {
                var p = data.peaks[0];
                metaPeak.textContent = formatDate(p.date) + ' · ' + spaced(p.total);
                if (metaPeakSub) metaPeakSub.textContent = spaced(p.me) + ' я · ' + spaced(p.other) + ' ты';
            } else if (metaPeak) { metaPeak.textContent = '—'; if(metaPeakSub) metaPeakSub.textContent=''; }

            // самое тихо — минимум >0? или минимум вообще
            if (metaLow) {
                var sorted = series.slice().sort(function(a,b){ return a.total-b.total; });
                var low = sorted[0];
                if (low) {
                    metaLow.textContent = formatDate(low.date) + ' · ' + spaced(low.total);
                    if (metaLowSub) {
                        if (low.total===0) metaLowSub.textContent = 'тишина — проверь, что было в этот день';
                        else metaLowSub.textContent = 'на ' + spaced(Math.round((data.average_active_day||data.average_per_day)-low.total)) + ' меньше среднего';
                    }
                }
            }

            drawCanvas(series, moving, data);
            drawHeatmap(series, max, data.dips || []);
            drawDips(data.dips || [], data);
            drawPeaks(data.peaks || [], max);
            if (footnote) {
                var f = '';
                if (data.is_demo) f = 'Показаны демо-данные — так будет выглядеть график, когда сервер получит историю Telegram. Реальные цифры появятся после первой синхронизации.';
                else if (data.dips && data.dips.length) f = 'Просадки — не приговор. Это просто места, где диалогу нужно было чуть больше тепла. Посмотри даты ниже и вспомни, что там было.';
                else if (series.length) f = 'За выбранный период просадок не нашлось — вы держали связь ровно, без провалов. Так держать ❤️';
                footnote.textContent = f;
            }
        }

        function drawCanvas(series, moving, data) {
            var ctx = canvas.getContext('2d');
            if (!ctx) return;
            var dpr = window.devicePixelRatio || 1;
            var rect = canvas.getBoundingClientRect();
            var W = Math.max(300, Math.round(rect.width * dpr));
            var H = Math.round(340 * dpr);
            if (canvas.width !== W || canvas.height !== H) {
                canvas.width = W; canvas.height = H;
            }
            // стиль в пикселях ретины
            var padL = Math.round(36 * dpr);
            var padR = Math.round(14 * dpr);
            var padT = Math.round(16 * dpr);
            var padB = Math.round(28 * dpr);
            var plotW = W - padL - padR;
            var plotH = H - padT - padB;

            ctx.clearRect(0,0,W,H);

            var n = series.length;
            if (n === 0) return;
            var max = niceMax(data.max || 0);
            if (max === 0) max = 10;
            // если максимум маленький — делаем сетку 0-10
            var yFor = function(v){ return padT + plotH - (v / max) * plotH; };
            var xFor = function(i){ return n===1 ? padL+plotW/2 : padL + (i/(n-1))*plotW; };

            // фон сетки
            ctx.strokeStyle = 'rgba(255,255,255,.06)';
            ctx.lineWidth = 1 * dpr;
            var ticks = 4;
            for (var t=0; t<=ticks; t++){
                var y = padT + (t/ticks)*plotH;
                ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W-padR, y); ctx.stroke();
                // подписи Y
                var val = Math.round(max - (t/ticks)*max);
                ctx.fillStyle = 'rgba(255,255,255,.32)';
                ctx.font = (11*dpr)+'px \"Segoe UI\", sans-serif';
                ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
                ctx.fillText(String(val), padL - 8*dpr, y);
            }
            // вертикальные редкие линии
            ctx.strokeStyle = 'rgba(255,255,255,.03)';
            var vStep = n > 90 ? Math.ceil(n/6) : (n > 30 ? Math.ceil(n/8) : 6);
            for (var i=0;i<n;i+=vStep){
                var x = xFor(i);
                ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT+plotH); ctx.stroke();
            }

            // заливка total area
            var grad = ctx.createLinearGradient(0, padT, 0, padT+plotH);
            grad.addColorStop(0, 'rgba(255,61,129,.34)');
            grad.addColorStop(0.55, 'rgba(160,107,255,.16)');
            grad.addColorStop(1, 'rgba(94,231,255,.04)');
            ctx.fillStyle = grad;
            ctx.beginPath();
            for (var i=0;i<n;i++){
                var x = xFor(i), y = yFor(series[i].total);
                if (i===0) { ctx.moveTo(x, y); }
                else ctx.lineTo(x, y);
            }
            // вниз к базе и обратно
            ctx.lineTo(xFor(n-1), padT+plotH);
            ctx.lineTo(xFor(0), padT+plotH);
            ctx.closePath();
            ctx.fill();

            // тонкая линия всего
            ctx.strokeStyle = 'rgba(255,61,129,.95)';
            ctx.lineWidth = 2.2 * dpr;
            ctx.lineJoin = 'round'; ctx.lineCap = 'round';
            ctx.beginPath();
            for (var i=0;i<n;i++){
                var x = xFor(i), y = yFor(series[i].total);
                if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
            }
            ctx.stroke();
            // свечение линии всего
            ctx.strokeStyle = 'rgba(255,61,129,.18)';
            ctx.lineWidth = 8 * dpr;
            ctx.stroke();

            // линия Я (cyan)
            ctx.strokeStyle = 'rgba(94,231,255,.95)';
            ctx.lineWidth = 1.4 * dpr;
            ctx.setLineDash([]);
            ctx.beginPath();
            for (var i=0;i<n;i++){
                var x = xFor(i), y = yFor(series[i].me);
                if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
            }
            ctx.stroke();
            // линия Ты (pink soft)
            ctx.strokeStyle = 'rgba(255,138,182,.95)';
            ctx.lineWidth = 1.4 * dpr;
            ctx.beginPath();
            for (var i=0;i<n;i++){
                var x = xFor(i), y = yFor(series[i].other);
                if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
            }
            ctx.stroke();

            // среднее 7 дней — белая пунктирная
            if (moving && moving.length===n){
                ctx.strokeStyle = 'rgba(255,255,255,.62)';
                ctx.lineWidth = 1.1 * dpr;
                ctx.setLineDash([6*dpr, 6*dpr]);
                ctx.beginPath();
                for (var i=0;i<n;i++){
                    var x = xFor(i), y = yFor(moving[i].avg);
                    if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
                }
                ctx.stroke();
                ctx.setLineDash([]);
            }

            // точки просадок
            var dips = data.dips || [];
            var dipSet = {};
            dips.forEach(function(d){ dipSet[d.date]=d; });
            for (var i=0;i<n;i++){
                var pt = series[i];
                if (dipSet[pt.date]) {
                    var x = xFor(i), y = yFor(pt.total);
                    // внешний ореол
                    ctx.fillStyle = 'rgba(255,59,59,.18)';
                    ctx.beginPath(); ctx.arc(x,y, 9*dpr, 0, Math.PI*2); ctx.fill();
                    // белая обводка
                    ctx.fillStyle = '#fff';
                    ctx.beginPath(); ctx.arc(x,y, 4.2*dpr, 0, Math.PI*2); ctx.fill();
                    // красная середина
                    ctx.fillStyle = '#ff3b3b';
                    ctx.beginPath(); ctx.arc(x,y, 2.8*dpr, 0, Math.PI*2); ctx.fill();
                }
            }

            // ховер-индикатор
            if (hoverIndex >=0 && hoverIndex < n){
                var hx = xFor(hoverIndex), hy = yFor(series[hoverIndex].total);
                ctx.strokeStyle = 'rgba(255,255,255,.16)';
                ctx.lineWidth = 1 * dpr;
                ctx.setLineDash([4*dpr,4*dpr]);
                ctx.beginPath(); ctx.moveTo(hx, padT); ctx.lineTo(hx, padT+plotH); ctx.stroke();
                ctx.setLineDash([]);
                ctx.fillStyle = 'rgba(18,12,30,.96)';
                ctx.strokeStyle = 'rgba(255,61,129,.5)';
                ctx.lineWidth = 1.2*dpr;
                ctx.beginPath(); ctx.arc(hx, hy, 5*dpr, 0, Math.PI*2); ctx.fill(); ctx.stroke();
                ctx.fillStyle = '#fff';
                ctx.beginPath(); ctx.arc(hx, hy, 2.2*dpr, 0, Math.PI*2); ctx.fill();
            }

            // подписи X (разреженно)
            ctx.fillStyle = 'rgba(255,255,255,.36)';
            ctx.font = (10*dpr)+'px \"Segoe UI\", sans-serif';
            ctx.textAlign = 'center'; ctx.textBaseline = 'top';
            var labelStep;
            if (n <= 18) labelStep = 2;
            else if (n <= 40) labelStep = 5;
            else if (n <= 90) labelStep = 14;
            else if (n <= 180) labelStep = 30;
            else labelStep = 45;
            for (var i=0;i<n;i+=labelStep){
                var x = xFor(i);
                var lab = formatDate(series[i].date);
                ctx.fillText(lab, x, padT+plotH+6*dpr);
            }
            // крайняя правая подпись тоже покажем если не попадает в шаг
            if ((n-1) % labelStep !== 0){
                var x = xFor(n-1);
                ctx.fillText(formatDate(series[n-1].date), x, padT+plotH+6*dpr);
            }

            // сохраняем для ховера
            canvas._plot = { padL:padL, padR:padR, padT:padT, padB:padB, W:W, H:H, plotW:plotW, plotH:plotH, n:n, xFor:xFor, yFor:yFor, max:max, series:series, moving:moving };
        }

        function drawHeatmap(series, max, dips) {
            if (!heat) return;
            heat.innerHTML = '';
            var dipSet = {};
            (dips||[]).forEach(function(d){ dipSet[d.date]=1; });
            series.forEach(function(pt){
                var div = document.createElement('div');
                div.className = 'heat ' + levelClass(pt.total, max);
                if (dipSet[pt.date]) div.classList.add('heat--dip');
                var tipText = formatLong(pt.date) + ' — ' + pt.total + ' ' + plural(pt.total,'сообщение','сообщения','сообщений') + ' ('+pt.me+' я · '+pt.other+' ты)';
                if (dipSet[pt.date]) tipText += ' · просадка';
                div.setAttribute('data-tip', tipText);
                div.addEventListener('click', function(){ highlightDate(pt.date); });
                heat.appendChild(div);
            });
            // прокрутка в конец (к сегодняшнему дню)
            heat.scrollLeft = heat.scrollWidth;
        }

        function drawDips(dips, data) {
            if (!dipsWrap || !dipsList) return;
            if (!dips || !dips.length) { dipsWrap.hidden = true; return; }
            dipsWrap.hidden = false;
            if (dipsCount) dipsCount.textContent = '· ' + dips.length + ' ' + plural(dips.length,'день','дня','дней');
            // сортировка по severity убыв
            var sorted = dips.slice().sort(function(a,b){ return b.severity - a.severity; });
            dipsList.innerHTML = '';
            sorted.forEach(function(d){
                var li = document.createElement('li');
                li.className = 'dip' + (d.severity >= 0.7 ? ' dip--severe' : '');
                var dateLabel = formatLong(d.date);
                var hint = d.total===0
                    ? 'тишина — сообщений не было. Вспомни, что было в этот день: занятость, ссора, усталость?'
                    : 'всего ' + d.total + ', обычно ~' + Math.round(d.ref_avg) + ' · просадка на ' + d.diff + plural(d.diff,' сообщение',' сообщения',' сообщений');
                li.innerHTML =
                    '<span>' +
                    '<span class="dip__date">'+ dateLabel +'</span>' +
                    '<span class="dip__meta">'+ hint +'<br><small style="color:rgba(255,255,255,.38)">'+ d.me+' я · '+d.other+' ты</small></span>' +
                    '</span>' +
                    '<span class="dip__badge">'+ (d.total===0 ? '0' : d.total) +' · '+ (d.severity>=0.7?'сильно':'заметно') +'</span>';
                li.addEventListener('click', function(){ highlightDate(d.date); });
                dipsList.appendChild(li);
            });
        }

        function drawPeaks(peaks, max) {
            if (!peaksWrap || !peaksList) return;
            if (!peaks || !peaks.length) { peaksWrap.hidden = true; return; }
            peaksWrap.hidden = false;
            peaksList.innerHTML = '';
            peaks.forEach(function(p){
                var li = document.createElement('li');
                li.className = 'peak';
                var w = max ? Math.max(8, Math.min(100, (p.total/max)*100)) : 0;
                li.innerHTML =
                    '<span class="peak__date">'+ formatLong(p.date) +'</span>' +
                    '<span class="peak__bar"><i style="width:'+ w +'%"></i></span>' +
                    '<span class="dip__badge" style="background:rgba(160,107,255,.12); border-color:rgba(160,107,255,.22); color:#d9c2ff">'+ p.total +' · пик</span>';
                li.addEventListener('click', function(){ highlightDate(p.date); });
                peaksList.appendChild(li);
            });
        }

        function highlightDate(dateStr) {
            if (!currentData || !currentData.series) return;
            var idx = -1;
            for (var i=0;i<currentData.series.length;i++) if (currentData.series[i].date===dateStr) { idx=i; break; }
            if (idx<0) return;
            hoverIndex = idx;
            drawCanvas(currentData.series, currentData.moving_avg_7, currentData);
            showTip(idx);
            // подсветка на пару секунд
            setTimeout(function(){
                // не сбрасываем если мышь всё ещё над графиком
            }, 2600);
            // прокрутка к графику на мобилке
            try { canvas.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch(e){}
        }

        function showTip(idx) {
            if (!currentData || idx<0 || !tip || !canvas) return;
            var pt = currentData.series[idx];
            var mv = currentData.moving_avg_7 && currentData.moving_avg_7[idx];
            var plot = canvas._plot;
            if (!plot) return;
            var x = plot.xFor(idx);
            var rect = canvas.getBoundingClientRect();
            var card = document.getElementById('chartCard');
            var cardRect = card.getBoundingClientRect();
            var tipX = rect.left - cardRect.left + x * (rect.width / plot.W);
            var tipY = rect.top - cardRect.top + plot.yFor(pt.total) * (rect.height / plot.H);
            tip.hidden = false;
            tip.classList.remove('chart-tip--below');
            tip.innerHTML = '<b>'+ formatLong(pt.date) +'</b> — ' + pt.total + ' ' + plural(pt.total,'сообщение','сообщения','сообщений') +
                '<br>я: ' + pt.me + ' · ты: ' + pt.other +
                (mv ? '<small>среднее 7д: ' + mv.avg + ' · обычно ' + Math.round(currentData.average_active_day||currentData.average_per_day) + '</small>' : '') +
                ( (currentData.dips||[]).find(function(d){ return d.date===pt.date; }) ? '<small style="color:#ff8a8a">⚠️ просадка — посмотри, что было в этот день</small>' : '');
            // сначала ставим, потом измеряем и клампим
            tip.style.left = tipX + 'px';
            tip.style.top = (tipY - 8) + 'px';
            tip.style.transform = 'translate(-50%, -110%)';
            // ждём layout
            var tipW = tip.offsetWidth, tipH = tip.offsetHeight;
            var cardW = cardRect.width, cardH = cardRect.height;
            // горизонтальный кламп: не выходить за края карты
            var minX = tipW/2 + 8, maxX = cardW - tipW/2 - 8;
            if (tipX < minX) tipX = minX;
            if (tipX > maxX) tipX = maxX;
            // вертикальный: если сверху не влезает (высокий скачок), показываем снизу
            var needBelow = false;
            // tip сейчас позиционирован выше точки на 110% (tipH + 12 примерно)
            // проверим, влезает ли верх
            var topEdge = tipY - tipH - 14; // 14 = отступ + стрелка
            if (topEdge < 8) needBelow = true;
            if (needBelow) {
                tip.classList.add('chart-tip--below');
                tip.style.transform = 'translate(-50%, 16px)';
            } else {
                tip.classList.remove('chart-tip--below');
                tip.style.transform = 'translate(-50%, -110%)';
            }
            tip.style.left = tipX + 'px';
            tip.style.top = tipY + 'px'; // базовый Y — центр точки, трансформ уже смещает
            // если снизу тоже не влезает (очень низкий), просто оставим выше
        }
        function hideTip(){ if(tip) { tip.hidden = true; tip.classList.remove('chart-tip--below'); } hoverIndex=-1; if(currentData) drawCanvas(currentData.series, currentData.moving_avg_7, currentData); }

        // интерактив canvas
        if (canvas) {
            canvas.addEventListener('mousemove', function(e){
                if (!currentData || !canvas._plot) return;
                var rect = canvas.getBoundingClientRect();
                var plot = canvas._plot;
                var x = (e.clientX - rect.left) / rect.width * plot.W;
                var rel = (x - plot.padL) / plot.plotW;
                var idx = Math.round(rel * (plot.n - 1));
                if (idx <0) idx=0; if(idx>=plot.n) idx=plot.n-1;
                if (idx !== hoverIndex) {
                    hoverIndex = idx;
                    drawCanvas(currentData.series, currentData.moving_avg_7, currentData);
                    showTip(idx);
                }
            });
            canvas.addEventListener('mouseleave', hideTip);
            canvas.addEventListener('click', function(e){
                if (!currentData || hoverIndex<0) return;
                showTip(hoverIndex);
            });
            // тач
            canvas.addEventListener('touchstart', function(e){
                var t = e.touches[0];
                var rect = canvas.getBoundingClientRect();
                var plot = canvas._plot;
                if (!plot) return;
                var x = (t.clientX - rect.left) / rect.width * plot.W;
                var rel = (x - plot.padL) / plot.plotW;
                var idx = Math.round(rel * (plot.n - 1));
                if (idx<0) idx=0; if(idx>=plot.n) idx=plot.n-1;
                hoverIndex = idx;
                drawCanvas(currentData.series, currentData.moving_avg_7, currentData);
                showTip(idx);
            }, {passive:true});
        }

        // периоды
        section.querySelectorAll('.period').forEach(function(btn){
            btn.addEventListener('click', function(){
                var days = parseInt(btn.dataset.days,10) || 0;
                fetchSeries(days);
            });
        });

        // ресайз
        var ro = null;
        try {
            ro = new ResizeObserver(function(){ if(currentData) drawCanvas(currentData.series, currentData.moving_avg_7, currentData); });
            ro.observe(canvas);
        } catch(e){
            window.addEventListener('resize', function(){ if(currentData) drawCanvas(currentData.series, currentData.moving_avg_7, currentData); });
        }

        // первый заход: пробуем из кэша сначала мгновенно, потом сеть
        try {
            var cached = localStorage.getItem('series_cache_30');
            if (cached) {
                var c = JSON.parse(cached);
                if (c && c.d && c.d.series) { currentData = c.d; render(c.d); if(statusEl) statusEl.textContent = 'кэш · обновляю…'; }
            }
        } catch(e){}
        fetchSeries(30);
        // также обновляем при возврате на вкладку
        document.addEventListener('visibilitychange', function(){
            if (document.visibilityState === 'visible') fetchSeries(currentDays);
        });
        // синхронизируем обновление со статистикой — по кнопке обновить
        var refreshBtn = document.getElementById('statsRefresh');
        if (refreshBtn) refreshBtn.addEventListener('click', function(){ fetchSeries(currentDays); });
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

    function init() { hearts(); lightbox(); transitions(); stats(); talkDynamics(); mood(); }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
