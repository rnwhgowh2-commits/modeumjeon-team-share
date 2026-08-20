"""주문 시점 가격 차이 — 「올릴 때 매입가」 vs 「지금 매입가」 3층 대조 (Phase 1B M4).

사장님 확정 요구: "주문 시점에 가격 차이가 있다면 화면에 전후 가격을 전부 표시".

3층이 각각 어디서 오는지 (전부 **호출만** — 계산식은 이 모듈에 없다):
  1층 올릴 때 매입가 = ``uploader.reconcile.last_confirmed_snapshot`` 이 고른
      PriceSnapshot.final_purchase_price. **실제로 마켓이 받은** 스냅샷만
      (action='upload' AND uploaded_at IS NOT NULL) — 전송 실패한 시도는 기준선이
      되지 못한다.
  2층 주문 걸린 판매가 = 주문 행의 `단가`(개당 판매가). 마켓이 준 실값.
  3층 지금 매입가 = ``api_pricing._option_matrix_data`` 의 대표 소싱처(최저 크롤가)
      → ``api_benefits.compute_breakdown`` 의 final_price.

마진 = ``uploader.reconcile.compute_margin_amount`` (기존 함수 그대로).
      = (판매가 − 배송비) × (1 − 수수료율) − 지금매입가.

★ 폴백 절대 금지 — 세 층 중 하나라도 모르면 그 행은 'unknown'(화면 "확인 불가").
  추정가·0원·평균으로 채우지 않는다. 전/후 두 값을 하나로 뭉개지 않는다.

★ N+1 회피 — 행 단위 쿼리가 하나도 없다:
  · 대상 색인(SetChannel⋈SetChannelOption) — **요청이 물어본 번호만** IN 절로
    (2026-08-06까지는 표를 통째로 읽었다. 주문 표 한 판이 이 색인을 세 군데에서 만든다)
  · Option(색상/사이즈) 1회 IN 쿼리
  · PriceSnapshot 1회 IN 쿼리(파이썬에서 대상별 최신 1건 선별)
  · _option_matrix_data 는 **모델코드당** 1회(행당 아님) + 모델코드와 무관한 조회는
    `batch` 그릇으로 요청당 1회 + 뽑은 결과는 짧은 TTL 캐시(_finals_cache)
  · _build_breakdown_cache 1회 → compute_breakdown 은 캐시 재사용
"""
from __future__ import annotations

import logging
import threading as _thr
import time as _time
from collections import defaultdict
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# 주문 행의 `판매처`(한글 라벨) → 내부 마켓 슬러그. order_export._MARKET_KO 의 역방향.
MARKET_SLUG_BY_LABEL = {
    "스마트스토어": "smartstore", "롯데온": "lotteon", "쿠팡": "coupang",
    "11번가": "eleven11", "옥션": "auction", "G마켓": "gmarket",
}

# resolve_market_policy 가 아는 마켓만. 모르는 마켓을 넣으면 조용히 'ss'(6%)로
# 폴백해 **엉뚱한 수수료로 마진을 날조**하므로(unified._PREFIX_MAP), 화이트리스트로 막는다.
# reconcile.PRICED_MARKETS 와 같은 근거.
_FEE_PREFIX = {"smartstore": "ss", "coupang": "coupang"}

# 화면 상태 — 색이 상황을 말한다(시안 C안 범례와 1:1).
STATE_SAME = "same"        # 회색 — 안 바뀜
STATE_LOSS = "loss"        # 빨강 — 올랐고 손해 전환
STATE_WARN = "warn"        # 주황 — 올랐지만 아직 남음
STATE_GAIN = "gain"        # 초록 — 내려서 더 남음
STATE_UNKNOWN = "unknown"  # 회색 — 확인 불가


@dataclass
class RowPriceDiff:
    """주문 한 줄의 가격 전후. 모르는 값은 전부 None (0 아님)."""

    upload_purchase: int | None = None    # 올릴 때 매입가
    current_purchase: int | None = None   # 지금 매입가
    order_sale_price: int | None = None   # 주문 걸린 판매가(단가)
    margin: int | None = None             # 지금 사면 마진
    state: str = STATE_UNKNOWN
    reason: str | None = None             # 확인 불가 사유(사람이 읽는 말)
    canonical_sku: str | None = None      # 진단용


