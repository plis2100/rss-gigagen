from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
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
    "Accept-Language": "en-US,en;q=0.9",
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


def obtener_datos_articulo(url):
    datos = {
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
            soup.find("meta", property="og:description")
            or soup.find("meta", attrs={"name": "description"})
        )

        if meta_descripcion:
            datos["descripcion"] = limpiar(
                meta_descripcion.get("content", "")
            )

        posibles_meta_fecha = [
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
        ]

        for etiqueta in posibles_meta_fecha:
            if not etiqueta:
                continue

            fecha = convertir_fecha(
                etiqueta.get("content", "")
            )

            if fecha:
                datos["fecha"] = fecha
                return datos

        etiqueta_time = soup.find("time")

        if etiqueta_time:
            fecha = convertir_fecha(
                etiqueta_time.get("datetime")
                or etiqueta_time.get_text(" ", strip=True)
            )

            if fecha:
                datos["fecha"] = fecha
                return datos

        for script in soup.find_all(
            "script",
            type="application/ld+json",
        ):
            try:
                contenido = json.loads(
                    script.string or "{}"
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
                    datos["fecha"] = fecha
                    return datos

        coincidencia = re.search(
            r"\b(?:January|February|March|April|May|June|"
            r"July|August|September|October|November|December)"
            r"\s+\d{1,2},\s+20\d{2}\b",
            limpiar(soup.get_text(" ", strip=True)),
            flags=re.IGNORECASE,
        )

        if coincidencia:
            datos["fecha"] = convertir_fecha(
                coincidencia.group(0)
            )

    except requests.RequestException as error:
        print(
            f"No se pudieron ampliar los datos de {url}: "
            f"{error}"
        )

    return datos


def obtener_comunicados():
    respuesta = descargar(SOURCE_URL)
    soup = BeautifulSoup(respuesta.text, "html.parser")

    encabezado = None

    for titulo in soup.find_all(
        ["h2", "h3", "h4", "strong"],
    ):
        if limpiar(titulo.get_text()).lower() == "press releases":
            encabezado = titulo
            break

    if not encabezado:
        raise RuntimeError(
            "No se encontró el apartado Press Releases "
            "en la página de GigaGen."
        )

    comunicados = []
    enlaces_vistos = set()

    for elemento in encabezado.find_all_next(
        ["h2", "h3", "h4", "a"]
    ):
        if elemento.name in ["h2", "h3", "h4"]:
            texto_encabezado = limpiar(
                elemento.get_text(" ", strip=True)
            ).lower()

            if texto_encabezado == "in the news":
                break

            continue

        enlace = urljoin(
            SOURCE_URL,
            elemento.get("href", ""),
        )

        titulo = limpiar(
            elemento.get_text(" ", strip=True)
        )

        if (
            not enlace.startswith("http")
            or len(titulo) < 15
            or enlace in enlaces_vistos
        ):
            continue

        enlaces_vistos.add(enlace)
        datos = obtener_datos_articulo(enlace)

        comunicados.append({
            "titulo": titulo,
            "enlace": enlace,
            "fecha": datos["fecha"],
            "descripcion": datos["descripcion"],
        })

    if not comunicados:
        raise RuntimeError(
            "No se encontraron comunicados actuales de GigaGen. "
            "La RSS anterior no será eliminada."
        )

    fecha_antigua = datetime(
        1970,
        1,
        1,
        tzinfo=timezone.utc,
    )

    comunicados.sort(
        key=lambda noticia: (
            noticia["fecha"] or fecha_antigua
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
        "Current press releases published by GigaGen"
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
