from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import calendar
import json
import re

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from feedgen.feed import FeedGenerator


SOURCE_URL = "https://www.gigagen.com/"
NEWS_URL = "https://www.gigagen.com/#news"
OUTPUT_FILE = Path("docs/feed.xml")

GITHUB_RSS = (
    "https://raw.githubusercontent.com/"
    "plis2100/rss-gigagen/main/docs/feed.xml"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


def limpiar(texto):
    return " ".join((texto or "").split()).strip()


def descargar(url):
    respuesta = requests.get(
        url,
        headers=HEADERS,
        timeout=60,
        allow_redirects=True,
    )

    print(
        f"Descarga {url}: "
        f"HTTP {respuesta.status_code}"
    )

    respuesta.raise_for_status()
    return respuesta


def convertir_fecha(texto):
    if not texto:
        return None

    try:
        fecha = date_parser.parse(
            limpiar(texto),
            fuzzy=True,
        )

        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)

        return fecha

    except (ValueError, TypeError, OverflowError):
        return None


def fecha_desde_feedburner(elemento):
    fecha_estructurada = (
        elemento.get("published_parsed")
        or elemento.get("updated_parsed")
    )

    if not fecha_estructurada:
        return None

    segundos = calendar.timegm(fecha_estructurada)

    return datetime.fromtimestamp(
        segundos,
        tz=timezone.utc,
    )


def es_enlace_de_comunicado(titulo, enlace):
    titulo_minusculas = titulo.lower()
    dominio = urlparse(enlace).netloc.lower()

    dominios_permitidos = (
        "globenewswire.com",
        "grifols.com",
        "prnewswire.com",
    )

    return (
        titulo_minusculas.startswith("gigagen")
        and any(
            dominio.endswith(dominio_permitido)
            for dominio_permitido in dominios_permitidos
        )
    )


def obtener_datos_articulo(url):
    resultado = {
        "fecha": None,
        "descripcion": "",
    }

    try:
        respuesta = descargar(url)
        soup = BeautifulSoup(
            respuesta.text,
            "html.parser",
        )

        meta_descripcion = (
            soup.find(
                "meta",
                property="og:description",
            )
            or soup.find(
                "meta",
                attrs={"name": "description"},
            )
        )

        if meta_descripcion:
            resultado["descripcion"] = limpiar(
                meta_descripcion.get("content", "")
            )

        etiquetas_fecha = [
            soup.find(
                "meta",
                property="article:published_time",
            ),
            soup.find(
                "meta",
                attrs={"name": "date"},
            ),
            soup.find(
                "meta",
                attrs={"name": "publish-date"},
            ),
            soup.find(
                "meta",
                attrs={"name": "datePublished"},
            ),
        ]

        for etiqueta in etiquetas_fecha:
            if not etiqueta:
                continue

            fecha = convertir_fecha(
                etiqueta.get("content", "")
            )

            if fecha:
                resultado["fecha"] = fecha
                return resultado

        etiqueta_time = soup.find("time")

        if etiqueta_time:
            fecha = convertir_fecha(
                etiqueta_time.get("datetime")
                or etiqueta_time.get_text(" ", strip=True)
            )

            if fecha:
                resultado["fecha"] = fecha
                return resultado

        for script in soup.find_all(
            "script",
            type="application/ld+json",
        ):
            contenido_script = script.string

            if not contenido_script:
                continue

            try:
                contenido = json.loads(
                    contenido_script
                )
            except (json.JSONDecodeError, TypeError):
                continue

            elementos = (
                contenido
                if isinstance(contenido, list)
                else [contenido]
            )

            for elemento in elementos:
                if not isinstance(elemento, dict):
                    continue

                fecha = convertir_fecha(
                    elemento.get("datePublished")
                )

                if fecha:
                    resultado["fecha"] = fecha
                    return resultado

        texto_pagina = limpiar(
            soup.get_text(" ", strip=True)
        )

        coincidencia = re.search(
            r"\b(?:January|February|March|April|May|June|"
            r"July|August|September|October|November|December)"
            r"\s+\d{1,2},\s+20\d{2}\b",
            texto_pagina,
            flags=re.IGNORECASE,
        )

        if coincidencia:
            resultado["fecha"] = convertir_fecha(
                coincidencia.group(0)
            )

    except requests.RequestException as error:
        print(
            f"No se pudo ampliar {url}: {error}"
        )

    return resultado


def obtener_comunicados():
    respuesta = descargar(SOURCE_URL)
    soup = BeautifulSoup(
        respuesta.text,
        "html.parser",
    )

    comunicados = []
    enlaces_vistos = set()

    todos_los_enlaces = soup.find_all(
        "a",
        href=True,
    )

    print(
        f"Enlaces totales encontrados: "
        f"{len(todos_los_enlaces)}"
    )

    for enlace_html in todos_los_enlaces:
        titulo = limpiar(
            enlace_html.get_text(" ", strip=True)
        )

        enlace = limpiar(
            enlace_html.get("href", "")
        )

        if not es_enlace_de_comunicado(
            titulo,
            enlace,
        ):
            continue

        if enlace in enlaces_vistos:
            continue

        enlaces_vistos.add(enlace)

        print(f"Comunicado encontrado: {titulo}")

        datos = obtener_datos_articulo(enlace)

        comunicados.append({
            "titulo": titulo,
            "enlace": enlace,
            "fecha": datos["fecha"],
            "descripcion": datos["descripcion"],
        })

    if not comunicados:
        raise RuntimeError(
            "No se encontraron enlaces de comunicados de "
            "GigaGen publicados en Grifols, GlobeNewswire "
            "o PR Newswire. La RSS anterior no será eliminada."
        )

    fecha_antigua = datetime(
        1970,
        1,
        1,
        tzinfo=timezone.utc,
    )

    comunicados.sort(
        key=lambda comunicado: (
            comunicado["fecha"] or fecha_antigua
        ),
        reverse=True,
    )

    print(
        f"Comunicados actuales encontrados: "
        f"{len(comunicados)}"
    )

    return comunicados


def crear_rss(comunicados):
    feed = FeedGenerator()

    feed.id(GITHUB_RSS)
    feed.title("GigaGen – Current Press Releases")
    feed.description(
        "Current official press releases published by GigaGen"
    )
    feed.language("en-US")
    feed.lastBuildDate(datetime.now(timezone.utc))

    feed.link(
        href=NEWS_URL,
        rel="alternate",
    )

    feed.link(
        href=GITHUB_RSS,
        rel="self",
        type="application/rss+xml",
    )

    for comunicado in comunicados[:100]:
        entrada = feed.add_entry()

        entrada.id(comunicado["enlace"])
        entrada.title(comunicado["titulo"])
        entrada.link(href=comunicado["enlace"])

        entrada.description(
            comunicado["descripcion"]
            or (
                "Read the complete GigaGen press release: "
                f"{comunicado['titulo']}"
            )
        )

        if comunicado["fecha"]:
            entrada.pubDate(comunicado["fecha"])

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    feed.rss_file(
        str(OUTPUT_FILE),
        pretty=True,
        encoding="UTF-8",
    )

    if not OUTPUT_FILE.exists():
        raise RuntimeError(
            "No se pudo crear docs/feed.xml"
        )

    print(f"RSS creada correctamente: {OUTPUT_FILE}")
    print(f"Tamaño: {OUTPUT_FILE.stat().st_size} bytes")


def main():
    comunicados = obtener_comunicados()
    crear_rss(comunicados)


if __name__ == "__main__":
    main()
