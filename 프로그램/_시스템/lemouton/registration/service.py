# -*- coding: utf-8 -*-
"""드래프트 등록 — 컴파일 → 마켓 호출 → ProductDraftMarket 기록.

원칙:
  · 성공 판정은 '마켓 상품ID 를 받았는가' 로만 한다. 200/code=SUCCESS 를 믿지 않는다
    (이 프로젝트의 반복 사고: 11번가 -3313, 쿠팡 vendorItemId 조용한 {}).
  · 실등록은 LIVE_REGISTER_ARMED=1 일 때만. 기본 OFF.
  · 컴파일 실패면 마켓을 호출하지 않는다.
"""
import json
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from lemouton.registration.models import ProductDraft, ProductDraftMarket
from lemouton.registration.compile_smartstore import compile_smartstore
from lemouton.registration.compile_coupang import compile_coupang
# CompileError 는 두 컴파일러가 compile_common 에서 재노출하는 단일 클래스다.
# 정본을 직접 잡으면 나중에 롯데온·11번가 컴파일러(Phase 4)가 같은 예외를 던져도 자동 포함.
from lemouton.registration.compile_common import CompileError, loads_json
# M4-3 고시 기본값 — 저장값은 그대로 두고 **컴파일에 넘길 사본**에만 병합한다.
from lemouton.registration.notice_defaults import apply_notice_defaults
# M4 가공 규칙 — 같은 규율(저장값 불변·적용 시점 사본).
from lemouton.registration import process_apply as PA
from lemouton.registration.process_policy import resolve_rules_for_draft

logger = logging.getLogger(__name__)

MARKETS = ('smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon')
#: 2026-07-21 실등록 검증으로 추가된 4마켓 — compile_more/send_more 경로를 탄다.
MARKETS_MORE = ('auction', 'gmarket', 'eleven11', 'lotteon')


class RegisterBlocked(RuntimeError):
    """LIVE_REGISTER_ARMED 가 꺼져 실등록을 막았다."""


def prepare_compile_draft(session, draft, market: str = '', *, gate=None):
    """컴파일에 넘길 **읽기 전용 사본** — 가공 규칙 + 고시 기본값을 이 순서로 얹는다.

    ★ 사전 점검(preflight_rows)과 실제 등록(register_draft)이 **같은 사본**을 쓰게 하는
      단일 지점이다. 두 화면이 서로 다른 판정을 내놓으면 그게 곧 모순이라고
      `webapp/routes/bulk/drafts.py::preflight_rows` docstring 이 못 박아 뒀다.
      복붙하지 않고 여기 하나를 부른다.

    ★ 저장된 드래프트는 손대지 않는다 — 가공도 고시도 사본에서만 일어난다.

    Args:
        gate: `process_policy.source_gate` 결과. 6마켓을 도는 호출자가 드래프트당
            한 번만 읽게 하려고 받는다(리뷰 I-7). 안 주면 여기서 만든다.

    Returns:
        (compile_draft, info)
        info = {'applied': [...], 'skipped': [...], 'notice_filled_from': {...}}
        `skipped` 에 `blocking=True` 가 하나라도 있으면 **그 상태로 등록하면 안 된다.**
    """
    rules, notes, collect_words = resolve_rules_for_draft(session, draft, market,
                                                          gate=gate)
    # 수집 금지어는 브랜드·마켓과 무관한 소싱처 단위 게이트라 따로 주입한다(리뷰 I5).
    view, applied, skipped = PA.apply_rules(draft, rules, market=market,
                                            collect_banned_words=collect_words)
    skipped = list(notes) + list(skipped)
    view, filled_from = apply_notice_defaults(session, view)
    return (view, {'applied': applied, 'skipped': skipped,
                   'notice_filled_from': filled_from})


