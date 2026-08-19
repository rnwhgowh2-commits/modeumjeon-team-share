import pathlib

from flask import Flask, render_template
from jinja2 import Environment, FileSystemLoader

from app import _resolve_samba_wave_url

TEMPLATES_DIR = (
    pathlib.Path(__file__).parent.parent / "webapp" / "templates"
)

_ICONS = {
    "bundles": {"emoji": "📦", "color": None},
    "inventory": {"emoji": "🏬", "color": None},
    "bulk": {"emoji": "🚀", "color": None},
}


def _render(samba_wave_url):
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("partials/_modeswitch.html")
    return template.render(
        active_app="bulk",
        sidebar_mode_icons=_ICONS,
        samba_wave_url=samba_wave_url,
    )


def test_modeswitch_link_defaults_to_bulk():
    html = _render(samba_wave_url=None)
    assert 'href="/bulk/"' in html


def test_modeswitch_link_uses_samba_wave_url_when_set():
    html = _render(samba_wave_url="https://samba-wave.example.com")
    assert 'href="https://samba-wave.example.com"' in html
    assert 'href="/bulk/"' not in html


def test_resolve_samba_wave_url_missing(monkeypatch):
    monkeypatch.delenv("SAMBA_WAVE_URL", raising=False)
    assert _resolve_samba_wave_url() is None


def test_resolve_samba_wave_url_whitespace_only(monkeypatch):
    """공백만 있는 값은 truthy 라 그냥 두면 href="   " 로 새서 링크가 조용히 깨진다."""
    monkeypatch.setenv("SAMBA_WAVE_URL", "   ")
    assert _resolve_samba_wave_url() is None


def test_resolve_samba_wave_url_strips_surrounding_whitespace(monkeypatch):
    monkeypatch.setenv("SAMBA_WAVE_URL", "  https://samba-wave.example.com  ")
    assert _resolve_samba_wave_url() == "https://samba-wave.example.com"


def _wiring_app() -> Flask:
    """create_app()(실 DB 필요)을 안 거치고, 진짜 컨텍스트프로세서 배선이 진짜
    HTTP 요청 경로에서 실제로 동작하는지 확인하기 위한 최소 앱.

    [코드리뷰 반영] 위의 _render()/직접 호출 테스트는 컨텍스트프로세서의 반환
    딕셔너리 키가 오타 나거나(@app.context_processor 데코레이터가 지워져도)
    구분 못 한다 — Undefined or '/bulk/' 가 조용히 '/bulk/' 로 떨어지기 때문.
    여긴 app.py 의 실제 등록 방식(@app.context_processor 로 samba_wave_url 키
    주입)을 그대로 재현해 실 배선을 검증한다.
    """
    test_app = Flask(
        __name__,
        template_folder=str(TEMPLATES_DIR),
    )

    @test_app.context_processor
    def _inject_samba_wave_url():
        return {"samba_wave_url": _resolve_samba_wave_url()}

    @test_app.route("/probe/<mode>")
    def probe(mode):
        return render_template(
            "partials/_modeswitch.html",
            active_app=mode,
            sidebar_mode_icons=_ICONS,
        )

    return test_app


def test_real_context_processor_wiring_defaults_to_bulk(monkeypatch):
    monkeypatch.delenv("SAMBA_WAVE_URL", raising=False)
    client = _wiring_app().test_client()
    html = client.get("/probe/bulk").get_data(as_text=True)
    assert 'href="/bulk/"' in html


def test_real_context_processor_wiring_switches_when_set(monkeypatch):
    monkeypatch.setenv("SAMBA_WAVE_URL", "https://samba-wave.example.com")
    client = _wiring_app().test_client()
    html = client.get("/probe/bulk").get_data(as_text=True)
    assert 'href="https://samba-wave.example.com"' in html
    assert 'href="/bulk/"' not in html
