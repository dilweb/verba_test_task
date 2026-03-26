import pytest
from unittest.mock import patch


# Таблица basket-диапазонов для тестов
TEST_BASKET_RANGES = [
    (0, 143, "01"),
    (144, 287, "02"),
    (7374, 7685, "35"),
]


@patch("wb_parser.get_basket_ranges", new=lambda: TEST_BASKET_RANGES)
class TestBasketHost:
    """Тесты определения basket-сервера по артикулу."""

    def test_vol_in_first_range(self):
        from wb_parser import _basket_host
        assert _basket_host(14_000_000) == "01"  # vol 140

    def test_vol_in_second_range(self):
        from wb_parser import _basket_host
        assert _basket_host(15_000_000) == "02"  # vol 150

    def test_vol_in_basket_35_range(self):
        from wb_parser import _basket_host
        assert _basket_host(749357736) == "35"  # vol 7493

    def test_vol_outside_table_returns_fallback(self):
        from wb_parser import _basket_host
        assert _basket_host(999_999_999) == "01"  # vol 9999 вне таблицы


@patch("wb_parser.get_basket_ranges", new=lambda: TEST_BASKET_RANGES)
class TestBuildImageUrls:
    """Тесты построения URL изображений."""

    def test_url_structure(self):
        from wb_parser import build_image_urls
        urls = build_image_urls(749357736, 3)
        assert len(urls) == 3
        assert urls[0] == "https://basket-35.wbbasket.ru/vol7493/part749357/749357736/images/big/1.webp"
        assert urls[1].endswith("/2.webp")
        assert urls[2].endswith("/3.webp")

    def test_zero_pics_returns_empty_list(self):
        from wb_parser import build_image_urls
        assert build_image_urls(749357736, 0) == []


@patch("wb_parser.get_basket_ranges", new=lambda: TEST_BASKET_RANGES)
class TestCardJsonUrl:
    """Тесты построения URL card.json."""

    def test_url_format(self):
        from wb_parser import _card_json_url
        url = _card_json_url(749357736)
        assert url == "https://basket-35.wbbasket.ru/vol7493/part749357/749357736/info/ru/card.json"


@patch("wb_parser.FILTER_MIN_RATING", 4.5)
@patch("wb_parser.FILTER_MAX_PRICE", 10000)
@patch("wb_parser.FILTER_COUNTRY", "Россия")
class TestApplyFilter:
    """Тесты фильтрации записей."""

    def test_passes_all_criteria(self):
        from wb_parser import apply_filter
        records = [{
            "Рейтинг": 4.8,
            "Цена": 5000,
            "Страна производства": "Россия",
        }]
        assert len(apply_filter(records)) == 1

    def test_rejects_low_rating(self):
        from wb_parser import apply_filter
        records = [{
            "Рейтинг": 4.0,
            "Цена": 5000,
            "Страна производства": "Россия",
        }]
        assert len(apply_filter(records)) == 0

    def test_rejects_high_price(self):
        from wb_parser import apply_filter
        records = [{
            "Рейтинг": 4.8,
            "Цена": 15000,
            "Страна производства": "Россия",
        }]
        assert len(apply_filter(records)) == 0

    def test_rejects_wrong_country(self):
        from wb_parser import apply_filter
        records = [{
            "Рейтинг": 4.8,
            "Цена": 5000,
            "Страна производства": "Китай",
        }]
        assert len(apply_filter(records)) == 0

    def test_country_case_insensitive(self):
        from wb_parser import apply_filter
        records = [{
            "Рейтинг": 4.8,
            "Цена": 5000,
            "Страна производства": "РОССИЯ",
        }]
        assert len(apply_filter(records)) == 1

    def test_empty_country_rejected(self):
        from wb_parser import apply_filter
        records = [{
            "Рейтинг": 4.8,
            "Цена": 5000,
            "Страна производства": "",
        }]
        assert len(apply_filter(records)) == 0