def row_key(r: dict) -> str:
    """주문 행 식별자. 화면(JS)과 서버가 같은 규칙을 쓴다.

    `판매처|오픈마켓주문번호` 만으로는 한 주문에 여러 상품이 든 행을 구분 못 해
    (order_export._row_key 와 같은 이유로) 상품명·옵션까지 붙인다.
    """
    return "|".join([str(r.get("판매처") or ""), str(r.get("오픈마켓주문번호") or ""),
                     str(r.get("상품명") or ""), str(r.get("옵션") or "")])


# ─────────────────────────────────────────────────────────────────────────────
#  1) 주문 행 → canonical_sku  (id 기반 조인만. 이름 추측 금지)
# ─────────────────────────────────────────────────────────────────────────────

def _row_market_ids(r: dict) -> tuple[str | None, list[str]]:
    """행이 들고 있는 (마켓옵션ID, [마켓상품ID…]). 없으면 (None, []).

    order_export 의 각 마켓 파서가 **응답에 실제로 있는 필드만** `_pd_` 키로 보존한다
    (엑셀·화면 열은 ALL_COLUMNS 화이트리스트라 `_pd_` 는 새어나가지 않는다).

    옵션 단위(정확 일치):
      · 쿠팡  vendorItemId → `_pd_market_option_id`
      · 11번가 prdStckNo(주문상품옵션코드) → `_pd_market_option_id`
    상품 단위(옵션은 색·사이즈 텍스트로 좁힘):
      · 롯데온 spdNo → `_lo_spdno`
      · 스마트스토어 productId(채널)·originalProductId(원상품) → `_pd_market_product_id(_alt)`
      · 옥션·G마켓 SiteGoodsNo → `_pd_market_product_id`

    스마트스토어·옥션·G마켓의 **옵션 단위** id 는 응답에서 확인되지 않았다(각 파서 주석 참조).
    추측해서 잇지 않는다 — 못 좁히면 화면은 '확인 불가'로 남는다.
    """
    oid = r.get("_pd_market_option_id") or r.get("_vid")
    pids, seen = [], set()
    for v in (r.get("_pd_market_product_id"), r.get("_pd_market_product_id_alt"),
              r.get("_lo_spdno")):
        s = str(v).strip() if v not in (None, "") else ""
        if s and s not in seen:
            seen.add(s)
            pids.append(s)
    oid = str(oid).strip() if oid not in (None, "") else ""
    return (oid or None, pids)


def _linked_markets(session) -> set:
    """연동이 **한 건이라도** 있는 마켓 슬러그. 쿼리 1회(DISTINCT — 돌아오는 행이 몇 개).

    색인을 IN 절로 좁히면 「그 마켓에 우리 상품이 하나도 없다」를 색인만 보고는 알 수
    없다(안 걸린 게 남의 상품이라서인지, 우리가 그 마켓을 안 쓰기 때문인지 구분 불가).
    그 판정만 따로 묻는다 — 전수 적재 없이 답이 나오는 질문이라 값이 싸다.

    🔴 **여긴 캐시하지 않는다.** 낡은 답은 「그 마켓엔 우리 상품이 없다」→ 방금 연동한
      마켓의 주문이 통째로 「남의 상품」으로 뜨는 거짓말이 된다. 몇 ms 아끼자고
      화면에 없는 말을 적을 자리가 아니다.
    """
    from lemouton.sets.models import SetChannel, SetChannelOption

    rows = (session.query(SetChannel.market)
            .join(SetChannelOption, SetChannelOption.channel_id == SetChannel.id)
            .filter(SetChannelOption.status == "matched")
            .distinct().all())
    return {m for (m,) in rows if m}