class RegisterUnknown(RuntimeError):
    """마켓 호출을 **시도한 뒤** 우리 쪽에서 터졌다 — 상품이 생겼을 수 있다.

    ★ [2026-07-24 4차리뷰 중요②] 전송 뒤 구간에서 나는 예외는 「실패」가 아니다.
      대표 경로가 `session.commit()` 실패다 — 마켓에는 상품이 만들어졌는데 장부는
      롤백된다. 그걸 화면이 「실패」로 보여주면 다음 점검이 그 마켓을 ready 로 내주고,
      한 번 더 누르면 같은 상품이 두 개가 된다. 상위(_register_one)가 이 예외를
      **확인 필요**로 다룬다.
    """


def _commit_after_send(session, market, e_ctx=''):
    """마켓 호출이 **나간 뒤**의 커밋 — 실패하면 RegisterUnknown 으로 올린다.

    전송 전 커밋(컴파일 실패·게이트 차단 기록)은 그냥 `session.commit()` 을 쓴다.
    그 시점엔 마켓에 아무것도 안 갔으니 실패해도 「모른다」가 아니기 때문이다.
    """
    try:
        session.commit()
    except Exception as e:      # noqa: BLE001
        try:
            session.rollback()
        except Exception:       # noqa: BLE001
            pass
        logger.exception('전송 뒤 장부 커밋 실패 market=%s %s', market, e_ctx)
        raise RegisterUnknown(
            f'{market} 마켓 호출은 나갔는데 그 결과를 기록하지 못했습니다 — 상품이 '
            f'만들어졌는지 모릅니다. 마켓에서 직접 확인해 주세요. 원문: {e!r}') from e


def _armed() -> bool:
    return os.environ.get('LIVE_REGISTER_ARMED') == '1'


#: 전송 계층 실패의 3분류 — **화면 문구가 아니라 이 코드로** 판정한다.
#:   PREREQ  보내기 전에 확정된 실패(상품 미생성 확실) → status='failed'
#:   PARTIAL 상품은 만들어졌는데 뒤 단계 실패(상품번호를 안다) → status='uncertain'
#:   CALL    보낸 뒤(또는 보냈는지 모르는 채) 끊김 → status='uncertain'
#: [2026-07-23 리뷰 I-B] 예전엔 전송 계층 예외를 전부 CALL 로 뭉갰다. 그러면 계정 없음·
#: 출고지 미등록 같은 확정 실패까지 「올라갔는지 모릅니다」로 떠서, 확인할 것도 없는
#: 경고가 상시로 뜨고 **진짜 유령 경고가 그 속에 묻힌다.**
SEND_FAIL_PREREQ = 'PREREQ'
SEND_FAIL_PARTIAL = 'PARTIAL'
SEND_FAIL_CALL = 'CALL'
#: 마켓이 **응답은 줬는데** 우리가 상품ID 를 못 찾은 경우 — 이것도 「모른다」다.
#: [2026-07-23 3차리뷰] 이 저장소의 실패 이력이 정확히 이 군이다(11번가 -3313 ·
#: 쿠팡 vendorItemId 조용한 {}). 상품은 만들어졌는데 우리 파서가 못 읽었을 수 있고,
#: 그걸 'failed' 로 적으면 다음 점검이 ready 로 내줘 같은 상품이 두 개가 된다.
SEND_FAIL_NO_ID = 'NO_PRODUCT_ID'

#: 장부 status — 'uncertain' = 「등록됨」도 「실패」도 아니고 **확인 전까지 잠금**.
LEDGER_UNCERTAIN = 'uncertain'


def _classify_send_failure(e):
    """전송 계층 예외 → (error_code, 아는 상품번호).

    ★ 「보내기 전」이라고 **확실히 아는 것만** PREREQ 다. 나머지는 전부 CALL(모른다) —
      연결 실패인지 응답 대기 중 끊김인지 일반적으로 구분할 수 없기 때문이다.
      모르는 것을 안다고 말하지 않는다.
    """
    from lemouton.registration.send_more import PrereqError, PartialRegisterError
    if isinstance(e, PartialRegisterError):
        return SEND_FAIL_PARTIAL, e.product_id
    if isinstance(e, (PrereqError, CoupangAccountMismatch)):
        return SEND_FAIL_PREREQ, None
    return SEND_FAIL_CALL, None


