# -*- coding: utf-8 -*-
"""배경 프리페치가 옥션·G마켓의 조회 차례를 잡아먹지 않게.

라이브 실측(2026-08-12):
  · 옥션 「하루치」 조회 하나가 52.6초. 마켓 규정이 **계정당 5초에 1회**인데
    조회 한 번에 대기 걸리는 호출이 6개 나간다(주문상태 5가지 + 입금확인중).
  · 화면은 8일 이하 빠른기간 전부(≈7개)를 미리 데운다 → 옥션만 42개 호출이
    대기줄에 쌓여 210초. 사용자가 실제로 누른 조회가 그 뒤에 서서
    앞단 100초 한도를 넘겨 `524: A timeout occurred` 로 끊겼다.
  · 실패하면 15초 뒤 자동 재시도가 또 한 번 대기줄을 채워 더 나빠졌다.

그래서 **5초/1회 마켓은 미리 데우지 않는다.** 미리 데워 아끼는 시간보다,
차례를 빼앗겨 실제 조회가 죽는 손해가 훨씬 크다.
"""
import pathlib
import re

TPL = pathlib.Path(__file__).resolve().parents[2] / "webapp/templates/orders/index.html"


def _src():
    return TPL.read_text(encoding="utf-8")


def test_프리페치_제외_마켓에_옥션과_G마켓이_있다():
    s = _src()
    m = re.search(r"PREFETCH_SKIP\s*=\s*\{([^}]*)\}", s)
    assert m, "프리페치에서 뺄 마켓 목록(PREFETCH_SKIP)이 없다"
    body = m.group(1)
    assert "auction" in body and "gmarket" in body, \
        "옥션·G마켓이 프리페치 제외에 없다: %s" % body


def test_프리페치가_그_목록을_실제로_거른다():
    s = _src()
    i = s.find("function prefetchNeighbors")
    assert i > 0, "prefetchNeighbors 가 없다"
    block = s[i:i + 1400]
    assert "PREFETCH_SKIP" in block, \
        "목록만 만들고 프리페치가 안 쓴다 — 이름만 있는 껍데기"


def test_왜_빼는지_코드에_적혀_있다():
    """숫자 없는 주석은 다음 사람이 되돌린다 — 실측값을 남긴다."""
    s = _src()
    i = s.find("PREFETCH_SKIP")
    around = s[max(0, i - 900):i + 300]
    assert "5초" in around, "5초/1회 제한이 이유라는 게 안 적혀 있다"
    assert "524" in around or "100초" in around, "앞단 한도에 걸린 사실이 안 적혀 있다"


# ── 524(앞단 시간초과)를 「네트워크 오류」로 뭉개지 않기 ────────────────────────
#   `r.json()` 이 Cloudflare 오류 HTML 에서 터져 `.catch` 로 떨어지면 화면엔
#   「네트워크 오류로 불러오지 못했어요」만 남는다. 무엇을 손볼지 알 수 없다.

def test_시간초과를_따로_말한다():
    s = _src()
    assert "524" in s, "앞단 시간초과(524)를 화면이 갈라 말하지 않는다"
    i = s.find("function fetchOne")
    assert i > 0
    block = s[i:i + 2600]
    assert "status" in block, "HTTP 상태를 안 보고 사유를 만든다"


def test_시간초과는_자동_재시도하지_않는다():
    """재시도가 5초 대기줄을 또 채워 더 느려진다 — 실패 원인을 키우는 재시도다."""
    s = _src()
    i = s.find("function fetchOne")
    block = s[i:i + 2600]
    assert "noRetry" in block, "시간초과에도 15초 자동 재시도가 그대로다"