def _target_index(session, *, option_ids=None, product_ids=None):
    """(마켓,마켓옵션ID)→[(sku,계정)] · (마켓,마켓상품ID)→[(sku,계정)] 색인. 쿼리 1회.

    근거 테이블은 reconcile.market_targets_for 와 같은 SetChannel⋈SetChannelOption —
    계정(account_key)까지 들고 있는 유일한 자리다. MarketRegistration 은 PK 가
    (sku,market) 라 같은 마켓의 두 계정을 구분 못 해 쓰지 않는다.

    ★ [perf 2026-08-06] `option_ids`·`product_ids` 를 주면 **그 번호들만** IN 절로 읽는다.
      예전엔 요청마다 이 표를 통째로 읽어(연동 수만 행) 파이썬 dict 로 쌓았는데,
      주문 표 한 판이 이 함수를 세 군데(가격전후·이행분류·매입가)에서 각각 부른다.
      찾는 번호는 요청이 이미 들고 있으므로 **행 수는 요청 크기에 비례**하면 된다.
      둘 다 None 이면 예전처럼 전수(다른 호출자 호환).
    """
    from lemouton.sets.models import SetChannel, SetChannelOption

    q = (session.query(SetChannel.market, SetChannel.account_key,
                       SetChannel.market_product_id,
                       SetChannelOption.market_option_id,
                       SetChannelOption.canonical_sku)
         .join(SetChannelOption, SetChannelOption.channel_id == SetChannel.id)
         .filter(SetChannelOption.status == "matched"))

    by_option, by_product = defaultdict(list), defaultdict(list)

    def _fill(rows, into_option=True, into_product=True):
        for market, acct, mpid, moid, sku in rows:
            pair = (sku, acct or "default")
            if into_option and moid:
                by_option[(market, str(moid))].append(pair)
            if into_product and mpid:
                by_product[(market, str(mpid))].append(pair)

    if option_ids is None and product_ids is None:
        _fill(q.all())
        return by_option, by_product

    oids = [str(v) for v in (option_ids or []) if v not in (None, "")]
    pids = [str(v) for v in (product_ids or []) if v not in (None, "")]
    # 🔴 두 조회는 **각자 자기 칸만** 채운다. 한 덩어리로 합치면 같은 행이 두 조회에
    #   걸려 후보가 두 번 쌓이고, 「후보가 하나일 때만 인정」 규약이 흔들린다.
    # 🔴 [2026-08-14] 여기 적혀 있던 「SQLite IN 한도(999)」는 **틀린 근거**였다
    #    (999 는 SQLite 3.32 이전 기본값). 실측 한도와 자르는 진짜 이유는
    #    `lemouton/matrix/readiness._CHUNK` 옆 한 곳에만 적어 뒀다. 자르는 것 자체는
    #    그대로 둔다 — 안 자르면 주문 줄이 쌓인 날에만 조회가 통째로 실패한다.
    for i in range(0, len(oids), 900):
        _fill(q.filter(SetChannelOption.market_option_id.in_(oids[i:i + 900])).all(),
              into_product=False)
    for i in range(0, len(pids), 900):
        _fill(q.filter(SetChannel.market_product_id.in_(pids[i:i + 900])).all(),
              into_option=False)
    return by_option, by_product


def _option_axis_index(session, skus):
    """sku → (정규화 색상, 정규화 사이즈, model_code). 쿼리 1회.

    matcher.normalize 를 그대로 쓴다(공백·단위·영한 색상 매핑) — 옵션 매칭 규칙을
    새로 만들지 않는다. uploader.linker 가 마켓 옵션을 sku 에 붙일 때 쓰는 그 함수다.
    """
    from lemouton.mapping.matcher import normalize
    from lemouton.sourcing.models import Option

    if not skus:
        return {}
    out = {}
    for o in (session.query(Option)
              .filter(Option.canonical_sku.in_(list(skus))).all()):
        out[o.canonical_sku] = (normalize(o.color_display or o.color_code or ""),
                                normalize(o.size_display or o.size_code or ""),
                                o.model_code)
    return out


#: 매칭 실패 사유 — **「우리 상품이 아니다」와 「우리 상품인데 못 좁혔다」는 다른 말**이다.
#:   NOT_OURS 를 「확인 불가」로 뭉개면, 모음전으로 관리하지도 않는 남의 상품 주문이
#:   전부 「프로그램이 실패했다」로 보인다(라이브 실측 2026-07-31: 쿠팡 97건 중 95건이
#:   잔스포츠·마스마룰즈 등 우리 시스템에 없는 상품이었다).
MATCH_OK = ''
MATCH_NO_MARKET = 'no_market'      # 판매처 라벨을 모른다
MATCH_NO_IDS = 'no_ids'            # 마켓이 상품·옵션 번호를 안 줬다
MATCH_NOT_OURS = 'not_ours'        # 번호는 있는데 우리 연동 목록에 없다 = 남의 상품
MATCH_AMBIGUOUS = 'ambiguous'      # 후보가 여럿이라 못 좁혔다
MATCH_NO_LINKS = 'no_links'        # 연동이 한 건도 없다 — 판단할 근거 자체가 없다