def _write_send_failure(session, draft, row, e):
    """전송 실패를 장부에 적는다 → {'ok': False, ...} 결과 dict.

    ★ [리뷰 C-2] 상품이 만들어졌을 수 있는 실패(PARTIAL·CALL)는 장부 status 를
      'uncertain' 으로 남긴다. 'failed' 로 적으면 다음 「점검」에서 그 마켓이 다시
      ready 로 나오고, 한 번 더 누르면 같은 상품이 두 개가 된다.
    """
    code, pid = _classify_send_failure(e)
    row.error_code = code
    row.error_message = str(e)
    if code == SEND_FAIL_PREREQ:
        row.status = 'failed'
        draft.status = 'failed'
    else:
        row.status = LEDGER_UNCERTAIN
        # 아는 상품번호는 반드시 남긴다 — 이게 없으면 유령을 찾을 단서가 사라진다.
        # ★ [3차리뷰 중요②] 새 번호로 덮기 전에 **이전 번호를 원문에 남긴다.**
        #   불확실(A) → 다시 올리기 → 새 상품 B 생성 후 또 실패 이면, 이 보존이 없으면
        #   A 가 장부에서도 원문에서도 사라지는데 마켓엔 살아 있다(영영 못 찾는다).
        if pid:
            keep = _keep_previous_product_id(row, {'partial_error': str(e)[:500]})
            try:
                row.raw_json = json.dumps(keep, ensure_ascii=False, default=str)[:20000]
            except Exception:   # noqa: BLE001 — 기록 실패가 등록 흐름을 죽이면 안 된다
                pass
            row.market_product_id = pid
        # 드래프트 전체를 'failed' 로 단정하지 않는다(마켓 하나가 불확실한 것뿐이다).
    if code == SEND_FAIL_PREREQ:
        session.commit()        # 보내기 전 확정 실패 — 커밋 실패해도 「모른다」가 아니다
    else:
        _commit_after_send(session, row.market, 'send-failure')
    return {'ok': False, 'market_product_id': (pid or row.market_product_id),
            'error': str(e), 'error_code': code}


def _keep_previous_product_id(row, raw):
    """상품번호가 **바뀌는** 등록이면 이전 번호를 원문에 함께 남긴다.

    [리뷰 I-F] 「다시 올리기」는 같은 장부 행을 덮어쓴다. 지웠다고 믿고 다시 올렸는데
    실제로는 남아 있었으면 상품이 둘 다 살아 있는데 장부는 새 번호만 안다 — 이전 번호를
    잃으면 되돌릴 방법이 없다. 바뀔 때만 감싸므로 평소 raw_json 모양은 그대로다.
    """
    prev = (row.market_product_id or '').strip()
    return raw if not prev else {'previous_market_product_id': prev, 'raw': raw}


def _row(session, draft_id: int, market: str, account_key: str) -> ProductDraftMarket:
    """드래프트 × 마켓 × 계정 행. 재시도해도 행이 늘지 않게 upsert.

    ★ account_key 를 빼면 안 된다 — 같은 상품을 같은 마켓의 다른 계정에 올릴 때
      한 행을 덮어써 앞 계정의 market_product_id 가 조용히 사라진다. 그러면 Phase 2
      가격·재고 자동갱신이 엉뚱한 계정으로 나간다 (설계서 §7-13).
    """
    row = (session.query(ProductDraftMarket)
           .filter_by(draft_id=draft_id, market=market, account_key=account_key).first())
    if row is None:
        row = ProductDraftMarket(draft_id=draft_id, market=market, account_key=account_key)
        session.add(row)
        try:
            session.flush()
        except IntegrityError:
            # 같은 키를 다른 요청이 방금 만들었다(UNIQUE 경합) — 그 행을 다시 읽어 쓴다.
            # 예외로 터뜨리면 등록 결과가 통째로 사라진다(장부 없는 유령의 시작).
            session.rollback()
            row = (session.query(ProductDraftMarket)
                   .filter_by(draft_id=draft_id, market=market,
                              account_key=account_key).first())
            if row is None:
                raise
    return row


