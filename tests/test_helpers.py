
# tests/test_helpers.py
from utils.helpers import normalize_product, prettify_product, parse_coord, confidence_label, confidence_class

def test_normalize_product_basic():
    assert normalize_product("Leche 1L") == "leche 1 l"
    assert normalize_product("  LECHE   1   l ") == "leche 1 l"
    assert normalize_product("Yerba 500ml") == "yerba 500 ml"
    assert normalize_product("") == ""

def test_prettify_product():
    assert prettify_product("leche 1 l") == "Leche 1 l"
    assert prettify_product("yerba 500 g") == "Yerba 500 g"

def test_parse_coord():
    assert parse_coord("-38.7183") == -38.7183
    assert parse_coord("abc") is None

def test_confidence():
    assert confidence_label(1).startswith("Reportado")
    assert confidence_class(1) == "confidence-red"
    assert confidence_class(3) == "confidence-yellow"
    assert confidence_class(10) == "confidence-green"
``
