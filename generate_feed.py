from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import xml.etree.ElementTree as ET

from feedgen.feed import FeedGenerator
from playwright.sync_api import sync_playwright


PAGINA = "https://www.gigagen.com/#news"
ARCHIVO_RSS = Path("docs/feed.xml")

URL_RSS_PUBLICA = (
    "https://raw.githubusercontent.com/"
    "plis2100/rss-gigagen/main/docs/feed.xml"
)

DOMINIOS_NOTICIAS = (
    "grifols.com",
    "globenewswire.com",
    "prnewswire.com",
)


def cargar_fechas_anteriores():
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


def limpiar_texto(texto):
    return " ".join((texto or "").split()).strip()


def obtener_comunicados():
    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        pagina = navegador.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            viewport={
                "width": 1440,
                "height": 1200,
            },
        )

        print("Abriendo la página de GigaGen...")

        pagina.goto(
            PAGINA,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        # Esperar a que WordPress termine de cargar el contenido.
        pagina.wait_for_timeout(5000)

        enlaces = pagina.locator("a[href]").evaluate_all(
            """
            elementos => elementos.map(elemento => ({
                titulo: (
                    elemento.innerText ||
                    elemento.textContent ||
                    elemento.getAttribute("aria-label") ||
                    elemento.getAttribute("title") ||
                    ""
                ).replace(/\\s+/g, " ").trim(),

                enlace: elemento.href || ""
            }))
            """
        )

        navegador.close()

    comunicados = []
    enlaces_vistos = set()

    for elemento in enlaces:
        titulo = limpiar_texto(elemento.get("titulo"))
        enlace = limpiar_texto(elemento.get("enlace"))
        titulo_minusculas = titulo.lower()
        enlace_minusculas = enlace.lower()

        if not titulo or not enlace:
            continue

        # El título tiene que referirse a GigaGen.
        if "gigagen" not in titulo_minusculas:
            continue

        # Solamente se admiten enlaces de comunicados oficiales.
        if not any(
            dominio in enlace_minusculas
            for dominio in DOMINIOS_NOTICIAS
        ):
            continue

        if enlace in enlaces_vistos:
            continue

        enlaces_vistos.add(enlace)

        comunicados.append(
            {
                "titulo": titulo,
                "enlace": enlace,
                "descripcion": (
                    "Comunicado de prensa o noticia corporativa de GigaGen."
                ),
            }
        )

    if not comunicados:
        raise RuntimeError(
            "GigaGen cargó la página, pero no se encontraron enlaces "
            "de comunicados de Grifols, GlobeNewswire o PR Newswire."
        )

    print(f"Se encontraron {len(comunicados)} comunicados.")

    for comunicado in comunicados:
        print(f"- {comunicado['titulo']}")

    return comunicados[:40]


def crear_rss(comunicados):
    fechas_anteriores = cargar_fechas_anteriores()
    ahora = datetime.now(timezone.utc)

    generador = FeedGenerator()

    generador.id(PAGINA)
    generador.title("GigaGen - Press Releases")
    generador.description(
        "Últimos comunicados de prensa y noticias corporativas de GigaGen"
    )
    generador.language("en")
    generador.link(
        href=PAGINA,
        rel="alternate",
    )
    generador.link(
        href=URL_RSS_PUBLICA,
        rel="self",
    )
    generador.lastBuildDate(ahora)

    for comunicado in reversed(comunicados):
        enlace = comunicado["enlace"]

        # Conserva la fecha antigua si la noticia ya existía.
        # Las noticias nuevas reciben la fecha de su primera detección.
        fecha = fechas_anteriores.get(enlace, ahora)

        entrada = generador.add_entry()
        entrada.id(enlace)
        entrada.guid(enlace, permalink=True)
        entrada.title(comunicado["titulo"])
        entrada.link(href=enlace)
        entrada.description(comunicado["descripcion"])
        entrada.pubDate(fecha)

    ARCHIVO_RSS.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    generador.rss_file(
        str(ARCHIVO_RSS),
        pretty=True,
    )

    if not ARCHIVO_RSS.exists():
        raise RuntimeError("No se creó docs/feed.xml.")

    if ARCHIVO_RSS.stat().st_size < 200:
        raise RuntimeError("docs/feed.xml está vacío o incompleto.")

    # Verificar que el resultado sea XML válido.
    ET.parse(ARCHIVO_RSS)

    print(f"RSS creado correctamente: {ARCHIVO_RSS}")


def main():
    comunicados = obtener_comunicados()
    crear_rss(comunicados)


if __name__ == "__main__":
    main()