def _extract_product_id(market: str, resp: dict):
    """마켓 응답 → 상품ID. 없으면 None (= 실패)."""
    if not isinstance(resp, dict):
        return None
    if market == 'smartstore':
        v = resp.get('originProductNo')
    else:
        # 쿠팡 create_product 는 성공 시 sellerProductId(int) 를 data 에 담는다
        v = resp.get('data') if isinstance(resp.get('data'), int) else resp.get('sellerProductId')
    return str(v) if v else None


def _send_live(market: str, body: dict, _client=None) -> dict:
    """실제 마켓 호출. 스스는 등록 직후 SUSPENSION(초안) 전환까지 한다.

    스스 서버는 요청의 statusType 을 무시하고 항상 SALE 로 등록한다 →
    mark_suspension 을 안 부르면 검증 전 상품이 바로 판매중이 된다.

    Args:
        _client: 테스트용 주입점. 실서비스에서는 None → SmartStoreClient().
    """
    if market == 'smartstore':
        from shared.platforms.smartstore.client import SmartStoreClient
        from shared.platforms.smartstore.change_status import mark_suspension
        c = _client or SmartStoreClient()
        resp = c.request(method='POST', path=c.path_for('create_product'), body=body)
        origin_no = resp.get('originProductNo')
        if origin_no:
            # ★ 상품은 이미 SmartStore 에 생성됐다(스스는 항상 SALE 로 등록). 이 뒤에
            #   무슨 일이 나도 상품ID 를 잃으면 안 된다 — mark_suspension 은 429 에
            #   SmartStoreRateLimitError 를 re-raise 하고 네트워크·디코드 오류도 그대로
            #   던진다. 그 예외를 여기서 삼키지 않으면 register_draft 가 이 건을
            #   'failed·ID없음' 으로 기록하고, 판매중인 실상품이 우리 DB 밖에서 미아가
            #   된다(가격·재고 갱신 불가·내려받기 불가). SUSPENSION 전환은 best-effort.
            try:
                sus = mark_suspension(int(origin_no), client=c)
                if not sus.success:
                    # 등록 자체는 성공했다 — 판매중으로 남았다는 사실을 숨기지 않는다.
                    logger.warning('SUSPENSION 전환 실패 originProductNo=%s %s %s — '
                                   '상품이 판매중 상태로 남았습니다.',
                                   origin_no, sus.error_code, sus.error_message)
                    resp['_suspend_failed'] = True
            except Exception:
                logger.exception('SUSPENSION 전환 예외 originProductNo=%s — '
                                 '상품이 판매중 상태로 남았습니다.', origin_no)
                resp['_suspend_failed'] = True
        return resp
    # ★ [2026-07-23 리뷰 I2] payload 의 vendorId 와 **실제 서명에 쓰이는 계정**이 같은지
    #   확인한 뒤에만 보낸다. 설정 카드·resolve_env_prefix·전송 클라이언트가 각자 다른
    #   「기본 계정」을 가리키던 탓에, 계정이 둘 이상이면 「payload 는 A 계정, 서명은 B
    #   계정」이 나갈 수 있었다 — 남의 셀러 반품지로 등록되는 금전 사고다.
    _assert_coupang_account_matches(body)
    from shared.platforms.coupang.products import create_product
    return {'data': create_product(body)}


class CoupangAccountMismatch(RuntimeError):
    """등록 payload 의 판매자와 실제 전송(서명) 계정이 다르다 — 보내면 안 된다."""


def _sending_coupang_vendor_id() -> str:
    """지금 `create_product` 가 쓰는 클라이언트(무접두사 COUPANG_*)의 판매자 ID."""
    from shared.platforms import COUPANG
    return str(COUPANG.get('vendor_id') or '').strip()


