# -*- coding: utf-8 -*-
"""맵핑 자동 제안 — 이름 유사도(순수함수) + 쿠팡 추천 앵커 오케스트레이션 (스펙 §C).

제안은 제안일 뿐이다: confidence 가 얼마든 자동 확정하지 않는다(정직성 원칙).
"""
from __future__ import annotations

import datetime
import json
import re

# 등록 흐름 전체(bulk_manual.js 카테고리 검색)에서 다루는 6마켓과 동일 순서·코드
# (webapp/routes/bulk/categories.py::MARKETS 와 중복 — lemouton 쪽이 webapp 을
#  import 하면 순환참조가 나서, 6마켓 코드표라는 짧고 안정적인 상수만 복제한다).
# ★ MARKETS 는 "6마켓 전체"가 맞는 다른 용도(예: webapp/routes/bulk/category_map.py 의
#   브랜드·지재권 제한표 market 검증 — 롯데온도 브랜드 자체를 막을 수 있어야 한다)에
#   계속 쓰인다. 카테고리 제안 생성만 SUGGESTION_MARKETS 를 쓴다(아래).
MARKETS = ('smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon')

# [2026-07-23 리뷰 수정 I3] 롯데온은 카테고리 코드가 아니라 본보기 상품번호(spdNo)로
# 등록한다(webapp/routes/bulk/drafts.py::_lotteon_sample_search 참조) — market_categories
# 카테고리 사전 자체가 롯데온 등록에는 쓰이지 않으므로, 자동 제안 생성 대상에서 제외한다.
# (catmap_confirm 라우트도 market='lotteon' 확정 요청을 400 으로 거부한다 — 맵핑 대상 아님.)
SUGGESTION_MARKETS = tuple(m for m in MARKETS if m != 'lotteon')


def _tokens(path):
    out = set()
    for part in str(path or '').split('>'):
        part = part.strip()
        if part:
            out.add(part)
    return out


# ── 성별·연령 축 (2026-07-23 사장님 규칙) ──────────────────────────────────
# 라이브 오제안: 소싱처 '슈즈/운동화>여성신발>스니커즈' → 11번가 '남성신발>스니커즈',
# 스스 '패션잡화>남성신발>스니커즈/운동화', 옥션 '브랜드 잡화>남성화>로퍼'.
# 원인은 **맨 끝 리프명만** 비교한 것 — 성별은 리프('스니커즈')가 아니라 앞마디
# ('여성신발')에 붙는데 그 앞마디를 통째로 무시했다. 그래서 판정은 리프가 아니라
# **경로 전체** 로 한다.
#
# ★ 단순 포함검사로 충분한가(사장님 지시 검토 항목)
#   · 한국어 '여성'/'여자' ↔ '남성'/'남자' 는 서로의 부분문자열이 아니고, 다른 뜻의
#     카테고리 단어에 끼어들지도 않는다 → **한국어는 단순 포함검사로 충분**하다.
#   · 영어는 다르다: 'WOMEN' 이 'MEN' 을 통째로 품는다. 포함검사를 그대로 쓰면
#     'SHOES>WOMEN>SNEAKERS' 가 여성이면서 남성으로도 읽혀 판정이 무너진다
#     → 영어는 **단어경계(\b) 정규식**으로만 본다(\bmen\b 는 'women' 안에서 안 걸린다).
#   · '맨' 은 포함검사 금지 — '맨투맨'(스스·옥션 실제 카테고리)·'슈퍼맨' 처럼 성별과
#     무관한 말에 흔히 낀다. '맨즈/맨스' 또는 **세그먼트 전체가 '맨'** 일 때만 남성.
#   · 'w'/'m' 한 글자는 세그먼트 전체가 그 글자일 때만(그 외엔 아무 영단어에나 걸린다).
#   · 공용/유니섹스/남녀공용 = **중립**(반대 성별로 잘못 배제되면 안 된다).
#   · 한 경로에 여성·남성 표지가 같이 있으면 판정을 포기하고 중립 — 추측보다 안전하다
#     (중립은 어느 쪽에서도 배제되지 않는다).
_UNISEX_RE = re.compile(r'남녀\s*공용|공용|유니\s*섹스|unisex', re.I)
_FEMALE_RE = re.compile(r"여성|여자|우먼|\bwomen(?:'?s)?\b|\bwmns\b|\bladies\b|\blady\b", re.I)
_MALE_RE = re.compile(r"남성|남자|맨즈|맨스|\bmen(?:'?s)?\b", re.I)
_FEMALE_SEGS = frozenset({'w', 'woman', 'women', 'womens', "women's", 'wmns', 'ladies', '우먼'})
_MALE_SEGS = frozenset({'m', 'man', 'men', 'mens', "men's", '맨'})