def resolve_targets_verbose(session, rows):
    """행키 → {'sku','market','account','reason'}. **못 찾은 행도 담는다**(사유와 함께).

    `_resolve_targets` 와 같은 판정을 쓰되, 왜 못 찾았는지를 남긴다.
    두 함수가 서로 다른 답을 내면 그 자체가 모순이므로 판정은 여기 하나뿐이고
    `_resolve_targets` 는 이걸 감싸기만 한다.
    """
    from lemouton.mapping.matcher import normalize

    rows = list(rows or [])
    #: [perf] 이 요청이 찾는 번호만 색인으로 읽는다(연동 표 전수 적재 금지).
    _want_oid, _want_pid = set(), set()
    for r in rows:
        _o, _p = _row_market_ids(r)
        if _o:
            _want_oid.add(_o)
        _want_pid.update(_p)
    by_option, by_product = _target_index(session, option_ids=_want_oid,
                                          product_ids=_want_pid)
    known_oid = {k[1] for k in by_option}
    known_pid = {k[1] for k in by_product}
    #: 연동이 **한 건이라도** 있는 마켓들. 여기 없는 마켓에는 우리 상품이 하나도
    #: 올라가 있지 않다는 뜻이라, 그 마켓 주문은 번호가 없어도 남의 상품이 확실하다.
    linked_markets = _linked_markets(session)
    if not linked_markets:
        # ★ 연동이 통째로 0건이면 판단 근거가 아예 없다. 이때 전 주문을
        #   「남의 상품」이라 단정하면 진짜 우리 주문이 통째로 묻힌다 —
        #   연동 데이터가 사라진 상태일 수도 있기 때문이다(모르면 멈춘다).
        return {row_key(r): {'sku': None, 'market': None, 'account': None,
                             'reason': MATCH_NO_LINKS} for r in rows}

    need = set()
    plan = []
    out = {}
    for r in rows:
        key = row_key(r)
        market = MARKET_SLUG_BY_LABEL.get(str(r.get("판매처") or "").strip())
        if not market:
            out[key] = {'sku': None, 'market': None, 'account': None,
                        'reason': MATCH_NO_MARKET}
            continue
        if market not in linked_markets:
            out[key] = {'sku': None, 'market': market, 'account': None,
                        'reason': MATCH_NOT_OURS}
            continue
        oid, pids = _row_market_ids(r)
        if not oid and not pids:
            out[key] = {'sku': None, 'market': market, 'account': None,
                        'reason': MATCH_NO_IDS}
            continue
        # 번호를 줬는데 우리 연동 색인에 **하나도** 없으면 남의 상품이다(확실).
        if (not oid or oid not in known_oid) and not any(p in known_pid for p in pids):
            out[key] = {'sku': None, 'market': market, 'account': None,
                        'reason': MATCH_NOT_OURS}
            continue
        plan.append((key, market, oid, pids, str(r.get("옵션") or "")))
        for pid in pids:
            for sku, _ in by_product.get((market, pid), []):
                need.add(sku)
    axis = _option_axis_index(session, need)

    for key, market, oid, pids, opt_text in plan:
        hits = by_option.get((market, oid), []) if oid else []
        if len(hits) == 1:
            out[key] = {'sku': hits[0][0], 'market': market,
                        'account': hits[0][1], 'reason': MATCH_OK}
            continue
        cands, seen_c = [], set()
        for pid in pids:
            for pair in by_product.get((market, pid), []):
                if pair not in seen_c:
                    seen_c.add(pair)
                    cands.append(pair)
        if not cands:
            out[key] = {'sku': None, 'market': market, 'account': None,
                        'reason': MATCH_NOT_OURS}
            continue
        if len(cands) == 1:
            out[key] = {'sku': cands[0][0], 'market': market,
                        'account': cands[0][1], 'reason': MATCH_OK}
            continue
        norm_opt = normalize(opt_text)
        matched = [(sku, acct) for sku, acct in cands
                   if sku in axis
                   and axis[sku][0] and axis[sku][1]
                   and axis[sku][0] in norm_opt and axis[sku][1] in norm_opt]
        if len(matched) == 1:
            out[key] = {'sku': matched[0][0], 'market': market,
                        'account': matched[0][1], 'reason': MATCH_OK}
        else:
            out[key] = {'sku': None, 'market': market, 'account': None,
                        'reason': MATCH_AMBIGUOUS}
    return out