def _assert_coupang_account_matches(body: dict) -> None:
    """payload 계정 ≠ 전송 계정이면 **호출 전에** 막는다(조용한 불일치 금지)."""
    payload_vendor = str((body or {}).get('vendorId') or '').strip()
    sending = _sending_coupang_vendor_id()
    if not sending:
        raise CoupangAccountMismatch(
            '전송에 쓰이는 쿠팡 계정의 판매자 ID(COUPANG_VENDOR_ID)를 확인할 수 없습니다 — '
            '어느 계정으로 나가는지 모른 채 등록할 수 없습니다.')
    if payload_vendor != sending:
        raise CoupangAccountMismatch(
            f'등록 내용은 판매자 {payload_vendor!r} 인데 실제 전송 계정은 {sending!r} 입니다 — '
            f'다른 계정의 반품지로 등록될 수 있어 막았습니다. 설정 탭에서 「지금 등록에 '
            f'쓰이는 계정」의 계정정보를 저장해 주세요.')


def _register_more(session, draft, row, market: str, *, category_code,
                   account_key: str = 'default', _send=None,
                   compile_draft=None) -> dict:
    """옥션·G마켓·11번가·롯데온 등록 — compile_more(순수 검증)→게이트→send_more(수확·조립·호출).

    스스·쿠팡과 같은 장부 규약: blocked/failed/ok 를 row 에 기록, 성공=상품ID 수령만.
    _send: 테스트 주입점 — _send(market, spec) -> {'product_id': str, ...}.
    compile_draft: 가공 규칙·고시 기본값을 얹은 **읽기 전용 사본**(prepare_compile_draft).
        컴파일에만 쓴다 — 상태 기록(draft.status)은 원본 `draft` 에 해야 한다
        (사본은 쓰기가 막혀 있고, 애초에 DB 에 안 남는다).
    """
    from lemouton.registration.compile_more import (
        compile_auction_gmarket, compile_eleven11, compile_lotteon)

    src = compile_draft if compile_draft is not None else draft

    # 1) 예비 컴파일(순수) — 실패면 마켓 호출 없음
    try:
        if market in ('auction', 'gmarket'):
            spec, excluded = compile_auction_gmarket(src, category_code=category_code)
        elif market == 'eleven11':
            spec, excluded = compile_eleven11(src, category_code=category_code)
        else:
            spec, excluded = compile_lotteon(src, category_code=category_code)
    except CompileError as e:
        row.status = 'failed'
        row.error_code = 'COMPILE'
        row.error_message = str(e)
        draft.status = 'failed'
        session.commit()
        return {'ok': False, 'market_product_id': None, 'error': str(e)}

    # 2) 라이브 게이트 — 스스·쿠팡과 동일
    if _send is None and not _armed():
        row.status = 'blocked'
        row.error_code = 'LIVE_OFF'
        row.error_message = ('실등록이 꺼져 있습니다 (LIVE_REGISTER_ARMED=1 이어야 함). '
                             '컴파일은 통과했습니다.')
        session.commit()
        raise RegisterBlocked(row.error_message)

    # 3) 선행자원 수확 + 조립 + 호출 (send_more — 게이트 뒤)
    try:
        if _send is not None:
            result = _send(market, spec)
        else:
            from lemouton.registration.send_more import register_live
            result = register_live(market, spec, account_key)
    except Exception as e:  # noqa: BLE001 — PrereqError·마켓 거부 전부 표면화
        logger.exception('%s 등록 호출 실패 draft_id=%s', market, draft.id)
        # 보내기 전(PREREQ) / 상품 생성 뒤 실패(PARTIAL) / 끊김(CALL) 을 갈라 적는다.
        return _write_send_failure(session, draft, row, e)

    # 4) 성공 판정 — 상품ID 가 있어야만 성공(거짓 성공 금지)
    pid = str((result or {}).get('product_id') or '') or None
    try:
        row.raw_json = json.dumps(_keep_previous_product_id(row, (result or {}).get('raw')),
                                  ensure_ascii=False, default=str)[:20000]
    except Exception:  # noqa: BLE001
        row.raw_json = None
    if not pid:
        # ★ [2026-07-23 3차리뷰 중요①] 「응답은 왔는데 상품ID 를 못 찾았다」는 실패가
        #   아니라 **모른다**다. 상품은 만들어졌는데 우리 파서가 못 읽었을 수 있다
        #   (이 저장소 이력: 11번가 -3313 · 쿠팡 vendorItemId 조용한 {}).
        #   'failed' 로 적으면 다음 점검이 ready 로 내줘 같은 상품이 두 개가 된다.
        msg = ('마켓이 상품ID 를 주지 않았습니다 — 올라갔는지 모릅니다(응답은 왔습니다). '
               f'마켓에서 직접 확인해 주세요. 응답: {result!r}')
        row.status = LEDGER_UNCERTAIN
        row.error_code = SEND_FAIL_NO_ID
        row.error_message = msg
        _commit_after_send(session, market, 'no-product-id')
        return {'ok': False, 'market_product_id': None, 'error': msg,
                'error_code': SEND_FAIL_NO_ID}

    row.status = 'ok'
    row.market_product_id = pid
    row.error_code = None
    row.error_message = None
    row.registered_at = datetime.now(timezone.utc)
    draft.status = 'done'
    _commit_after_send(session, market, 'success')
    return {'ok': True, 'market_product_id': pid, 'error': None, 'excluded': excluded}


