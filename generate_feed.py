from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urldefrag, urlparse
import re
import time
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from playwright.sync_api import sync_playwright

PAGINA = 'https://www.gigagen.com/#news'
URL_BASE = 'https://www.gigagen.com/'
ARCHIVO_RSS = Path('docs/feed.xml')
URL_RSS_PUBLICA = 'https://raw.githubusercontent.com/plis2100/rss-gigagen/main/docs/feed.xml'
DOMINIOS_NOTICIAS = ('grifols.com', 'globenewswire.com', 'prnewswire.com')
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'


def limpiar_texto(texto):
    return ' '.join((texto or '').split()).strip()


def cargar_fechas_anteriores():
    fechas = {}
    if not ARCHIVO_RSS.exists():
        return fechas
    try:
        for item in ET.parse(ARCHIVO_RSS).getroot().findall('./channel/item'):
            enlace = limpiar_texto(item.findtext('link'))
            fecha = limpiar_texto(item.findtext('pubDate'))
            if enlace and fecha:
                try:
                    fechas[enlace] = parsedate_to_datetime(fecha)
                except (TypeError, ValueError, OverflowError):
                    pass
    except (ET.ParseError, OSError) as error:
        print(f'No se pudo leer el RSS anterior: {error}')
    return fechas


def extraer_enlaces(html, url_base):
    sopa = BeautifulSoup(html, 'html.parser')
    enlaces = []
    for etiqueta in sopa.select('a[href]'):
        titulo = limpiar_texto(etiqueta.get_text(' ', strip=True) or etiqueta.get('aria-label') or etiqueta.get('title'))
        enlace = urldefrag(urljoin(url_base, etiqueta.get('href', ''))).url
        enlaces.append({'titulo': titulo, 'enlace': enlace})
    return enlaces


def descargar_con_requests():
    # requests usa HTTP/1.1 normalmente, lo que evita el error HTTP/2 de Chromium.
    sesion = requests.Session()
    sesion.headers.update({'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xhtml+xml'})
    for intento in range(1, 4):
        try:
            respuesta = sesion.get(URL_BASE, timeout=35)
            respuesta.raise_for_status()
            print(f'Descarga HTTP correcta (intento {intento}).')
            return extraer_enlaces(respuesta.text, respuesta.url)
        except requests.RequestException as error:
            print(f'Fallo HTTP {intento}/3: {error}')
            if intento < 3:
                time.sleep(3 * intento)
    return []


def descargar_con_playwright():
    try:
        with sync_playwright() as playwright:
            navegador = playwright.chromium.launch(headless=True, args=['--disable-dev-shm-usage', '--no-sandbox', '--disable-http2'])
            try:
                pagina = navegador.new_page(user_agent=USER_AGENT, viewport={'width': 1440, 'height': 1200})
                for intento in range(1, 4):
                    try:
                        pagina.goto(URL_BASE, wait_until='domcontentloaded', timeout=45000)
                        pagina.wait_for_timeout(4000)
                        print(f'Página cargada con Playwright (intento {intento}).')
                        return extraer_enlaces(pagina.content(), pagina.url)
                    except Exception as error:
                        print(f'Fallo de Playwright {intento}/3: {error}')
                        if intento < 3:
                            time.sleep(3 * intento)
            finally:
                navegador.close()
    except Exception as error:
        print(f'No se pudo iniciar Playwright: {error}')
    return []


def filtrar_comunicados(enlaces):
    comunicados = []
    vistos = set()
    for elemento in enlaces:
        titulo = limpiar_texto(elemento.get('titulo'))
        enlace = limpiar_texto(elemento.get('enlace'))
        if not titulo or not enlace or 'gigagen' not in titulo.lower():
            continue
        host = (urlparse(enlace).hostname or '').lower()
        if not any(host == dominio or host.endswith('.' + dominio) for dominio in DOMINIOS_NOTICIAS):
            continue
        if enlace in vistos:
            continue
        vistos.add(enlace)
        comunicados.append({'titulo': titulo, 'enlace': enlace, 'descripcion': 'Comunicado de prensa o noticia corporativa de GigaGen.'})
    return comunicados[:40]


def obtener_comunicados():
    # Primero intentamos HTTP/1.1; si el sitio depende de JavaScript, usamos navegador.
    enlaces = descargar_con_requests()
    comunicados = filtrar_comunicados(enlaces)
    if not comunicados:
        print('No se encontraron comunicados en HTML; probando navegador...')
        comunicados = filtrar_comunicados(descargar_con_playwright())
    print(f'Se encontraron {len(comunicados)} comunicados.')
    for comunicado in comunicados:
        print(f"- {comunicado['titulo']}")
    return comunicados


def crear_rss(comunicados):
    fechas_anteriores = cargar_fechas_anteriores()
    ahora = datetime.now(timezone.utc)
    generador = FeedGenerator()
    generador.id(PAGINA)
    generador.title('GigaGen - Press Releases')
    generador.description('Últimos comunicados de prensa y noticias corporativas de GigaGen')
    generador.language('en')
    generador.link(href=PAGINA, rel='alternate')
    generador.link(href=URL_RSS_PUBLICA, rel='self')
    generador.lastBuildDate(ahora)
    for comunicado in reversed(comunicados):
        enlace = comunicado['enlace']
        fecha = fechas_anteriores.get(enlace, ahora)
        entrada = generador.add_entry()
        entrada.id(enlace)
        entrada.guid(enlace, permalink=True)
        entrada.title(comunicado['titulo'])
        entrada.link(href=enlace)
        entrada.description(comunicado['descripcion'])
        entrada.pubDate(fecha)
    ARCHIVO_RSS.parent.mkdir(parents=True, exist_ok=True)
    generador.rss_file(str(ARCHIVO_RSS), pretty=True)
    ET.parse(ARCHIVO_RSS)
    print(f'RSS creado correctamente: {ARCHIVO_RSS}')


def main():
    comunicados = obtener_comunicados()
    if not comunicados:
        if ARCHIVO_RSS.exists() and ARCHIVO_RSS.stat().st_size > 200:
            try:
                ET.parse(ARCHIVO_RSS)
                print('AVISO: No hay noticias recuperadas. Se conserva el RSS anterior sin cambios.')
                return
            except ET.ParseError:
                pass
        raise RuntimeError('No se encontraron comunicados y no existe un RSS anterior válido. No se generará un feed vacío.')
    crear_rss(comunicados)


if __name__ == '__main__':
    main()