def _resolve_targets(session, rows):
    """행키 → (sku, market, account_key). 못 찾은 행은 아예 안 담는다(추측 금지).

    판정은 :func:`resolve_targets_verbose` 하나다 — 여기서는 찾은 것만 골라 낸다.

    2단계, **둘 다 유일하게 걸릴 때만** 인정한다(set_link_service._resolve_env_prefix
    의 '정확히 1건일 때만' 규약과 같음). 애매하면 화면에 '확인 불가'가 뜨는 게
    엉뚱한 상품의 가격을 보여주는 것보다 낫다.
      1단계 마켓옵션ID 정확 일치 (쿠팡 vendorItemId · 11번가 prdStckNo)
      2단계 마켓상품ID + 옵션 텍스트의 색상·사이즈 동시 포함
            (롯데온 spdNo · 스마트스토어 productId/originalProductId · 옥션·G마켓 SiteGoodsNo)
    """
    return {k: (v['sku'], v['market'], v['account'])
            for k, v in resolve_targets_verbose(session, rows).items()
            if v['reason'] == MATCH_OK}



# ─────────────────────────────────────────────────────────────────────────────
#  2) 올릴 때 매입가 — 스냅샷 일괄 (last_confirmed_snapshot 과 같은 필터)
# ─────────────────────────────────────────────────────────────────────────────

def _confirmed_snapshots(session, targets):
    """(sku,market,account_key) → PriceSnapshot. 쿼리 1회.

    reconcile.last_confirmed_snapshot 은 단건 전용이라 행마다 부르면 N+1 이 난다.
    **필터 조건과 '최신=id 내림차순 첫 행' 규약을 그대로** 옮겨 일괄로 만든다
    (조건이 갈리면 화면값과 업로드 게이트값이 달라지므로 여기서 바꾸면 안 된다).
    """
    from lemouton.uploader.models import PriceSnapshot

    if not targets:
        return {}
    skus = {t[0] for t in targets}
    rows = (session.query(PriceSnapshot)
            .filter(PriceSnapshot.canonical_sku.in_(list(skus)),
                    PriceSnapshot.action == "upload",
                    PriceSnapshot.uploaded_at.isnot(None))
            .order_by(PriceSnapshot.id.desc())
            .all())
    out = {}
    for sp in rows:                       # id 내림차순 → 대상별 첫 등장이 최신
        k = (sp.canonical_sku, sp.market, sp.account_key or "default")
        if k not in out:
            out[k] = sp
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  3) 지금 매입가 — 대표 소싱처 크롤가 → compute_breakdown (호출만)
# ─────────────────────────────────────────────────────────────────────────────

#: [perf 2026-08-06] 모델코드 → (잰 시각, {sku: (소싱처id, 크롤가, 소싱상품id)}).
#:
#: 왜 캐시가 필요했나 — 주문 표 한 판을 그리면 화면이 **세 곳**(가격전후·이행분류·매입가)에서
#: 동시에 이 함수를 부르고, 그 안에서 `_option_matrix_data` 가 **모델코드마다** 돌았다.
#: 실측(합성 2만 소싱상품): 매트릭스 1회 = 25쿼리·1.7초 → 3줄짜리 요청이 2.8초, 400줄이 4분 반.
#:
#: 무엇을 담는가 — **대표 소싱처를 고른 결과(숫자 셋)뿐**이다. 매트릭스 원본(옵션·가격설정·
#: 재고까지 든 큰 dict)은 담지 않는다. 라이브 워커는 램이 작다.
#: 대표 선정 규칙(크롤가 최저)은 여기서 만들지 않고 매트릭스 값을 그대로 읽는다.
_FINALS_TTL = 60.0                  # 크롤 주기는 시간 단위라 1분 지연은 화면에 안 보인다
_FINALS_MAX = 500                   # 모델코드 수 상한 — 넘으면 통째로 비운다(램 못 박기)
_finals_cache: dict = {}
_finals_lock = _thr.Lock()


