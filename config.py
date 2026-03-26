SEARCH_QUERY = "пальто из натуральной шерсти"
DEST = "-1257786" # регион (Москва)
MAX_PAGES = 50
DELAY = 1 # пауза между запросами в секундах

OUTPUT_ALL = "results/catalog_all.xlsx"
OUTPUT_FILTERED = "results/catalog_filtered.xlsx"

FILTER_MIN_RATING = 4.5
FILTER_MAX_PRICE = 10000
FILTER_COUNTRY = "Россия"

# Кэш таблицы basket на диске (рядом с проектом, см. wb_parser). 0 = не использовать файловый кэш.
BASKET_CACHE_TTL_SEC = 3600

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}