# -*- coding: utf-8 -*-
"""소싱처 URL → 등록 초안 자동 생성 — POST /bulk/api/drafts/from-url.

지금까지 초안은 수기 폼 하나로만 만들었다. 크롤이 이미 가져다 둔 값(상품명·옵션·재고·
카테고리·이미지·상세)을 사람이 다시 옮겨 적고 있었던 셈이다. 이 라우트가 그 다리다.

★ 여기서 크롤을 돌리지 않는다.
  크롤 = 로컬 PC, 업로드 = 서버 (CLAUDE.md 데이터 정합성 원칙 3). 서버가 소싱처에
  접속하면 IP·속도 제한·차단 문제가 생기고, 무엇보다 설계가 아니다. 그래서 크롤 결과가
  없으면 **404 + "먼저 크롤이 돌아야 합니다"** 로 끝낸다 — 조용히 빈 초안을 만들지 않는다.

★ 만들자마자 「어느 마켓에 뭐가 부족한지」까지 돌려준다.
  등록 사전 점검(preflight)과 **같은 함수**를 쓴다 — 두 화면이 다른 답을 내면 그게 모순이다.

★ 갱신이면 **무엇을 덮었는지**까지 돌려준다 (`changes`).
  「기존 초안을 갱신했습니다」 한 줄로 끝내면, 사람이 넣은 값이 덮여도 아무도 모른다
  (2026-07-23 리뷰 I3 — C1·I1 이 조용한 실패가 됐던 근본 이유).
"""
# [2026-07-23] 크롤 → 등록 초안 자동 생성 (라우트)
from flask import jsonify, request
from sqlalchemy.exc import IntegrityError

from shared.db import SessionLocal
from lemouton.registration import draft_from_crawl as DFC
from lemouton.registration.draft_from_crawl import (
    AmbiguousSourceUrl, DraftFromCrawlError, DraftLocked, SourceNotCrawled,
)
from lemouton.registration.service import MARKETS
# M4 가공 규칙 — 규칙 조회는 process_policy, 적용은 순수함수 process_apply.
from lemouton.registration import process_apply as PA
from lemouton.registration.process_policy import resolve_rules_for_draft
from . import bp
from .drafts import _draft_detail, _err, preflight_rows

#: 한 번에 받을 수 있는 URL 수. 초안 생성은 순수 변환이지만 URL 마다 6마켓 사전 점검을
#: 돌리므로(컴파일 6회 × N) 무제한으로 열면 요청 하나가 워커를 오래 붙든다.
MAX_URLS = 50


def _one(session, url, *, site=None, sale_price=None, markets=None):
    """URL 1건 → 결과 dict. 예외는 여기서 잡아 행 단위 실패로 만든다
    (복수 요청에서 한 건이 실패해도 나머지가 조용히 사라지면 안 된다)."""
    row = {'url': url, 'ok': False}
    try:
        sp = DFC.find_source_product(session, url, site=site)
    except SourceNotCrawled as e:
        row.update(error=str(e), code='NOT_CRAWLED')
        return row
    except (AmbiguousSourceUrl, DraftFromCrawlError) as e:
        row.update(error=str(e), code='BAD_URL')
        return row

    try:
        draft = DFC.build_draft_from_source(session, sp, sale_price=sale_price)
    except DraftLocked as e:
        row.update(error=str(e), code='LOCKED', draft_id=e.draft.id,
                   draft=_draft_detail(e.draft))
        return row

    created = draft.id is None

    # ── M4 가공 규칙 — 초안을 만든 **직후**, 저장(flush) 전 ────────────────────
    #   ★ 여기서는 **드래프트에 쓰지 않는다.** 가공은 컴파일 직전에 만드는 읽기 전용
    #     사본에서만 일어난다(prepare_compile_draft). 초안에 미리 써 넣으면
    #     ① 사장님이 다듬은 값과 프로그램이 만든 값이 뭉개지고
    #     ② 재크롤 때 이미 가공된 이름 위에 또 얹혀 「나이키 나이키 …」가 된다.
    #     그래서 여기서는 **미리보기와 사유**만 만들어 응답에 싣는다.
    #   ★ 규칙 조회는 DB 를 읽는다 → autoflush 로 이 초안이 먼저 저장되면
    #     아래 「수집 금지어」 취소가 불가능해진다. no_autoflush 로 막는다.
    #   market='' — 이 시점엔 어느 마켓에 올릴지 모른다. 마켓별 규칙은 등록·점검 때.
    #   ★ [리뷰 I5] 수집 금지어는 브랜드가 비어 정책을 못 고르는 상태에서도 돌아야
    #     한다(크롤 초안은 브랜드가 대개 빈다) — 그래서 소싱처 단위로 따로 받아 넣는다.
    with session.no_autoflush:
        proc_rules, proc_notes, collect_words = resolve_rules_for_draft(session, draft, '')
    proc_view, proc_applied, proc_skipped = PA.apply_rules(
        draft, proc_rules, market='', collect_banned_words=collect_words)
    proc_skipped = list(proc_notes) + list(proc_skipped)

    # 「수집 금지어」는 어느 마켓에도 안 올린다 → **초안 자체를 만들지 않는다.**
    #   (설계서 §7-1 「수집 금지: 이 단어가 있으면 아예 안 가져옵니다」)
    if PA.has_code(proc_skipped, 'COLLECT_BANNED'):
        why = ' / '.join(s['reason'] for s in proc_skipped
                         if s['code'] == 'COLLECT_BANNED')
        if created:
            session.expunge(draft)      # 아직 flush 전이라 없던 일로 만들 수 있다
            row.update(error=why, code='COLLECT_BANNED')
            return row
        # 이미 있던 초안이면 지우지 않는다(사장님이 만든 것일 수 있다) — 대신 사유를
        # 그대로 실어 보내고, 사전 점검·등록이 같은 판정기로 모든 마켓을 막는다.
        row.update(error=why, code='COLLECT_BANNED', draft_id=draft.id)
        return row

    session.flush()          # id 를 얻는다. 커밋은 라우트가 한 번에.

    source_options = DFC._load_options(session, sp)
    report = DFC.fill_report(sp, draft, source_options)
    row.update(
        ok=True, created=created, draft_id=draft.id,
        source_site=sp.site, source_url=draft.source_url,
        filled=report['filled'], warnings=report['warnings'],
        # ★ [리뷰 I3] 갱신이 무엇을 덮었는지 — 화면이 접지 않고 그대로 보여준다.
        changes=report['changes'],
        human_only=report['human_only'],
        # ★ [M4] 가공 규칙이 이 초안에 무엇을 하는지 — 만들자마자 보여준다.
        #   name = 마켓 공통 규칙으로 만든 **미리보기**(저장값 아님).
        process={'applied': proc_applied, 'skipped': proc_skipped,
                 'name': str(getattr(proc_view, 'name', '') or ''),
                 'tags': list(getattr(proc_view, 'process_tags', []) or [])},
        missing=preflight_rows(session, draft, markets or list(MARKETS)),
    )
    return row