# 연령 축은 성별과 **별개 축**이다(유아동 안에도 남아/여아가 있다). 사장님 지시대로
# 같은 방식으로 다룬다 — 양쪽이 모두 명시됐고 서로 다르면 제외, 한쪽이 미표기면 배제
# 하지 않는다. 성별 표지(여성/남성)는 성인 트리의 표지이므로 '성인'으로 읽는다
# (유아동 트리는 '남아/여아' 를 쓰지 '남성/여성' 을 쓰지 않는다).
_KIDS_RE = re.compile(
    r'유아동|아동|키즈|주니어|유아|남아|여아|베이비|\bkids?\b|\bjunior\b|\bbaby\b'
    r'|\btoddler\b|\binfant\b', re.I)
_ADULT_RE = re.compile(r'성인|\badult\b', re.I)


def _segments(path):
    return [p.strip().lower() for p in str(path or '').split('>') if p.strip()]


def _gender_of(path):
    """경로 전체에서 성별을 읽는다 — 'female' | 'male' | None(중립·미표기·모호)."""
    text = str(path or '')
    if not text:
        return None
    if _UNISEX_RE.search(text):
        return None
    segs = _segments(text)
    female = bool(_FEMALE_RE.search(text)) or any(s in _FEMALE_SEGS for s in segs)
    male = bool(_MALE_RE.search(text)) or any(s in _MALE_SEGS for s in segs)
    if female and male:
        return None          # 모호 — 중립으로 둔다(배제도 우대도 하지 않는다)
    if female:
        return 'female'
    if male:
        return 'male'
    return None


def _age_of(path, gender=None):
    """경로 전체에서 연령축을 읽는다 — 'kids' | 'adult' | None(미표기)."""
    text = str(path or '')
    if not text:
        return None
    if _KIDS_RE.search(text):
        return 'kids'
    if _ADULT_RE.search(text) or gender:
        return 'adult'
    return None


def _axes(path):
    gender = _gender_of(path)
    return gender, _age_of(path, gender)


def is_opposite_axis(source_path, candidate_path):
    """소스와 후보가 **명시적으로 반대** 성별(또는 연령)인가 — 제안 금지 판정용.

    한쪽이라도 미표기(중립)면 False — 애매한 걸 반대로 단정하지 않는다.
    """
    s_gender, s_age = _axes(source_path)
    c_gender, c_age = _axes(candidate_path)
    if s_gender and c_gender and s_gender != c_gender:
        return True
    if s_age and c_age and s_age != c_age:
        return True
    return False


