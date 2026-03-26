import json
import logging
import time
from pathlib import Path

import pandas as pd
import requests

from config import (
    BASKET_CACHE_TTL_SEC,
    DEST,
    DELAY,
    FILTER_COUNTRY,
    FILTER_MAX_PRICE,
    FILTER_MIN_RATING,
    HEADERS,
    MAX_PAGES,
    OUTPUT_ALL,
    OUTPUT_FILTERED,
    SEARCH_QUERY,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_SEARCH_URL = (
    "https://search.wb.ru/exactmatch/ru/common/v18/search"
    "?appType=1&curr=rub&dest={dest}&lang=ru"
    "&page={page}&query={query}&resultset=catalog&sort=popular&spp=30"
)
_CARD_URL_BY_ID = "https://www.wildberries.ru/catalog/{nm_id}/detail.aspx"
_UPSTREAMS_URL = "https://cdn.wbbasket.ru/api/v3/upstreams"

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

_basket_ranges_mem: list[tuple[int, int, str]] | None = None


def _basket_cache_path() -> Path:
    return Path(__file__).resolve().parent / ".wb_parser_cache" / "basket_ranges.json"


def _try_read_basket_cache() -> list[tuple[int, int, str]] | None:
    if BASKET_CACHE_TTL_SEC <= 0:
        return None
    path = _basket_cache_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        saved_at = float(raw["saved_at"])
        if time.time() - saved_at > BASKET_CACHE_TTL_SEC:
            return None
        return [(int(a), int(b), str(c)) for a, b, c in raw["ranges"]]
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.warning("кэш basket не использован: %s", e)
        return None


def _write_basket_cache(ranges: list[tuple[int, int, str]]) -> None:
    if BASKET_CACHE_TTL_SEC <= 0 or not ranges:
        return
    path = _basket_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"saved_at": time.time(), "ranges": [list(t) for t in ranges]}
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logger.warning("не удалось записать кэш basket: %s", e)


def _load_basket_ranges_from_network() -> list[tuple[int, int, str]]:
    """Загружает актуальную таблицу маршрутизации basket-серверов с CDN WB."""
    try:
        resp = requests.get(_UPSTREAMS_URL, timeout=5)
        resp.raise_for_status()
        hosts = resp.json()["recommend"]["mediabasket_route_map"][0]["hosts"]
        return [
            (h["vol_range_from"], h["vol_range_to"], h["host"].removeprefix("basket-").removesuffix(".wbbasket.ru"))
            for h in hosts
        ]
    except Exception as e:
        logger.warning("не удалось загрузить таблицу basket-серверов: %s — используем fallback", e)
        return []


def _load_basket_ranges_with_file_cache() -> list[tuple[int, int, str]]:
    cached = _try_read_basket_cache()
    if cached:
        logger.info("таблица basket взята из локального кэша")
        return cached
    ranges = _load_basket_ranges_from_network()
    if ranges:
        _write_basket_cache(ranges)
    return ranges


def get_basket_ranges() -> list[tuple[int, int, str]]:
    """Таблица диапазонов vol → basket (ленивая загрузка, без запроса при import)."""
    global _basket_ranges_mem
    if _basket_ranges_mem is None:
        _basket_ranges_mem = _load_basket_ranges_with_file_cache()
    return _basket_ranges_mem


