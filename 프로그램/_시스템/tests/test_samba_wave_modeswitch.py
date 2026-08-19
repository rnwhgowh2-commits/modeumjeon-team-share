import pathlib

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