def _sources_cached(model_code):
    """캐시에 살아 있는 대표 소싱처 정보. 없으면 None."""
    with _finals_lock:
        hit = _finals_cache.get(model_code)
    if not hit:
        return None
    ts, data = hit
    return data if (_time.monotonic() - ts) < _FINALS_TTL else None


def _sources_store(model_code, data):
    with _finals_lock:
        if len(_finals_cache) >= _FINALS_MAX:
            _finals_cache.clear()
        _finals_cache[model_code] = (_time.monotonic(), data)


def _best_sources_of(data):
    """매트릭스 응답 → {sku: (source_id, crawled_price, source_product_id)}.

    대표 = **크롤가 최저**(sets_api._current_source_value_map 과 같은 규칙).
    크롤값이 없는 옵션은 키를 안 만든다 — 「확인 불가」로 남기려는 것이다.
    """
    out = {}
    for o in (data.get("options") or []):
        cands = [sc for sc in (o.get("sources") or [])
                 if sc.get("source_id") is not None
                 and sc.get("crawled_price") is not None]
        if not cands or not o.get("sku"):
            continue
        best = min(cands, key=lambda sc: sc["crawled_price"])
        out[o["sku"]] = (best["source_id"], best["crawled_price"],
                         best.get("source_product_id"))
    return out


def _current_purchase(session, skus, matrix_loader=None):
    """sku → 지금 최종매입가. 못 구한 sku 는 **키를 안 만든다**(0 으로 채우지 않음).

    소싱 값은 매트릭스 단일 진실 원천(_option_matrix_data)을 그대로 쓴다 —
    카드·영수증과 같은 값이어야 화면끼리 안 갈린다(sets_api._current_source_value_map
    과 동일 경로·동일 대표 선정: 크롤가 최저).

    ★ [perf] 매트릭스는 **모델코드당 1회**이고, 그 결과에서 뽑은 대표 소싱처는 위 TTL 캐시에
      남는다. 또 한 요청 안에서 여러 모델코드를 훑을 때는 `batch` 그릇을 물려
      소싱상품 전수 조회를 **한 번만** 하게 한다(모델코드마다 반복하던 것).
    """
    from webapp.routes.api_benefits import _build_breakdown_cache, compute_breakdown
    from lemouton.sourcing.models import Option

    #: matrix_loader 를 준 호출자(시험·정책 미리보기·이행분류)는 자기 로더를 쓴다 →
    #: 공용 캐시를 쓰지 않는다(주입한 값이 남의 요청에 새면 안 된다).
    injected = matrix_loader is not None
    batch = None
    matrix_many = None
    if not injected:
        from webapp.routes.api_pricing import (
            _option_matrix_data as matrix_loader,
            _option_matrix_data_many as matrix_many,
        )
        batch = {}

    want = set(skus)
    if not want:
        return {}, {}
    # model_code 별로 1회만 매트릭스를 읽는다(행당 아님).
    model_by_sku = {o.canonical_sku: o.model_code
                    for o in session.query(Option)
                    .filter(Option.canonical_sku.in_(list(want))).all()}
    items = []
    all_mcs = sorted(set(model_by_sku.values()))
    cached_by_mc = {} if injected else {
        mc: got for mc in all_mcs if (got := _sources_cached(mc)) is not None}
    #: [perf 2026-08-07] 캐시에 없는 모델코드는 **한꺼번에** 읽는다 — 예전엔 코드마다
    #:   따로 불러 세션을 새로 열고 닫았고, 그래서 소싱처 명부·혜택 캐시·축 맞춤 사전이
    #:   모델마다 다시 만들어졌다(실측 모델당 27.5쿼리).
    fetched = {}
    _need = [mc for mc in all_mcs if mc not in cached_by_mc]
    if _need and not injected:
        try:
            fetched = matrix_many(_need, batch=batch)
        except Exception:                          # noqa: BLE001
            logger.exception("옵션 매트릭스 일괄 조회 실패 n=%d", len(_need))
            fetched = {}
    for mc in all_mcs:
        best_by_sku = cached_by_mc.get(mc)
        if best_by_sku is None:
            if injected:
                try:
                    data = matrix_loader(mc)
                except Exception:                  # noqa: BLE001
                    logger.exception("옵션 매트릭스 조회 실패 model=%s", mc)
                    continue
            else:
                data = fetched.get(mc)
            if not data or not data.get("ok"):
                continue
            best_by_sku = _best_sources_of(data)
            if not injected:
                _sources_store(mc, best_by_sku)
        for sku, (sid, price, spid) in best_by_sku.items():
            if sku in want:
                items.append({"sku": sku, "source_id": sid,
                              "sale_price": price, "source_product_id": spid})

    finals, errors = {}, {}
    if not items:
        return finals, errors
    try:
        # 소싱상품 전수를 이미 읽었으면 그대로 넘긴다(같은 표를 또 읽지 않는다).
        # batch 는 있을 때만 넘긴다 — 이 함수를 가짜로 바꿔 끼우는 자리(시험·미리보기)가
        #   옛 서명을 그대로 쓰고 있어서, 없는데 넘기면 그쪽이 깨진다.
        # 🔴 매트릭스가 만든 캐시(`batch['bd_cache']`)를 여기서 **되쓰지 않는다** —
        #   그건 상품 묶음마다 비워지는 것이라 **앞 묶음 SKU 가 빠져 있다**.
        #   빠진 SKU 는 혜택이 통째로 없는 것처럼 계산돼 최종매입가가 표면가로 뜬다(금전).
        cache = _build_breakdown_cache(session, items,
                                       sp_rows=(batch or {}).get("sp_all"),
                                       **({"batch": batch} if batch else {}))
    except Exception:                                    # noqa: BLE001
        logger.exception("breakdown 캐시 실패 — %d건 확인 불가", len(items))
        return finals, {it["sku"]: "계산 실패" for it in items}
    for it in items:
        try:
            bd = compute_breakdown(session, sku=it["sku"],
                                   source_id=_sid_key(it["source_id"]),
                                   sale_price=float(it["sale_price"]), _cache=cache,
                                   source_product_id=it.get("source_product_id"))
        except Exception:                                # noqa: BLE001
            logger.exception("최종매입가 계산 실패 sku=%s", it["sku"])
            errors[it["sku"]] = "계산 실패"
            continue
        if bd and bd.get("final_price") is not None:
            finals[it["sku"]] = int(bd["final_price"])
        else:
            errors[it["sku"]] = "계산 실패"
    return finals, errors