def _get_with_retry(url: str, *, retries: int = 3, backoff: float = 20.0) -> requests.Response | None:
    """GET с повторами при 429, 5xx и сетевых таймаутах."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
        except requests.exceptions.Timeout:
            logger.warning("таймаут (попытка %d/%d): %s", attempt, retries, url)
            if attempt >= retries:
                break
            time.sleep(backoff * attempt)
            continue
        except requests.exceptions.RequestException as e:
            logger.error("ошибка запроса: %s", e)
            return None

        if resp.status_code in _RETRYABLE_STATUSES:
            wait = backoff * attempt
            logger.warning(
                "HTTP %s — ждём %.0f сек (попытка %d/%d)",
                resp.status_code,
                wait,
                attempt,
                retries,
            )
            time.sleep(wait)
            continue

        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP ошибка: %s", e)
            return None
        return resp

    logger.error("исчерпаны %d попытки для: %s", retries, url)
    return None


def fetch_search_page(query: str, page: int) -> list[dict]:
    """Запрашивает одну страницу поиска и возвращает список товаров."""
    url = _SEARCH_URL.format(dest=DEST, page=page, query=query)
    resp = _get_with_retry(url)
    if resp is None:
        return []
    return resp.json().get("products", [])


def _basket_host(nm_id: int) -> str:
    """Определяет номер basket-сервера по артикулу"""
    vol = nm_id // 100_000
    for lo, hi, num in get_basket_ranges():
        if lo <= vol <= hi:
            return num
    logger.warning("nm_id %d (vol %d) вне таблицы basket-диапазонов", nm_id, vol)
    return "01"


def build_image_urls(nm_id: int, pics: int) -> list[str]:
    """Строит список URL изображений товара по артикулу и количеству фото"""
    vol = nm_id // 100_000
    part = nm_id // 1_000
    basket = _basket_host(nm_id)
    base = f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/images/big"
    return [f"{base}/{i}.webp" for i in range(1, pics + 1)]


def _card_json_url(nm_id: int) -> str:
    """Строит URL до card.json на CDN"""
    vol = nm_id // 100_000
    part = nm_id // 1_000
    basket = _basket_host(nm_id)
    return f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/info/ru/card.json"


def fetch_card_detail(nm_id: int) -> dict:
    """Запрашивает card.json с CDN и возвращает описание, характеристики, страну."""
    url = _card_json_url(nm_id)
    resp = _get_with_retry(url)
    if resp is None:
        return {}
    data = resp.json()
    options: list[dict] = data.get("options", [])
    country = next(
        (o["value"] for o in options if "страна" in o.get("name", "").lower()),
        None,
    )
    return {
        "description": data.get("description", ""),
        "options": options,
        "country": country,
    }


def build_record(raw: dict) -> dict:
    """Собирает полную запись товара из сырых данных поиска + card.json."""
    nm_id: int = raw["id"]
    pics: int = raw.get("pics", 0)

    detail = fetch_card_detail(nm_id)
    time.sleep(DELAY)

    sizes = raw.get("sizes", [])
    size_names = [s["name"] for s in sizes if s.get("name")]
    price_raw = sizes[0].get("price", {}).get("product", 0) if sizes else 0
    price = price_raw / 100

    options: list[dict] = detail.get("options", [])
    characteristics = "; ".join(f'{o["name"]}: {o["value"]}' for o in options)

    supplier_id: int = raw.get("supplierId", 0)

    return {
        "Ссылка на товар": _CARD_URL_BY_ID.format(nm_id=nm_id),
        "Артикул": nm_id,
        "Название": raw.get("name", ""),
        "Цена": price,
        "Описание": detail.get("description", ""),
        "Ссылки на изображения": ", ".join(build_image_urls(nm_id, pics)),
        "Характеристики": characteristics,
        "Продавец": raw.get("supplier", ""),
        "Ссылка на продавца": f"https://www.wildberries.ru/seller/{supplier_id}",
        "Размеры": ", ".join(size_names),
        "Остатки": raw.get("totalQuantity", 0),
        "Рейтинг": raw.get("reviewRating", 0),
        "Количество отзывов": raw.get("feedbacks", 0),
        "Страна производства": detail.get("country", ""),
    }


def collect_search_results(query: str) -> list[dict]:
    """Собирает все страницы поиска и возвращает сырой список товаров"""
    all_products = []
    for page in range(1, MAX_PAGES + 1):
        products = fetch_search_page(query, page)
        if not products:
            logger.info("страница %d пустая, завершаем сбор", page)
            break
        all_products.extend(products)
        logger.info("страница %d — получено %d шт. (всего: %d)", page, len(products), len(all_products))
        time.sleep(DELAY)
    return all_products


def collect_all_records(query: str) -> list[dict]:
    """Собирает полные записи по всем товарам из поиска."""
    raw_products = collect_search_results(query)
    logger.info("начинаем обогащение карточек, товаров: %d", len(raw_products))
    records = []
    for i, raw in enumerate(raw_products, start=1):
        try:
            record = build_record(raw)
            records.append(record)
        except Exception as e:
            logger.error("товар %d (id=%s) — ошибка сборки записи: %s", i, raw.get("id"), e)
        if i % 50 == 0:
            logger.info("обработано %d / %d", i, len(raw_products))
    logger.info("готово: собрано %d записей", len(records))
    return records


def save_xlsx(records: list[dict], path: str) -> None:
    """Сохраняет список записей в XLSX-файл."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_excel(out, index=False)
    logger.info("сохранено: %s (%d строк)", path, len(records))


def apply_filter(records: list[dict]) -> list[dict]:
    """Возвращает записи, удовлетворяющие критериям фильтрации."""
    return [
        r for r in records
        if r["Рейтинг"] >= FILTER_MIN_RATING
        and r["Цена"] <= FILTER_MAX_PRICE
        and (r["Страна производства"] or "").strip().lower() == FILTER_COUNTRY.lower()
    ]


def main() -> None:
    records = collect_all_records(SEARCH_QUERY)
    if not records:
        logger.warning("результаты пусты, файлы не созданы")
        return
    save_xlsx(records, OUTPUT_ALL)

    filtered = apply_filter(records)
    logger.info("отфильтровано: %d записей (рейтинг ≥ %.1f, цена ≤ %d, страна = %s)",
                len(filtered), FILTER_MIN_RATING, FILTER_MAX_PRICE, FILTER_COUNTRY)
    save_xlsx(filtered, OUTPUT_FILTERED)


if __name__ == "__main__":
    main() 
