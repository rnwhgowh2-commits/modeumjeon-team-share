# -*- coding: utf-8 -*-
"""margin_ext_check.js — E2 소싱처 주문상태 seam 의 순수 파싱(_parseMemo) 단위검증(Node).

브라우저 전용(확장·부모 MoumExt)이라 E2E 는 라이브 체크리스트로 검증하되, 간단메모 →
{url, site_key, account_id} 순수 파싱은 Node 로 결정적 검증 가능(블랙스팟 extract_memo_info 미러).
확장·window.parent 없이 window stub 만으로 로드되어 _parseMemo 를 노출한다.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

_STATIC = pathlib.Path(__file__).resolve().parents[2] / "webapp" / "static"
FILE = _STATIC / "margin_ext_check.js"
EXT_BRIDGE = _STATIC / "ext_bridge.js"


def test_file_exists():
    assert FILE.exists()


def test_seam_uses_typed_bridge_method_not_private_send():
    """[E2 리뷰 회귀가드] seam 은 MoumExt 의 타입 메서드 checkSourcingOrder 를 호출해야 한다.

    raw send 는 ext_bridge.js IIFE 내부 private 라 window.MoumExt 로 노출되지 않는다 →
    ext.send(...) 호출은 happy path 에서 TypeError 로 죽는다(해피패스 배선 사망 회귀). 방지.
    """
    seam = FILE.read_text(encoding="utf-8")
    bridge = EXT_BRIDGE.read_text(encoding="utf-8")
    # (1) 브리지가 타입 메서드를 노출
    assert "checkSourcingOrder:" in bridge, "ext_bridge.js MoumExt 에 checkSourcingOrder 미노출"
    assert 'send("sourcing.check-order"' in bridge, "checkSourcingOrder 가 sourcing.check-order 로 배선 안 됨"
    # (2) seam 이 타입 메서드를 호출, raw send 직접호출 금지
    assert "ext.checkSourcingOrder(" in seam, "seam 이 타입 메서드를 호출하지 않음"
    assert "ext.send(" not in seam, "seam 이 노출 안 된 private send 를 직접 호출(해피패스 사망 회귀)"
    # (3) 배치 중지(AbortController) 배선
    assert "opts.signal" in seam or "opts && opts.signal" in seam, "opts.signal(배치 중지) 미배선"
    assert "AbortError" in seam, "AbortError 처리 미배선"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_parse_memo_via_node():
    # window stub 만 주입하면 IIFE 가 window._moumParseMemo 를 노출(로드 시 document/부모 미참조).
    script = r"""
    const fs = require('fs');
    global.window = {};
    const code = fs.readFileSync(process.argv[1], 'utf-8');
    (0, eval)(code);
    const P = global.window._moumParseMemo;
    const cases = [
      // 1) 날짜 소싱처명 / 계정 + 무신사 URL
      '26.04.14 무신사 / rnwhgowh1 은순 https://www.musinsa.com/order/order-detail/ABC123',
      // 2) URL 없음 — 소싱처명 텍스트 + "계정 : 무신사/rnwhgowh2"
      '25.08.03 주문번호 : 202508031019270004 -. 계정 : 무신사/rnwhgowh2',
      // 3) 롯데온 URL
      '25.09.01 롯데온 / rnwhgowh2 https://www.lotteon.com/order/orderView.ecp?orderNo=XYZ',
      // 4) 미지원 소싱처(현대H몰) — site_key 비어야(정직: 확인 불가)
      '25.09.02 현대H몰 / acc https://www.hmall.com/p/orderDetail?ordNo=1',
      // 5) 빈 메모
      '',
    ];
    console.log(JSON.stringify(cases.map(P)));
    """
    r = subprocess.run(["node", "-e", script, str(FILE)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])

    # 1) 무신사 URL → site_key musinsa, 계정 rnwhgowh1
    assert out[0]["site_key"] == "musinsa"
    assert out[0]["account_id"] == "rnwhgowh1"
    assert out[0]["url"].startswith("https://www.musinsa.com/order/order-detail/ABC123")

    # 2) URL 없이 소싱처명 텍스트 → musinsa, 계정 rnwhgowh2
    assert out[1]["site_key"] == "musinsa"
    assert out[1]["account_id"] == "rnwhgowh2"
    assert out[1]["url"] == ""

    # 3) 롯데온 URL → lotteon
    assert out[2]["site_key"] == "lotteon"

    # 4) 미지원 소싱처 → site_key 빈 문자열(폴백 없이 확인 불가 유도 = 정직)
    assert out[3]["site_key"] == "", "미지원 소싱처가 거짓 site_key 로 매칭되면 안 됨"

    # 5) 빈 메모 → 전부 빈 값
    assert out[4] == {"url": "", "account_id": "", "site_name": "", "site_key": ""}
