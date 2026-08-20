# -*- coding: utf-8 -*-
"""왕복 절차 — 바꿔 보내고 · 되읽어 확인하고 · 되돌리고 · 되읽어 확인한다.

절차(이 순서를 바꾸면 안전이 깨진다):
    1. before  = 마켓에서 되읽기
    2. 판매중이면 거부 (판매중 상품은 건드리지 않는다)
    3. 저널에 before 기록  ← **여기 실패하면 전송하지 않는다**
    4. try:  시험값 전송 → 되읽기 → 「진짜 바뀌었나」 검사
    5. finally: **before 값으로 원복** → 되읽기 → 「진짜 돌아왔나」 검사
    6. 원복 실패 = 🔴 큰 경보 + 저널 경로(손복구 근거)

원복값은 **마켓이 실제로 준 값**이다. 「우리가 보내려던 값」으로 되돌리면
마켓이 우리 뜻과 다르게 갖고 있던 것을 덮어써 조용히 틀린 값이 남는다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from lemouton.uploader.roundtrip.snapshot import AXES, AXIS_LABELS, Snapshot

logger = logging.getLogger(__name__)

#: 재고 시험값. 현재값과 같으면 「안 바뀌었는데 통과」가 되므로 다른 값으로 비킨다.
#: 사장님 확정(2026-08-07) — **가격 +100원 · 재고 +1**.
#:   폭이 작을수록 사고가 나도 피해가 작다(원복 실패 시 남는 차이도 100원).
#:   🔴 재고를 고정값(7)으로 덮던 옛 방식은 위험했다 — 재고가 430인 상품이
#:      7로 줄어 오버셀이 날 수 있다. **상대값(+1)** 으로 바꾼다.
_PRICE_DELTA = 100
_STOCK_DELTA = 1
_NAME_SUFFIX = " (시험중)"

#: 상세에 붙일 표식. **속성을 쓰지 않는다** — 네이버는 모르는 속성을 지우고
#: `<!-- Not Allowed Attribute Filtered (…) -->` 주석으로 바꿔버린다(2026-08-06 실측).
#: 평문 토큰이라야 검열을 통과해 되읽기에서 찾을 수 있다.
_DETAIL_TOKEN = "ROUNDTRIP-TEST-MARK"
_DETAIL_MARK = f"<p>{_DETAIL_TOKEN}</p>"


@dataclass
class AxisResult:
    """축 하나의 왕복 결과."""

    axis: str
    label: str
    before: object = None
    sent: object = None
    after: object = None
    #: True=바뀜 · False=안 바뀜 · None=확인불가(시험 자체를 안 했다)
    changed_ok: bool | None = None
    restored: object = None
    restored_ok: bool | None = None
    note: str = ""


@dataclass
class RoundtripReport:
    ok: bool = False
    refusal: str | None = None
    axes: tuple = ()
    reverted: bool = False
    revert_error: str | None = None
    journal_path: str = ""
    send_error: str | None = None
    before: Snapshot | None = None
    recovery_hint: str = ""


def _test_value(axis: str, before: Snapshot, image_url: str | None, *, bounds=None):
    """축별 시험값 — before 에서 만든다(고정 상수 금지: 현재값과 같으면 검증 무의미).

    Args:
        bounds: 재고 (하한, 상한). 마켓이 정한 범위를 어댑터가 알려준다. 모르면 None.

    🔴 [2026-08-12] 11번가 실측 — 재고가 이미 **상한(9,999)** 인 상품에 +1 을 보내
       마켓이 거부했다. 왕복은 "값을 흔들었다 되돌리는" 것이지 "무조건 늘리는" 게
       아니다. 위로 못 가면 아래로 흔든다. 방향이 없으면 None(=확인불가)을 준다.
       ⚠️ 가격은 방향을 바꾸지 않는다 — 내리면 그 잠깐 **싸게 팔린다**(금전 손실).
    """
    cur = before.value_of(axis)
    if axis == "sale_price":
        return int(cur) + _PRICE_DELTA
    if axis == "stock":
        cur = int(cur)
        lo, hi = (bounds or (None, None))
        if hi is not None and cur + _STOCK_DELTA > hi:
            down = cur - _STOCK_DELTA
            if lo is not None and down < lo:
                return None            # 흔들 방향이 없다 — 지어내지 않는다
            return down
        return cur + _STOCK_DELTA
    if axis == "name":
        return str(cur) + _NAME_SUFFIX
    if axis == "detail_html":
        return str(cur) + _DETAIL_MARK
    if axis == "image_urls":
        # 대표(첫 장)를 시험 이미지로 바꾼다. 나머지는 그대로 둔다.
        return (image_url,) + tuple(cur)[1:]
    raise ValueError(f"모르는 축: {axis!r}")


def _eq(a, b) -> bool:
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        return tuple(a or ()) == tuple(b or ())
    return a == b


def _changed_ok(axis: str, sent, after) -> bool:
    """「진짜 바뀌었나」 판정. 마켓이 값을 손보는 축은 완전일치로 보면 안 된다.

    상세 HTML: 네이버가 검열해 돌려주므로(2026-08-06 실측) **표식이 들어 있는가**로 본다.
    표식은 평문이라 검열을 통과한다 — 「무조건 통과」가 아니라, 안 보내면 없으므로 잡힌다.
    """
    if axis == "detail_html":
        return _DETAIL_TOKEN in str(after or "")
    return _eq(after, sent)


def _restored_ok(axis: str, before, restored) -> bool:
    """「진짜 되돌아왔나」 판정. 원래값은 이미 마켓 검열을 통과한 값이라 일치해야 한다.
    상세는 그 위에 **표식이 사라졌는지**까지 확인한다."""
    if axis == "detail_html":
        return _eq(restored, before) and _DETAIL_TOKEN not in str(restored or "")
    return _eq(restored, before)


def run_roundtrip(*, snapshot_fn, apply_fn, journal, axes=AXES,
                  on_sale_fn=None, image_url_fn=None,
                  approval_axes=(), allow_on_sale=False,
                  stock_bounds=None,
                  recheck_sleep: float = 3.0) -> RoundtripReport:
    """5축 왕복 1회.

    Args:
        snapshot_fn: () -> Snapshot. 마켓에서 되읽기(GET).
        apply_fn:    (changes: dict) -> None. 마켓에 쓰기(PUT/POST).
        journal:     .write(Snapshot) / .close(ok, note) / .path
        axes:        시험할 축 이름들
        on_sale_fn:  () -> bool. True 면 거부(판매중 상품 보호)
        image_url_fn:() -> str. **실제로 CDN 에 올린** 시험 이미지 URL.
                     없으면 이미지 축은 확인불가 — 가짜 URL 을 지어내지 않는다.
        approval_axes: 그 마켓에서 **승인 후 반영**되는 축들(쿠팡 상품명·상세·이미지 등).
                     보낸 직후 되읽으면 옛 값이라, 「안 바뀜=실패」로 적으면 거짓 보고가 된다.
                     이 축은 확인불가(None) + 「승인 후 반영」 비고로 남긴다.
                     ★ 원복 전송은 승인 축이라도 **똑같이 보낸다** — 안 보내면 승인이
                       나는 순간 시험값이 라이브에 뜬다.
    """
    report = RoundtripReport()

    # 1) 변경 전 되읽기
    before = snapshot_fn()
    report.before = before

    # 2) 판매중 상품 보호 — **명시적으로 켤 때만** 통과(기본은 거부).
    #    사장님 확정(2026-08-07): 판매중 상품으로 가격 +100원·재고 +1 만 왕복.
    #    폭이 작고 즉시 되돌리므로 위험이 작다 — 다만 실수로 켜지지 않게 옵트인.
    if not allow_on_sale and on_sale_fn is not None and on_sale_fn():
        report.refusal = ("판매중인 상품입니다 — 기본은 판매중지 상품에만 합니다. "
                          "판매중 상품으로 하려면 allow_on_sale 을 켜 주세요.")
        return report

    # 3) 저널 먼저 — 여기 실패하면 전송하지 않는다
    try:
        journal.write(before)
    except Exception as e:  # noqa: BLE001
        report.refusal = (f"저널(원복 보험)을 쓰지 못해 전송을 멈췄습니다: {e} "
                          f"— 저널 없이 보내면 중간에 죽었을 때 되돌릴 근거가 없습니다.")
        return report
    report.journal_path = str(getattr(journal, "path", "") or "")

    # 4) 시험할 축 고르기 — 못 읽는 축은 건드리지 않는다(원복 불가)
    results: dict[str, AxisResult] = {}
    testable: list[str] = []
    test_image = None
    image_error = None
    if "image_urls" in axes and image_url_fn is not None:
        try:
            test_image = image_url_fn()
        except Exception as e:  # noqa: BLE001
            # 사유를 보고서에 담는다 — 「확인불가」만 있고 왜인지가 없으면
            # 사장님이 원인을 못 찾는다(2026-08-06 라이브 1차에서 실제로 겪음).
            image_error = f"{type(e).__name__}: {e}"
            logger.warning("시험 이미지 준비 실패: %s", image_error)
            test_image = None

    for axis in axes:
        r = AxisResult(axis=axis, label=AXIS_LABELS.get(axis, axis),
                       before=before.value_of(axis))
        if not before.has(axis):
            # 🔴 [2026-08-13] 「마켓이 안 줌」과 「우리가 안 보냄」은 다른 말이다.
            #    읽히는 값인데 마켓 탓을 하면, 없는 제약을 있는 것처럼 굳힌다
            #    (11번가 상품명이 실제로 그랬다 — 읽히는데 「안 준다」고 적혀 나갔다).
            if before.value_of(axis) is not None:
                r.note = (f"확인불가 — 「{r.label}」 은 읽히지만, 되돌려 쓸 안전한 방법이 없어 "
                          f"저희가 보내지 않습니다(마켓이 안 주는 게 아닙니다).")
            else:
                r.note = f"확인불가 — 이 마켓이 「{r.label}」 을 조회로 주지 않습니다(전송 안 함)."
        elif axis == "image_urls" and not test_image:
            why = f" 사유: {image_error}" if image_error else ""
            r.note = ("확인불가 — 올릴 시험 이미지를 준비하지 못했습니다"
                      f"(없는 주소를 지어내 보내지 않습니다).{why}")
        else:
            r.sent = _test_value(axis, before, test_image, bounds=stock_bounds)
            if r.sent is None:
                # 흔들 방향이 없다(상한이자 하한) — 보낼 값을 지어내지 않는다.
                r.note = (f"확인불가 — 현재 「{r.label}」 이 마켓 허용범위"
                          f"{stock_bounds} 의 끝이라 올리지도 내리지도 못합니다(전송 안 함).")
            else:
                testable.append(axis)
        results[axis] = r

    changes = {a: results[a].sent for a in testable}

    # 🔴 [2026-08-13] **보낸 값을 저널에 적는다.** 손복구가 「이게 우리 시험값인가」를
    #    주소 모양·낱말로 짐작하다 틀렸다(스마트스토어 시험사진을 못 알아봄).
    #    보낸 값을 그대로 적어 두면 짐작할 필요가 없다 — 지금 값과 같으면 우리 것이다.
    try:
        journal.record_sent(changes)
    except AttributeError:
        pass                      # 옛 저널 객체 호환 — 없으면 옛 방식(짐작)으로 떨어진다

    # 5) 전송 → 되읽기 → 검사. 실패해도 원복은 반드시 돈다.
    try:
        if changes:
            apply_fn(changes)
            after = snapshot_fn()
            # 🔴 [2026-08-07 라이브] 쿠팡 재고는 **반영이 지연**된다 — 보내고 즉시 읽으면
            #    아직 옛 값이다. 한 번 읽고 「안 바뀜」으로 단정하면 거짓 보고가 된다.
            #    안 맞는 축이 있으면 잠깐 기다렸다 **한 번 더** 읽는다(그래도 안 맞으면 실패).
            if any(not _changed_ok(a, results[a].sent, after.value_of(a)) for a in testable):
                if recheck_sleep:
                    import time as _t
                    _t.sleep(recheck_sleep)
                after = snapshot_fn()
            for a in testable:
                r = results[a]
                r.after = after.value_of(a)
                ok = _changed_ok(a, r.sent, r.after)
                if ok:
                    r.changed_ok = True
                elif a in approval_axes:
                    # 이 마켓은 이 축을 승인 후 반영한다 — 「안 바뀜」이 곧 실패가 아니다.
                    r.changed_ok = None
                    r.note = ("보냈습니다. 이 마켓은 이 축을 **승인 후 반영**해서 "
                              "지금 되읽으면 아직 옛 값입니다(확인불가 — 실패 아님).")
                else:
                    r.changed_ok = False
                    r.note = (f"보냈는데 마켓 값이 안 바뀌었습니다 — "
                              f"보낸값={r.sent!r} 마켓값={r.after!r}")
    except Exception as e:  # noqa: BLE001
        report.send_error = f"{type(e).__name__}: {e}"
        logger.exception("왕복 시험 전송 실패 — 원복으로 넘어갑니다")
        for a in testable:
            if results[a].changed_ok is None:
                results[a].changed_ok = False
                results[a].note = f"전송 중 실패: {report.send_error}"
    finally:
        # 6) 원복 — **마켓이 준 값**으로. 예외가 났어도 무조건 돈다.
        if changes:
            revert = {a: before.value_of(a) for a in testable}
            try:
                apply_fn(revert)
                restored = snapshot_fn()
                # 원복도 같은 이유로 한 번 더 본다(지연 반영).
                if any(not _restored_ok(a, results[a].before, restored.value_of(a))
                       for a in testable):
                    if recheck_sleep:
                        import time as _t
                        _t.sleep(recheck_sleep)
                    restored = snapshot_fn()
                report.reverted = True
                for a in testable:
                    r = results[a]
                    r.restored = restored.value_of(a)
                    if a in approval_axes and r.changed_ok is None:
                        # 애초에 반영이 안 됐으니 되읽기로는 원복도 확인할 수 없다.
                        # **원복 전송은 이미 나갔다**(승인 나는 순간 원래값이 뜬다).
                        r.restored_ok = None
                        continue
                    r.restored_ok = _restored_ok(a, r.before, r.restored)
                    if not r.restored_ok:
                        r.note = (f"🔴 원복이 안 됐습니다 — 원래값={r.before!r} "
                                  f"지금값={r.restored!r}")
                if any(results[a].restored_ok is False for a in testable):
                    report.reverted = False
                    report.revert_error = "원복 전송은 됐으나 되읽기 값이 원래대로가 아닙니다."
            except Exception as e:  # noqa: BLE001
                report.reverted = False
                report.revert_error = f"{type(e).__name__}: {e}"
                logger.critical("🔴 원복 실패 — 마켓에 시험값이 남아 있습니다. 저널=%s",
                                report.journal_path)
        else:
            report.reverted = True   # 보낸 게 없으니 되돌릴 것도 없다

    if not report.reverted:
        report.recovery_hint = (
            f"🔴 손복구 필요 — 저널 파일의 before 값으로 마켓을 직접 되돌리세요: "
            f"{report.journal_path}")

    tested = [results[a] for a in testable]
    report.axes = tuple(results[a] for a in axes)
    report.ok = bool(
        report.refusal is None
        and report.send_error is None
        and report.reverted
        # 확인불가(None)는 실패가 아니다 — 거짓만 실패로 센다.
        and not any(r.changed_ok is False or r.restored_ok is False for r in tested)
    )
    try:
        journal.close(report.ok, report.revert_error or "")
    except Exception:  # noqa: BLE001
        logger.exception("저널 닫기 실패(왕복 결과에는 영향 없음)")
    return report