@bp.post('/api/drafts/from-url')
def draft_from_url():
    """소싱처 URL(들) → 등록 초안.

    body:
      url    : 'https://...'          (단건)
      urls   : ['https://...', ...]   (복수 — 최대 50)
      site   : 'musinsa'              (같은 URL 이 여러 소싱처에 있을 때만 필요)
      sale_price : 판매가를 이미 아는 경우에만. **크롤 매입가를 넣지 말 것**
                   (안 주면 「판매가 미정」으로 두고 사전 점검이 빨간불로 알린다)
      markets: ['smartstore', ...]    생략하면 6마켓 전부 점검

    응답(단건):
      {ok, draft_id, created, filled:{...}, warnings:[...], human_only:[...],
       missing:[{market,status,reason,...}]}
    응답(복수): {ok, rows:[위 dict + url]}
    """
    p = request.get_json(silent=True) or {}

    urls = p.get('urls')
    many = isinstance(urls, list)
    if not many:
        one = p.get('url')
        if not isinstance(one, str) or not one.strip():
            return _err('소싱처 상품 URL 을 보내 주세요 (url 또는 urls).')
        urls = [one]
    urls = [str(u).strip() for u in urls if str(u or '').strip()]
    if not urls:
        return _err('소싱처 상품 URL 을 보내 주세요 (url 또는 urls).')
    if len(urls) > MAX_URLS:
        return _err(f'한 번에 {MAX_URLS}개까지 됩니다 (받은 값: {len(urls)}개).')

    markets = p.get('markets')
    if markets is not None:
        if not isinstance(markets, list):
            return _err('markets 는 배열이어야 합니다.')
        unknown = [m for m in markets if m not in MARKETS]
        if unknown:
            return _err(f'모르는 마켓입니다: {unknown} — {list(MARKETS)} 중에서 골라 주세요.')

    sale_price = p.get('sale_price')
    if sale_price is not None:
        from lemouton.registration.compile_common import coerce_int, CompileError
        try:
            sale_price = coerce_int(sale_price, '판매가')
        except CompileError as e:
            return _err(str(e))
        if sale_price is not None and sale_price <= 0:
            return _err('판매가가 0원 이하입니다 — 비워 두면 「판매가 미정」으로 만듭니다.')

    site = (p.get('site') or '').strip() or None

    def _run(session):
        rows = [_one(session, u, site=site, sale_price=sale_price, markets=markets)
                for u in urls]
        if any(r.get('ok') for r in rows):
            session.commit()
        else:
            session.rollback()
        return rows

    s = SessionLocal()
    try:
        try:
            rows = _run(s)
        except IntegrityError:
            # ★ [리뷰 I4] 동시 요청(gunicorn 워커 3개)이 같은 URL 초안을 2벌 만들려다
            #   부분 유니크 인덱스(uq_product_drafts_source_url_live)에 걸린 경우다.
            #   되돌리고 **한 번만** 다시 돈다 — 이번엔 남이 만든 초안이 보이므로
            #   삽입이 아니라 갱신 경로를 탄다(유령 초안이 안 생긴다).
            s.rollback()
            rows = _run(s)
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()

    if many:
        return jsonify({'ok': True, 'rows': rows,
                        'made': sum(1 for r in rows if r.get('ok'))})
    row = rows[0]
    if not row.get('ok'):
        # 크롤이 아직 안 돈 건 「없는 것」이라 404, 나머지는 요청 문제라 400.
        return jsonify({'ok': False, 'error': row.get('error'),
                        'code': row.get('code'), 'draft_id': row.get('draft_id')}), \
            (404 if row.get('code') == 'NOT_CRAWLED' else 400)
    return jsonify({'ok': True, **{k: v for k, v in row.items() if k != 'ok'}})