def rank_candidates(source_path, market_leaves, top=3):
    """source_path 의 리프명·경로 토큰으로 market_leaves 후보 상위 top 개.

    점수: 리프명 정확일치 1.0 / 리프명이 후보명에 포함(또는 역포함) 0.7
          / 경로 토큰 겹침 0.4×(겹친 토큰 비율). 0 은 제외.

    성별(2026-07-23 사장님 규칙) — 점수를 곱셈으로 깎지 않고 **정렬 우선순위**로 넣는다
    (곱셈 가중은 "왜 이 순서인지" 를 숫자 뒤에 숨긴다):
      ① 소스에 성별이 있으면 **중립(성별 미표기) 후보가 1순위** — 점수가 낮아도 앞선다
      ② 그 다음이 **같은 성별**
      ③ **반대 성별은 후보에서 제거** — 결과가 0개가 되면 행을 만들지 않고 사장님이
         검색으로 직접 고르는 흐름으로 넘긴다(틀린 제안이 1등에 오르는 것보다 낫다)
      ④ 소스에 성별이 없으면 기존 동작 그대로(필터 없음·중립을 깎지도 우대하지도 않음)
    연령축(유아동)도 ③과 같은 방식으로 반대는 제거하고, 유아동 소스일 때만 유아동
    후보를 앞세운다(성인 소스는 연령 순서를 건드리지 않는다 — 성별 순서와 안 엉킨다).

    반환 dict 의 `gender`/`age` 는 화면에 "왜 이 순서인지" 를 설명하기 위한 근거 필드다
    (neutral=후보가 미표기 / same=소스와 같음 / none=소스 자체가 미표기).
    """
    parts = [p for p in str(source_path or '').split('>') if p.strip()]
    if not parts:
        return []
    leaf = parts[-1].strip()
    stoks = _tokens(source_path)
    src_gender, src_age = _axes(source_path)
    ranked = []
    for cand in market_leaves:
        name = str(cand.get('name') or '').strip()
        score = 0.0
        if name == leaf:
            score = 1.0
        elif leaf and (leaf in name or name in leaf) and name:
            score = 0.7
        else:
            ctoks = _tokens(cand.get('full_path'))
            inter = stoks & ctoks
            if inter:
                score = 0.4 * (len(inter) / max(len(stoks), 1))
        if score <= 0:
            continue

        # 성별·연령은 리프명이 아니라 **경로 전체**로 본다(full_path 가 비면 이름으로).
        cand_text = cand.get('full_path') or name
        cand_gender, cand_age = _axes(cand_text)
        if src_gender and cand_gender and cand_gender != src_gender:
            continue                                    # ③ 반대 성별 — 제안하지 않는다
        if src_age and cand_age and cand_age != src_age:
            continue                                    # 반대 연령축(유아동↔성인)도 제외

        gender_rank = 0 if (not src_gender or cand_gender is None) else 1
        age_rank = 1 if (src_age == 'kids' and cand_age != 'kids') else 0
        ranked.append((gender_rank, age_rank, -score, cand.get('full_path') or '', {
            'code': cand['code'], 'path': cand.get('full_path'), 'name': name,
            'score': round(score, 3),
            'gender': 'none' if not src_gender else ('neutral' if cand_gender is None else 'same'),
            'age': 'none' if not src_age else ('neutral' if cand_age is None else 'same'),
        }))
    ranked.sort(key=lambda r: r[:4])
    return [r[4] for r in ranked[:top]]


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def generate_suggestions(session, source_id, coupang_predict=None, now=None):
    """source_categories(source_id) 의 각 경로 × 6마켓으로 category_map 제안을 채운다.

    - status='confirmed' 행은 절대 건드리지 않는다(코드·상태 불변) — skipped_confirmed 로 집계.
    - suggested/re_confirm 행은 후보·1등코드·confidence 를 갱신한다. **status 는 바꾸지 않는다**
      (re_confirm 을 suggested 로 되돌리면 「재확정 필요」 표시가 지워져 조용히 묻힌다).
    - 후보가 0개면 행을 만들지 않는다. 기존 행이 있어도 지우지 않는다(조용한 삭제 금지) —
      그냥 건드리지 않고 넘어간다. **예외 하나**: status='suggested' 인데 그 제안이
      새 성별·연령 규칙에서 반대 축임이 증명되면(is_opposite_axis) 지운다 — 갱신으로
      덮이지 않아 틀린 제안이 계속 1등으로 남기 때문. 몇 건인지는 결과의 cleared.
    - 쿠팡은 `coupang_predict(name=리프명, brand=None)` 콜러블(주입식)이 SUCCESS 를 반환하면
      그 카테고리를 1등 후보로 앵커한다(method='coupang_reco', confidence=0.95). 미주입이거나
      FAILURE/INSUFFICIENT_INFORMATION 이면 이름 유사도 후보만 쓴다 — 추측 금지.
      실제 `shared/platforms/coupang/categories.py::predict` 는 성공 시 카테고리ID(int),
      실패 시 None 만 돌려주는 얇은 래퍼라 — 여기서는 그 값이나(정수/문자열),
      더 풍부한 `{'result': 'SUCCESS'|'FAILURE'|'INSUFFICIENT_INFORMATION',
      'predictedCategoryId': ...}` 딕셔너리 어느 쪽을 돌려줘도 인식한다(Task 5 라우트가
      실래퍼를 감싸 어느 모양으로 주입하든 이 함수가 그대로 받게).

    Returns: {'sources': n, 'suggested': n, 'skipped_confirmed': n, 'cleared': n}
    """
    from lemouton.registration.models import SourceCategory, CategoryMapRow, MarketCategory

    now = now or _utcnow()
    src_rows = (session.query(SourceCategory)
                .filter(SourceCategory.source_id == source_id)
                .all())

    # 마켓별 리프 카테고리를 소스 루프 밖에서 딱 1회씩만 로딩한다(6쿼리, 소스 경로
    # 개수와 무관 — 예전엔 소스경로×마켓마다 재질의해 500경로×6마켓=3000쿼리였다).
    # code_to_path 는 쿠팡 앵커의 경로 조회용 — 매번 leaves 를 선형 스캔(next())하던
    # 것을 여기서 미리 만든 dict 조회 O(1) 로 바꾼다.
    leaves_by_market = {}
    code_to_path = {}
    for market in SUGGESTION_MARKETS:
        leaves = (session.query(MarketCategory)
                  .filter(MarketCategory.market == market,
                          MarketCategory.is_leaf.is_(True),
                          MarketCategory.removed_at.is_(None))
                  .all())
        leaves_by_market[market] = [{'code': m.code, 'name': m.name, 'full_path': m.full_path}
                                    for m in leaves]
        code_to_path[market] = {str(m.code): m.full_path for m in leaves}

    # 이 source_id 의 기존 category_map 행 전체를 1쿼리로 로딩(소스경로×마켓마다
    # 재질의하던 것 제거). confirmed 게이트를 여기서 먼저 걸어 rank_candidates·
    # coupang_predict 호출까지 건너뛴다(전엔 confirmed 여부와 무관하게 항상 계산했다).
    existing_rows = (session.query(CategoryMapRow)
                      .filter(CategoryMapRow.source_id == source_id)
                      .all())
    existing_map = {(row.source_path, row.market): row for row in existing_rows}

    suggested = 0
    skipped_confirmed = 0
    cleared = 0

    for src in src_rows:
        for market in SUGGESTION_MARKETS:
            existing = existing_map.get((src.path, market))

            if existing and existing.status == 'confirmed':
                skipped_confirmed += 1
                continue

            market_leaves = leaves_by_market[market]
            candidates = rank_candidates(src.path, market_leaves, top=3)
            method = 'name_sim' if candidates else None

            if market == 'coupang' and coupang_predict is not None:
                result = coupang_predict(name=src.leaf_name, brand=None)
                pred_code = None
                if isinstance(result, dict):
                    if (result.get('result') == 'SUCCESS'
                            and result.get('predictedCategoryId')):
                        pred_code = str(result['predictedCategoryId'])
                elif result:
                    pred_code = str(result)
                if pred_code:
                    pred_path = code_to_path[market].get(pred_code)
                    if pred_path is not None and is_opposite_axis(src.path, pred_path):
                        # 쿠팡 추천은 리프명만 보고 오므로(성별 없는 '스니커즈') 반대 성별
                        # 카테고리를 돌려줄 수 있다 — 이름유사도와 같은 잣대로 앵커도 버린다.
                        pred_path = None
                    if pred_path is not None:
                        coupang_cand = {'code': pred_code, 'path': pred_path,
                                        'name': None, 'score': 0.95}
                        candidates = ([coupang_cand]
                                     + [c for c in candidates if c['code'] != pred_code])[:3]
                        method = 'coupang_reco'
                    # else: 예측 코드가 로컬 사전(market_categories)에 없다 — 확정
                    # 게이트가 400 으로 거부할 코드를 1등 제안으로 주지 않는다.
                    # 앵커를 버리고 이름 유사도 후보만 쓴다(method 는 'name_sim' 유지).

            if not candidates:
                # 후보 0개 — 새로 만들지 않는다. 기존 suggested/re_confirm 행이 있어도
                # 조용히 지우지 않고 그대로 둔다(없음=검색 유도, 삭제=데이터 손실).
                #
                # [2026-07-23 성별 규칙] 단 하나의 예외 — 남아 있는 제안이 **반대 성별
                # (또는 반대 연령축)임이 증명된** 경우엔 지운다. 후보가 0개가 된 이유가
                # 새 규칙이라 갱신으로 덮이지 않는데, 그대로 두면 '남성신발>스니커즈' 같은
                # 틀린 제안이 계속 1등으로 보인다(= 잘못 등록될 위험). 근거 없는 조용한
                # 삭제가 아니라 "틀렸음이 확인된 제안"만 걷어내는 것이고, 결과 dict 의
                # cleared 로 몇 건인지 드러낸다.
                #   · confirmed 는 절대 손대지 않는다(위에서 이미 continue).
                #   · re_confirm 도 남긴다 — 「다시 골라야 함」 표시 자체가 사장님에게 갈
                #     신호라, 지우면 그 신호가 사라진다(코드는 확정 게이트에서 다시 고른다).
                if (existing is not None and existing.status == 'suggested'
                        and is_opposite_axis(src.path, existing.market_cat_path)):
                    session.delete(existing)
                    cleared += 1
                continue

            top = candidates[0]
            candidates_json = json.dumps(candidates, ensure_ascii=False)

            if existing:
                existing.market_cat_code = top['code']
                existing.market_cat_path = top.get('path')
                existing.method = method
                existing.confidence = top['score']
                existing.candidates_json = candidates_json
                existing.updated_at = now
                # status(suggested|re_confirm) 는 의도적으로 건드리지 않는다.
            else:
                session.add(CategoryMapRow(
                    source_id=source_id, source_path=src.path, market=market,
                    market_cat_code=top['code'], market_cat_path=top.get('path'),
                    method=method, confidence=top['score'],
                    candidates_json=candidates_json, updated_at=now,
                ))
            suggested += 1

    session.commit()
    return {'sources': len(src_rows), 'suggested': suggested,
            'skipped_confirmed': skipped_confirmed, 'cleared': cleared}