def _sid_key(v):
    """소싱처 id 정규화 — sets_api._sid_key 와 같은 규약(문자열 카탈로그 키 허용)."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


# ─────────────────────────────────────────────────────────────────────────────
#  4) 마진 — 기존 수수료·마진 함수 재사용 (여기서 산식을 만들지 않는다)
# ─────────────────────────────────────────────────────────────────────────────

class _PriceLike:
    """compute_margin_amount 가 읽는 모양(final_price/breakdown)만 맞춘 어댑터.

    마진 산식을 복사하지 않으려고 둔다 — 실제 계산은 reconcile.compute_margin_amount
    한 곳에서만 일어난다(정의가 갈리면 같은 상품 마진이 화면마다 달라진다).
    """

    def __init__(self, final_price, fee_rate, shipping_fee=0):
        self.final_price = final_price
        self.breakdown = {"fee_rate": fee_rate, "shipping_fee": shipping_fee}


def _parse_pct(v):
    """'11.55%' → 0.1155. 못 읽으면 None(0 으로 넘기지 않는다)."""
    if v is None or v == "":
        return None
    try:
        s = str(v).strip().rstrip("%")
        if not s:
            return None
        return float(s) / 100.0
    except (TypeError, ValueError):
        return None


def _fee_rate_for(row, market, tpl):
    """이 주문에 쓸 수수료율(분수). 모르면 None → 마진은 '확인 불가'.

    순서에 근거가 있다:
      1. 주문 행의 `수수료율` — 마켓 정산이 준 **실값**(order_export._finalize_rows
         가 마켓수수료÷총주문금액으로 채움). 추정이 아니므로 최우선.
      2. 없으면 pricing.unified.resolve_market_policy 의 fee_rate — 우리가 가격을
         만들 때 쓴 그 요율. 단 _FEE_PREFIX 에 있는 마켓만: resolve_market_policy 는
         모르는 마켓을 조용히 'ss'(6%)로 폴백해 롯데온·11번가 마진을 날조한다.
      3. 둘 다 없으면 None.
    """
    real = _parse_pct(row.get("수수료율"))
    if real is not None and 0 <= real < 1:
        return real
    prefix = _FEE_PREFIX.get(market)
    if not prefix:
        return None
    from lemouton.pricing.unified import resolve_market_policy
    try:
        return float(resolve_market_policy(tpl, prefix, "sourcing").get("fee_rate"))
    except Exception:                                    # noqa: BLE001
        logger.exception("수수료율 조회 실패 market=%s", market)
        return None


def _price_templates_for(session, skus):
    """sku → PriceTemplate. reconcile._price_template_for 와 같은 경로를 일괄로.

    sku → Option.model_code → Model.price_template_id → PriceTemplate. 쿼리 3회(고정).
    """
    from lemouton.sourcing.models import Model, Option
    from lemouton.templates.models import PriceTemplate

    if not skus:
        return {}
    opts = (session.query(Option.canonical_sku, Option.model_code)
            .filter(Option.canonical_sku.in_(list(skus))).all())
    model_by_sku = dict(opts)
    codes = set(model_by_sku.values())
    if not codes:
        return {}
    tpl_id_by_code = {m.model_code: m.price_template_id
                      for m in session.query(Model)
                      .filter(Model.model_code.in_(list(codes))).all()}
    tpl_ids = {v for v in tpl_id_by_code.values() if v}
    tpl_by_id = {}
    if tpl_ids:
        tpl_by_id = {t.id: t for t in session.query(PriceTemplate)
                     .filter(PriceTemplate.id.in_(list(tpl_ids))).all()}
    return {sku: tpl_by_id.get(tpl_id_by_code.get(mc))
            for sku, mc in model_by_sku.items()}


# ─────────────────────────────────────────────────────────────────────────────
#  5) 조립
# ─────────────────────────────────────────────────────────────────────────────

def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(round(float(str(v).replace(",", ""))))
    except (TypeError, ValueError):
        return None


def _state_of(upload, current, margin):
    if upload is None or current is None:
        return STATE_UNKNOWN
    if int(upload) == int(current):
        return STATE_SAME
    if int(current) > int(upload):
        # 손해 전환은 **마진을 실제로 계산했을 때만** 단정한다. 마진을 모르면
        # '올랐다'까지만 말한다(모르는 걸 손해로 단정하지 않음).
        return STATE_LOSS if (margin is not None and margin < 0) else STATE_WARN
    return STATE_GAIN


def build_price_diffs(session, rows, *, matrix_loader=None) -> dict:
    """주문 행 목록 → {행키: RowPriceDiff dict}. 실패는 전부 '확인 불가'로 남는다."""
    rows = list(rows or [])
    if not rows:
        return {}

    targets = _resolve_targets(session, rows)
    skus = {t[0] for t in targets.values()}
    snaps = _confirmed_snapshots(session, set(targets.values()))
    finals, calc_errors = _current_purchase(session, skus, matrix_loader=matrix_loader)
    tpls = _price_templates_for(session, skus)

    out = {}
    for r in rows:
        key = row_key(r)
        sale = _to_int(r.get("단가"))
        d = RowPriceDiff(order_sale_price=sale)
        tgt = targets.get(key)
        if not tgt:
            d.reason = "이 주문을 우리 옵션(SKU)에 연결하지 못했어요"
            out[key] = asdict(d)
            continue
        sku, market, acct = tgt
        d.canonical_sku = sku
        sp = snaps.get((sku, market, acct))
        if sp is None:
            d.reason = "마켓에 실제로 올라간 가격 기록(스냅샷)이 없어요"
        elif sp.final_purchase_price is not None:
            d.upload_purchase = int(sp.final_purchase_price)
        else:
            d.reason = "올릴 때 매입가가 기록되지 않았어요"

        if sku in finals:
            d.current_purchase = finals[sku]
        else:
            d.reason = d.reason or (calc_errors.get(sku)
                                    or "지금 소싱처 가격을 못 읽었어요")

        if d.current_purchase is not None and sale is not None:
            fee = _fee_rate_for(r, market, tpls.get(sku))
            if fee is not None:
                from lemouton.uploader.reconcile import compute_margin_amount
                d.margin = compute_margin_amount(
                    _PriceLike(sale, fee, _to_int(r.get("배송비")) or 0),
                    d.current_purchase)
        d.state = _state_of(d.upload_purchase, d.current_purchase, d.margin)
        out[key] = asdict(d)
    return out
