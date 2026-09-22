#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Собирает одностраничную версию сайта: все 6 разделов в одном HTML-файле,
CSS и JS внутри, фотографии — data-URI. Результат: love_site_one_file.html
"""
import base64, io, os, re, sys
from PIL import Image, ImageOps

SRC = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SRC, 'love_site_one_file.html')

PAGES = ['index.html', 'page2.html', 'page3.html', 'page5.html', 'page6.html', 'page4.html']
MAP = {'index.html': '#p1', 'page2.html': '#p2', 'page3.html': '#p3',
       'page5.html': '#p4', 'page6.html': '#p5', 'page4.html': '#p6'}
STEP_LABELS = ['Подарки', 'Укусы', 'Глаза', 'Статистика', 'Кнопка', 'Письмо']
MAX_SIDE, QUALITY = 1100, 78        # фото для одностраничной версии


def data_uri(path):
    """Сжатая картинка → data:image/jpeg;base64,..."""
    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert('RGB')
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=QUALITY, optimize=True, progressive=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def build():
    css = open(os.path.join(SRC, 'styles.css'), encoding='utf-8').read()
    js = open(os.path.join(SRC, 'script.js'), encoding='utf-8').read()

    cache, sections = {}, []
    for i, page in enumerate(PAGES, 1):
        html = open(os.path.join(SRC, page), encoding='utf-8').read()
        body = re.search(r'<main class="card">(.*?)</main>', html, re.S).group(1)

        # внутренние ссылки → якоря разделов
        for target, anchor in MAP.items():
            body = body.replace('href="%s"' % target, 'href="%s"' % anchor)

        # <img src="img/x.jpg" data-full="img/large/x.jpg"> → одна картинка внутри файла
        def swap(m):
            big = m.group('full') or m.group('src')
            if big not in cache:
                cache[big] = data_uri(os.path.join(SRC, big))
            return m.group(0) \
                .replace(m.group('src'), cache[big]) \
                .replace(' data-full="%s"' % m.group('full'), '') if m.group('full') else \
                m.group(0).replace(m.group('src'), cache[big])

        body = re.sub(
            r'<img\s+src="(?P<src>img/[^"]+)"(?:\s+data-full="(?P<full>img/[^"]+)")?',
            swap, body)

        aria = ' aria-current="page"' if i == 1 else ''
        sections.append(
            '        <section class="page%s" id="p%d" aria-label="%s">\n'
            '            <div class="card">%s</div>\n'
            '        </section>' % (' is-active' if i == 1 else '', i, STEP_LABELS[i - 1], body))

    steps = '\n'.join(
        '        <a class="step%s" href="#p%d"%s><b>%d</b><span>%s</span></a>' % (
            ' is-active' if i == 1 else '', i, ' aria-current="page"' if i == 1 else '', i, label)
        for i, label in enumerate(STEP_LABELS, 1))

    spa = """
    /* ---------- одностраничный режим: переключение разделов ---------- */
    (function () {
        var sections = [].slice.call(document.querySelectorAll('.page'));
        var steps = [].slice.call(document.querySelectorAll('.steps .step'));
        if (!sections.length) return;

        function indexOf(id) {
            for (var i = 0; i < sections.length; i++) if (sections[i].id === id) return i;
            return -1;
        }

        function paint(i) {
            steps.forEach(function (s, n) {
                s.classList.toggle('is-active', n === i);
                s.classList.toggle('is-done', n < i);
                if (n === i) s.setAttribute('aria-current', 'page'); else s.removeAttribute('aria-current');
            });
            document.title = sections[i].querySelector('h1').textContent.trim() + ' ❤️';
        }

        function show(id, instant) {
            var i = indexOf(id);
            if (i < 0) return false;
            var current = document.querySelector('.page.is-active');
            if (current === sections[i]) return true;
            var swap = function () {
                if (current) current.classList.remove('is-active');
                sections[i].classList.add('is-active');
                document.body.classList.remove('is-leaving');
                paint(i);
                window.scrollTo({ top: 0, behavior: instant ? 'auto' : 'smooth' });
            };
            if (instant || current === null) swap();
            else {
                document.body.classList.add('is-leaving');
                setTimeout(swap, 240);
            }
            return true;
        }

        window.__spaGo = function (hash) {
            var id = hash.replace('#', '');
            if (!show(id)) return;
            if (history.replaceState) history.replaceState(null, '', '#' + id);
        };

        window.addEventListener('hashchange', function () { show(location.hash.replace('#', '')); });

        var start = location.hash && indexOf(location.hash.replace('#', '')) > -1 ? location.hash : '#p1';
        show(start.replace('#', ''), true);
    })();
"""

    doc = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#07050d">
<title>Для тебя ❤️</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%E2%9D%A4%EF%B8%8F%3C/text%3E%3C/svg%3E">
<style>
@@CSS@@

/* ---- только для одностраничной сборки ---- */
.deck { width: 100%; max-width: 760px; }
.page { display: none; }
.page.is-active { display: block; }
.page .card { width: 100%; }
</style>
</head>
<body>

<div class="bg" aria-hidden="true"><span></span><span></span><span></span><span></span></div>

<nav class="steps" aria-label="Разделы">
@@STEPS@@
</nav>

<div class="deck">
@@SECTIONS@@
</div>

<script>
@@JS@@
@@SPA@@
</script>
</body>
</html>
"""

    doc = (doc.replace('@@CSS@@', css)
              .replace('@@STEPS@@', steps)
              .replace('@@SECTIONS@@', '\n'.join(sections))
              .replace('@@JS@@', js)
              .replace('@@SPA@@', spa))

    open(OUT, 'w', encoding='utf-8').write(doc)
    size = os.path.getsize(OUT)
    print('готово: %s  (%.1f МБ, встроено фото: %d)' % (os.path.basename(OUT), size / 1024 / 1024, len(cache)))
    return OUT


if __name__ == '__main__':
    build()
