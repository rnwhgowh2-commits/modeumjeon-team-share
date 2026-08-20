# -*- coding: utf-8 -*-
"""마진 패키지 부트스트랩 — 의존성·패키지 존재 확인."""


def test_pandas_importable():
    import pandas as pd
    assert pd.__version__.startswith("2.")


def test_xlrd_importable():
    import xlrd
    assert xlrd.__version__.startswith("2.")


def test_html5lib_importable():
    import html5lib
    assert html5lib is not None


def test_margin_package_importable():
    import lemouton.margin
    assert lemouton.margin is not None
