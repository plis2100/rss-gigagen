from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator


PAGINA = "https://www.gigagen.com/"
ARCHIVO_RSS = Path("docs/feed.xml")

URL_RSS_PUBLICA = (
    "https://raw.githubusercontent.com/"
    "plis2100/rss-gigagen/main/docs/feed.xml"
)

DOMINIOS_PERMITIDOS = {
    "grifols.com",
    "www.grifols.com",
    "globenewswire.com",
    "www.globenewswire.com",
    "prnewswire.com",
    "www.prnewswire.com",
}


def cargar_fechas_anteriores():
    """
    Conserva las fechas de las noticias que ya estaban en el RSS.
    Así Feedly no considera que todas las noticias son nuevas cada hora.
    """
    fechas = {}

    if not ARCHIVO_RSS.exists():
        return fechas

    try:
        raiz = ET.parse(ARCHIVO_RSS).getroot()

        for item in raiz.findall("./channel/item"):
            enlace = item.findtext("link", "").strip()
            fecha = item.findtext("pubDate", "").strip()

            if enlace and fecha:
                try:
                    fechas[enlace] = parsedate_to_datetime(fecha)
                except (TypeError, ValueError):
                    pass
    except (ET.ParseError, OSError):
        pass

    return fechas


def descargar_pagina():
    cabeceras = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    respuesta = requests.get(
        PAGINA,
        headers=cabeceras,
        timeout=(10, 30),
    )
    respuesta.raise_for_status()

    return respuesta.text


def obtener_comunicados():
    html = descargar_pagina()
    sopa = BeautifulSoup(html, "html.parser")

    comunicados = []
    enlaces_vistos = set()

    for etiqueta in sopa.select("a[href]"):
        titulo = " ".join(etiqueta.get_text(" ", strip=True).split())
        enlace = urljoin(PAGINA, etiqueta.get("href", "").strip())

        if not titulo or not enlace:
            continue

        dominio = urlparse(enlace).netloc.lower()

        # Los comunicados de la sección Press Releases comienzan
        # normalmente por “GigaGen” y enlazan a Grifols o GlobeNewswire.
        if not titulo.lower().startswith("gigagen"):
            continue

        if dominio not in DOMINIOS_PERMITIDOS:
            continue

        if enlace in enlaces_vistos:
            continue

        enlaces_vistos.add(enlace)

        comunicados.append(
            {
                "titulo": titulo,
                "enlace": enlace,
                "descripcion": (
                    "Comunicado de prensa publicado por GigaGen. "
                    "Abre el enlace para consultar la noticia completa."
                ),
            }
        )

    if not comunicados:
        raise RuntimeError(
            "No se encontraron comunicados de GigaGen en la página principal."
        )

    return comunicados[:30]


def crear_rss(comunicados):
    fechas_anteriores = cargar_fechas_anteriores()
    fecha_actual = datetime.now(timezone.utc)

    generador = FeedGenerator()
    generador.id(PAGINA)
    generador.title("GigaGen - Press Releases")
    generador.link(href=PAGINA, rel="alternate")
    generador.link(href=URL_RSS_PUBLICA, rel="self")
    generador.description(
        "Últimos comunicados y noticias corporativas de GigaGen"
    )
    generador.language("en")
    generador.lastBuildDate(fecha_actual)

    # Se añaden en orden inverso porque FeedGen coloca primero
    # el último elemento incorporado.
    for comunicado in reversed(comunicados):
        enlace = comunicado["enlace"]

        fecha_publicacion = fechas_anteriores.get(
            enlace,
            fecha_actual,
        )

        entrada = generador.add_entry()
        entrada.id(enlace)
        entrada.guid(enlace, permalink=True)
        entrada.title(comunicado["titulo"])
        entrada.link(href=enlace)
        entrada.description(comunicado["descripcion"])
        entrada.pubDate(fecha_publicacion)

    ARCHIVO_RSS.parent.mkdir(parents=True, exist_ok=True)

    generador.rss_file(
        str(ARCHIVO_RSS),
        pretty=True,
    )

    if not ARCHIVO_RSS.exists() or ARCHIVO_RSS.stat().st_size < 200:
        raise RuntimeError("El archivo docs/feed.xml no se creó correctamente.")

    print(
        f"RSS creado correctamente con {len(comunicados)} comunicados: "
        f"{ARCHIVO_RSS}"
    )


def main():
    comunicados = obtener_comunicados()
    crear_rss(comunicados)


if __name__ == "__main__":
    main()