def register_draft(session, draft_id: int, market: str, *,
                   category_code, vendor: dict = None,
                   account_key: str = 'default', _send=None, _prepare=None) -> dict:
    """드래프트 1건을 마켓 1곳(계정 1개)에 등록한다.

    Args:
        account_key: 마켓 계정 식별자. Phase 1A 는 단일계정이라 'default' 뿐이지만,
            결과는 계정별로 기록한다 (설계서 §7-13 「타 계정은 별도 설정으로 허용」).
        _send: 테스트용 주입점. 실서비스에서는 None → _send_live.
        _prepare: 이미지 재호스팅(공개 URL→CDN) 주입점. 실서비스에서는 None →
            image_prep.prepare_cdn_images (라이브 fetch+업로드, 게이트 뒤).

    Returns:
        {'ok': bool, 'market_product_id': str|None, 'error': str|None,
         'excluded': list}  — excluded = 품절·확인불가로 등록에서 빠진 옵션

    Raises:
        RegisterBlocked: LIVE_REGISTER_ARMED 가 꺼져 있음 (행은 blocked 로 남긴다)
    """
    if market not in MARKETS:
        raise ValueError(f'market 은 {MARKETS} 중 하나여야 합니다: {market!r}')

    # ★ 거짓 장부 금지 — account_key 는 기록에만 반영돼 있고 실제 전송에는 아직 안 붙는다
    #   (_send_live 가 계정 없이 SmartStoreClient() 를 부른다). 여기서 막지 않으면
    #   'acctB' 로 기록해놓고 호출은 기본 계정으로 나가, DB 가 acctB 소유라고 거짓말한다.
    #   Phase 2 에서 _resolve_env_prefix(market, account_key) 배선 후 이 가드를 푼다.
    #   (라이브 경로 선례: lemouton/sets/set_link_service.py:41)
    #   [2026-07-21 Phase 2] 4마켓(auction·gmarket·eleven11·lotteon)은 send_more 가
    #   account_key→env_prefix 를 실제 배선(없는 계정이면 예외·기본 폴백 금지)하므로 허용.
    #   스스·쿠팡은 여전히 _send_live 가 계정 없이 기본 클라이언트를 불러 가드 유지.
    if account_key != 'default' and market not in MARKETS_MORE:
        raise ValueError(
            f'{market} 는 아직 단일 계정만 됩니다 (받은 값: {account_key!r}) — '
            f'지금 넘기면 기록과 실제 전송 계정이 어긋납니다.')

    draft = session.query(ProductDraft).filter_by(id=draft_id).first()
    if draft is None:
        raise ValueError(f'드래프트를 찾을 수 없습니다: id={draft_id}')

    row = _row(session, draft_id, market, account_key)
    row.category_code = str(category_code)

    # ── M4 가공 규칙 — 컴파일 직전, **6마켓 공통** 자리 ────────────────────────
    #   ★ MARKETS_MORE 분기(_register_more)보다 **앞**이어야 한다. 뒤에 두면 스스·쿠팡만
    #     가공되고 옥션·G마켓·11번가·롯데온은 원본 그대로 올라간다 — 사전 점검(6마켓 전부
    #     같은 함수로 판정)과 답이 갈려 그 자체가 모순이 된다.
    #   ★ 적용 못 한 사유가 하나라도 「막아야 하는 것」이면 마켓을 부르지 않는다
    #     (브랜드 미확정·금지어·브랜드 표기 불가 — 조용히 원본 통과 금지).
    compile_draft, proc = prepare_compile_draft(session, draft, market)
    blocked = PA.blocking_reasons(proc['skipped'])
    if blocked:
        msg = ' / '.join(blocked)
        row.status = 'blocked'
        row.error_code = ('PROCESS_HOLD'
                          if PA.has_code(proc['skipped'], 'NO_BRAND_FOR_RULES')
                          else 'PROCESS_BLOCKED')
        row.error_message = msg
        session.commit()
        return {'ok': False, 'market_product_id': None, 'error': msg,
                'blocked': True, 'reason': msg, 'process': proc,
                # [머지 2026-07-24] _register_one 이 이 코드로 status='blocked' 를 준다
                # (안 주면 가공 보류가 「실패」로 둔갑해 점검(need_brand)과 답이 갈린다).
                'error_code': row.error_code}

    # ── 4마켓(옥션·G마켓·11번가·롯데온) 경로 — 스스·쿠팡 기존 흐름은 그대로 둔다 ──
    if market in MARKETS_MORE:
        return _register_more(session, draft, row, market,
                              category_code=category_code,
                              account_key=account_key, _send=_send,
                              compile_draft=compile_draft)

    # 1) 예비 컴파일 — 실패면 마켓 호출 없음. A/S·옵션·고시 오류를 게이트 앞에서 잡는다.
    #    ★ 스스 CDN 이미지는 라이브 업로드로만 생기고 업로드는 게이트 뒤에서만 돈다.
    #      그래서 여기선 require_cdn_images=False 로 컴파일해(이미지 검사 생략) 게이트 OFF
    #      에서도 비이미지 오류를 보여주고 '실등록 꺼짐' 메시지에 닿게 한다. 진짜 body 는
    #      게이트 뒤에서 이미지 업로드 후 재컴파일(3-1)해 만든다.
    #    excluded = 품절·확인불가로 빠진 옵션. 조용히 버리지 않고 결과에 실어 올린다.
    # M4-3: 고시정보 기본값(전역·소싱처)을 **적용 시점에만** 합친 읽기 전용 사본.
    #   저장된 notice_json 은 손대지 않는다 — 사장님이 입력한 값과 기본값이 뭉개지면
    #   나중에 어느 쪽이 진짜인지 알 수 없다. 기본값이 없으면 원본 draft 그대로다.
    #   [M4 가공] 위 prepare_compile_draft 가 「가공 규칙 → 고시 기본값」 순서로 이미
    #   얹어 뒀다. 여기서 다시 부르면 사본이 두 벌 생겨 어느 쪽이 진짜인지 갈린다.

    try:
        if market == 'smartstore':
            body, excluded = compile_smartstore(compile_draft, category_code=str(category_code),
                                                require_cdn_images=False)
        else:
            # ★ 쿠팡도 **가공된 사본**으로 컴파일한다 — 여기에 draft 를 넣으면 상품명
            #   가공이 쿠팡에만 안 먹어, 사전 점검(가공본 기준)과 답이 갈린다.
            body, excluded = compile_coupang(compile_draft, category_code=int(category_code),
                                             vendor=vendor or {})
    except CompileError as e:
        row.status = 'failed'
        row.error_code = 'COMPILE'
        row.error_message = str(e)
        draft.status = 'failed'
        session.commit()
        return {'ok': False, 'market_product_id': None, 'error': str(e)}

    # 2) 라이브 게이트
    if _send is None and not _armed():
        row.status = 'blocked'
        row.error_code = 'LIVE_OFF'
        row.error_message = ('실등록이 꺼져 있습니다 (LIVE_REGISTER_ARMED=1 이어야 함). '
                             '컴파일은 통과했습니다.')
        session.commit()
        raise RegisterBlocked(row.error_message)

    # 3-1) [게이트 뒤·스스] 폼 이미지를 네이버 CDN 에 재호스팅 → 진짜 body 재컴파일.
    #      게이트를 이미 통과했으므로(2단계) 라이브 업로드가 맞다. 준비 함수는 _prepare 로
    #      주입 가능(테스트). cdn_images_json 이 이미 채워져 있으면(재시도) 업로드 생략.
    #      이미지 준비·재컴파일 실패면 마켓을 호출하지 않는다(마켓 전송 전 단계).
    if market == 'smartstore':
        try:
            existing_cdn = loads_json(draft.cdn_images_json, [], what='CDN이미지')
            if not existing_cdn:
                prepare = _prepare
                if prepare is None:
                    # ★ 라이브 이미지 준비(fetch+업로드)도 arm 게이트 안쪽에서만. _send 게이트가
                    #   보통 먼저 막지만, _send 만 주입하고 _prepare 를 안 넘긴 조합에서 라이브
                    #   호출이 새지 않게 여기서도 arm 을 확인한다('arm 없이 라이브 없음' 불변식).
                    if not _armed():
                        raise RegisterBlocked(
                            '실등록이 꺼져 있습니다 (LIVE_REGISTER_ARMED=1 이어야 이미지 업로드).')
                    from lemouton.registration.image_prep import prepare_cdn_images
                    prepare = prepare_cdn_images
                from lemouton.registration.image_prep import ImagePrepError
                public_urls = loads_json(draft.images_json, [], what='이미지')
                try:
                    cdn_urls = prepare(public_urls)
                except ImagePrepError as e:
                    raise CompileError(f'이미지 업로드 실패 — {e}') from e
                draft.cdn_images_json = json.dumps(cdn_urls, ensure_ascii=False)
            body, excluded = compile_smartstore(compile_draft, category_code=str(category_code),
                                                require_cdn_images=True)
        except CompileError as e:
            row.status = 'failed'
            row.error_code = 'IMAGE'
            row.error_message = str(e)
            draft.status = 'failed'
            session.commit()
            return {'ok': False, 'market_product_id': None, 'error': str(e)}

    send = _send or _send_live

    # 3) 호출
    try:
        resp = send(market, body)
    except Exception as e:
        logger.exception('%s 등록 호출 실패 draft_id=%s', market, draft_id)
        # 쿠팡 계정 불일치는 **호출 전에 막은 것**이라 확정 실패(PREREQ)다. 나머지는
        # 보냈는지 모르므로 CALL(불확실) — 모르는 것을 안다고 말하지 않는다.
        return _write_send_failure(session, draft, row, e)

    # 4) 성공 판정 — 상품ID 가 있어야만 성공
    pid = _extract_product_id(market, resp)
    try:
        row.raw_json = json.dumps(_keep_previous_product_id(row, resp),
                                  ensure_ascii=False, default=str)[:20000]
    except Exception:
        row.raw_json = None

    if not pid:
        # [3차리뷰 중요①] 위와 같은 이유로 **불확실**이다(실패로 단정하지 않는다).
        msg = ('마켓이 상품ID 를 주지 않았습니다 — 올라갔는지 모릅니다(응답은 왔습니다). '
               f'마켓에서 직접 확인해 주세요. 응답: {resp!r}')
        row.status = LEDGER_UNCERTAIN
        row.error_code = SEND_FAIL_NO_ID
        row.error_message = msg
        _commit_after_send(session, market, 'no-product-id')
        return {'ok': False, 'market_product_id': None, 'error': msg,
                'error_code': SEND_FAIL_NO_ID}

    row.status = 'ok'
    row.market_product_id = pid
    row.error_code = None
    row.error_message = None
    row.registered_at = datetime.now(timezone.utc)
    draft.status = 'done'
    _commit_after_send(session, market, 'success')
    # excluded 를 반드시 실어 보낸다 — 사용자가 입력한 옵션이 빠졌는데 화면이 '성공' 만
    # 보여주면 조용한 실패다.
    return {'ok': True, 'market_product_id': pid, 'error': None, 'excluded': excluded}
