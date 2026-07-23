"""판매처 카테고리 전수 수집 — 마켓별 파서(순수함수) + 저장/diff 엔진.

원칙 (스펙 2026-07-22 §A·§5):
- 파서는 순수함수(응답 텍스트/JSON → 행 리스트). 네트워크는 fetch 콜러블 주입 — 테스트는 fixture.
- 실패는 HarvestError 로 표면화한다. 조용히 빈 리스트를 돌려주지 않는다(조용한 실패 금지).
- 행 스키마: {code, name, parent_code, depth, is_leaf, full_path, raw}  (전부 str/int/bool, raw=원문 조각)
"""
from __future__ import annotations

import re


class HarvestError(Exception):
    """카테고리 수집 실패 — 사유를 그대로 담는다."""


# [2026-07-23 실측 사고 대응 #3] 청크 200 → 50. 실측 3회: ①13시간 running 후 유실
# ②1,534건에서 정지(22분간 진행 정지 = 스레드 사망) ③124건에서 정지 — 200 문턱을 한 번도
# 못 넘겨 첫 청크조차 저장되지 못했다(저장 0건). 워커가 gunicorn 리사이클·메모리 캡(2GB·
# 900m·earlyoom)으로 죽는 환경에서는 "200건 모을 때까지 버티기"조차 보장 못 한다 — 문턱을
# 낮춰 죽기 전에 최소 한 번은 저장되게 한다. harvest_coupang·harvest_esm_site 공용.
CHUNK_SIZE = 50


def build_paths(rows):
    """parent_code 사슬로 full_path('A>B>C')를 조립해 각 행에 넣는다. 고아 부모는 HarvestError."""
    by_code = {r['code']: r for r in rows}
    def _path(r, guard=0):
        if guard > 10:
            raise HarvestError(f"카테고리 경로 순환 의심: {r['code']}")
        p = r.get('parent_code')
        if not p:
            return r['name']
        if p not in by_code:
            raise HarvestError(f"카테고리 고아 부모: code={r['code']} parent_code={p}")
        return _path(by_code[p], guard + 1) + '>' + r['name']
    for r in rows:
        r['full_path'] = _path(r)
    return rows


# ── 11번가 ──────────────────────────────────────────────
_CAT_BLOCK = re.compile(r'<(?:\w+:)?category>(.*?)</(?:\w+:)?category>', re.S)


def _tag(block, t):
    m = re.search(r'<(?:\w+:)?%s>(.*?)</(?:\w+:)?%s>' % (t, t), block, re.S)
    return m.group(1).strip() if m else ''


def parse_eleven11(xml_text):
    """11번가 전체 카테고리 XML → 행 리스트. leafYn=='Y' 를 리프로 본다(기존 검색 코드와 동일 기준)."""
    rows = []
    for block in _CAT_BLOCK.findall(xml_text or ''):
        code, name = _tag(block, 'dispNo'), _tag(block, 'dispNm')
        if not code or not name:
            raise HarvestError('11번가 카테고리 블록에 dispNo/dispNm 누락: ' + block[:120])
        parent = _tag(block, 'parentDispNo')
        rows.append({
            'code': code, 'name': name,
            'parent_code': (parent if parent not in ('', '0') else None),
            'depth': int(_tag(block, 'depth') or 0),
            'is_leaf': _tag(block, 'leafYn') == 'Y',
            'raw': block,
        })
    if not rows:
        raise HarvestError('11번가 카테고리 응답에서 category 블록을 하나도 못 찾음')
    return build_paths(rows)


# ── 스마트스토어 ─────────────────────────────────────────
def parse_smartstore(payload):
    """GET /v1/categories 평면 리스트 → 행. wholeCategoryName 이 경로 그 자체(재조립 불필요)."""
    import json as _json
    if not payload:
        raise HarvestError('스마트스토어 카테고리 응답이 비었음')
    rows = []
    for c in payload:
        code = str(c.get('id') or '')
        name = str(c.get('name') or '')
        path = str(c.get('wholeCategoryName') or '')
        if not code or not name or not path:
            raise HarvestError('스마트스토어 카테고리에 id/name/wholeCategoryName 누락: %r' % (c,))
        parts = path.split('>')
        rows.append({
            'code': code, 'name': name, 'parent_code': None,
            'depth': len(parts), 'is_leaf': bool(c.get('last')),
            'full_path': path, 'raw': _json.dumps(c, ensure_ascii=False),
        })
    return rows


# ── 쿠팡 ────────────────────────────────────────────────
def harvest_coupang(fetch, sleep, *, on_progress=None, on_chunk=None):
    """code='0' 루트부터 BFS. fetch(code:str)->data 노드 dict. child 는 1depth 하위만이라 노드마다 호출.

    리프 판정 = 그 노드를 fetch 했을 때 child 가 빔. DISABLED 는 행 제외 + 하위 미탐색.
    호출량이 크므로(노드 수 = 콜 수) sleep 콜러블로 마켓 예의를 지킨다(운영은 0.2s, 테스트는 no-op).
    on_progress(count) — 선택. 노드를 하나 처리할 때마다 그 시점까지 쌓인 행 수로 호출한다
    (쿠팡은 수 시간 걸릴 수 있어 "돌고 있는지" 를 보여주는 용도). None 이면 아무 일 없음.

    on_chunk(rows_so_far) — 선택 [2026-07-23 실측 사고 대응]. 쿠팡은 전량 완주까지 수 시간
    걸리는데(1,534건에서 22분간 진행 정지 = 백그라운드 데몬 스레드 사망 실측), 종전엔 전량을
    메모리에 쌓았다가 맨 마지막에만 저장해 중간에 죽으면 전부 유실됐다. 누적 행 수가
    CHUNK_SIZE(50) 단위로 늘 때마다 그 시점까지의 rows 리스트를 통째로 넘겨 호출한다 — 저장은
    콜백(호출부) 책임. None 이면 아무 일 없음(기존 호출부는 영향 없음).
    """
    import json as _json
    rows, queue, seen = [], ['0'], set()
    parents = {}    # code -> parent_code
    names = {}      # code -> full_path 조립용
    chunk_next = CHUNK_SIZE
    while queue:
        code = queue.pop(0)
        if code in seen:
            continue
        seen.add(code)
        data = fetch(code)
        if not isinstance(data, dict):
            raise HarvestError(f'쿠팡 카테고리 {code} 응답이 dict 아님: {data!r}')
        children = data.get('child') or []
        if code != '0':
            path = (names.get(parents.get(code), '') + '>' if parents.get(code) in names else '')
            full = path + str(data.get('name') or '')
            names[code] = full
            rows.append({
                'code': code, 'name': str(data.get('name') or ''),
                'parent_code': parents.get(code),
                'depth': full.count('>') + 1,
                'is_leaf': len(children) == 0,
                'full_path': full,
                'raw': _json.dumps({k: data[k] for k in data if k != 'child'}, ensure_ascii=False),
            })
            if on_chunk is not None and len(rows) >= chunk_next:
                on_chunk(list(rows))
                chunk_next += CHUNK_SIZE
        for ch_node in children:
            c_code = str(ch_node.get('displayItemCategoryCode') or '')
            if not c_code:
                raise HarvestError(f'쿠팡 카테고리 {code} 의 child 에 코드 누락: {ch_node!r}')
            # READY(준비중)는 ACTIVE 와 동일 취급 — 실데이터 의미는 Task 12 라이브 실측에서 확정
            if str(ch_node.get('status') or '') == 'DISABLED':
                continue
            parents[c_code] = code if code != '0' else None
            queue.append(c_code)
        sleep(0.2)
        if on_progress is not None:
            on_progress(len(rows))
    return rows


# ── ESM (옥션·G마켓 공용 — 사이트별 client 로 각각 호출) ──
def harvest_esm_site(fetch, sleep, *, on_progress=None, on_chunk=None):
    """fetch(code|None)->응답 dict. None=대분류 전체(/site-cats), code=하위(/site-cats/{code}).

    subCats 는 1depth 하위만 → isLeaf=False 인 노드만 재귀(리프는 재호출 안 함).
    실패 응답({resultCode!=0})은 HarvestError 로 표면화.
    seen 가드: 이미 방문(행 추가)한 catCode 는 다시 큐잉·행추가 하지 않는다(순환·중복 응답 방어).
    on_progress(count) — 선택. 노드를 하나 처리할 때마다 그 시점까지 쌓인 행 수로 호출한다.
    on_chunk(rows_so_far) — 선택. harvest_coupang 과 동일 기준 — 누적 행 수가 CHUNK_SIZE(50)
    단위로 늘 때마다 그 시점까지의 rows 리스트를 통째로 넘겨 호출한다(체크포인트 저장용).
    """
    import json as _json
    rows = []
    seen = set()
    queue = [(None, None, '')]          # (code, parent_code, parent_path)
    chunk_next = CHUNK_SIZE
    while queue:
        code, parent, ppath = queue.pop(0)
        data = fetch(code)
        if not isinstance(data, dict):
            raise HarvestError(f'ESM site-cats {code} 응답이 dict 아님: {data!r}')
        if data.get('resultCode') not in (None, 0):
            raise HarvestError(f"ESM site-cats {code} 실패: {data.get('resultCode')} {data.get('message')}")
        for sub in (data.get('subCats') or []):
            c_code, c_name = str(sub.get('catCode') or ''), str(sub.get('catName') or '')
            if not c_code or not c_name:
                raise HarvestError(f'ESM subCats 에 코드/이름 누락: {sub!r}')
            if c_code in seen:
                continue
            seen.add(c_code)
            full = (ppath + '>' if ppath else '') + c_name
            is_leaf = bool(sub.get('isLeaf'))
            rows.append({
                'code': c_code, 'name': c_name, 'parent_code': (code if code else None),
                'depth': full.count('>') + 1, 'is_leaf': is_leaf, 'full_path': full,
                'raw': _json.dumps(sub, ensure_ascii=False),
            })
            if on_chunk is not None and len(rows) >= chunk_next:
                on_chunk(list(rows))
                chunk_next += CHUNK_SIZE
            if not is_leaf:
                queue.append((c_code, code, full))
        sleep(0.3)
        if on_progress is not None:
            on_progress(len(rows))
    if not rows:
        raise HarvestError('ESM site-cats 수집 결과 0건 — 응답 구조 확인 필요')
    return rows


# ── 롯데온 (표준카테고리 — cheetah host) ─────────────────
def harvest_lotteon(fetch, sleep, *, on_progress=None):
    """fetch(skip:int, limit:int)->data 배열. 빈 배열이면 종료. 리프=자식 없는 노드(응답에 리프 플래그 없음).

    sleep 콜러블로 페이지마다 마켓 예의를 지킨다(운영은 0.2s, 테스트는 no-op) — harvest_coupang/harvest_esm_site 와 동일 기준.
    on_progress(count) — 선택. 페이지를 하나 처리할 때마다 그 시점까지 쌓인 원행 수로 호출한다.
    """
    import json as _json
    raw_rows, skip, LIMIT = [], 0, 100
    while True:
        batch = fetch(skip, LIMIT)
        if not isinstance(batch, list):
            raise HarvestError(f'롯데온 표준카테고리 skip={skip} 응답이 배열 아님: {type(batch)}')
        if not batch:
            break
        raw_rows.extend(batch)
        sleep(0.2)
        if on_progress is not None:
            on_progress(len(raw_rows))
        if len(batch) < LIMIT:
            break
        skip += LIMIT
    if not raw_rows:
        raise HarvestError('롯데온 표준카테고리 수집 결과 0건')
    rows = []
    for c in raw_rows:
        code, name = str(c.get('std_cat_id') or ''), str(c.get('std_cat_nm') or '')
        if not code or not name:
            raise HarvestError(f'롯데온 표준카테고리에 std_cat_id/std_cat_nm 누락: {c!r}')
        parent = c.get('upr_std_cat_id')
        # parse_eleven11 과 같은 기준 — 센티넬 None/''/0/'0' 은 parent 없음(루트)으로 취급
        parent_code = str(parent) if parent not in (None, '', 0, '0') else None
        rows.append({
            'code': code, 'name': name,
            'parent_code': parent_code,
            'depth': int(c.get('depth_no') or 0), 'is_leaf': False,
            'raw': _json.dumps(c, ensure_ascii=False),
        })
    has_child = {r['parent_code'] for r in rows if r['parent_code']}
    for r in rows:
        r['is_leaf'] = r['code'] not in has_child
    return build_paths(rows)


# ── 저장·diff ────────────────────────────────────────────
def save_snapshot(session, market, rows, now, *, partial=False):
    """수집 rows 를 market_categories 에 반영. 반환 {'added','updated','removed','total'}.

    빈 rows 거부 — 수집 실패가 '전부 삭제' 로 둔갑하는 조용한 실패 방지.
    사라진 코드는 삭제하지 않고 removed_at 마킹(M2 CategoryMap 재확정 강등의 근거) —
    같은 세션 안에서 그 코드를 가리키던 category_map 의 confirmed 행도 re_confirm 으로
    강등한다(ix_category_map_market_code 활용). 자동 확정 금지 원칙의 반대편: 사라진
    카테고리를 confirmed 로 방치하면 다음 등록이 존재하지 않는 코드로 조용히 나간다.

    partial=True [2026-07-23 체크포인트 저장 — 실측 사고 대응]: 쿠팡·ESM 처럼 노드당 1콜
    BFS 라 수 시간 걸리는 수집이 CHUNK_SIZE(50)건 단위로 콜백 저장할 때 쓰는 모드. 이 시점의 rows 는
    "지금까지 수집한 일부"일 뿐 "지금 존재하는 카테고리 전체"가 아니므로 ①빈 rows 도
    거부하지 않는다(진행 중엔 0건도 정상 — 아직 아무 청크도 안 찼을 수 있다) ②rows 에
    없는 기존 코드를 removed_at 마킹하지 않는다(부분 수집일 뿐인데 "없어졌다"고 판단할
    근거가 없다 — 조용한 오삭제 방지) ③그에 딸린 re_confirm 강등도 건너뛴다. added/updated
    는 이 청크에 담긴 코드에 대해서만 정상 계산된다. 전량 기준 removed 마킹·강등은 항상
    partial=False(기본값)인 최종 저장에서만 수행한다.
    """
    from lemouton.registration.models import MarketCategory, CategoryMapRow
    if not rows and not partial:
        raise HarvestError(f'{market}: 수집 결과 0건 — 스냅샷 저장 거부(전부삭제 오기록 방지)')
    existing = {r.code: r for r in session.query(MarketCategory).filter_by(market=market).all()}
    added = updated = removed = 0
    seen = set()
    for row in rows:
        code = row['code']
        if code in seen:
            # 배치 안 중복 code — 나중 것이 session.add() 로 또 들어가면 커밋 시점에야
            # UniqueConstraint IntegrityError 로 터진다(리뷰 지적). 여기서 먼저 표면화한다.
            raise HarvestError(f'{market}: 수집 결과에 중복 코드 {code}')
        seen.add(code)
        # depth=0 은 뜻이 있는 값(쿠팡 루트 등)일 수 있다 — `or 1` 은 0 을 조용히 1 로
        # 치환해버려 depth0 이 사라진다(리뷰 지적). 키가 없거나 None 일 때만 1 로 기본.
        depth = row['depth'] if row.get('depth') is not None else 1
        cur = existing.get(code)
        if cur is None:
            session.add(MarketCategory(
                market=market, code=code, name=row['name'],
                full_path=row['full_path'], parent_code=row.get('parent_code'),
                depth=depth, is_leaf=bool(row.get('is_leaf')),
                raw_json=row.get('raw'), harvested_at=now))
            added += 1
        else:
            changed = (cur.name != row['name'] or cur.full_path != row['full_path']
                       or cur.is_leaf != bool(row.get('is_leaf')) or cur.removed_at is not None)
            cur.name, cur.full_path = row['name'], row['full_path']
            cur.parent_code = row.get('parent_code')
            cur.depth = depth
            cur.is_leaf = bool(row.get('is_leaf'))
            cur.raw_json = row.get('raw')
            cur.harvested_at = now
            cur.removed_at = None
            if changed:
                updated += 1
    if not partial:
        for code, cur in existing.items():
            if code not in seen and cur.removed_at is None:
                cur.removed_at = now
                removed += 1
                # 이 코드를 confirmed 로 가리키던 맵핑은 이제 존재하지 않는 카테고리를
                # 가리킨다 — re_confirm 으로 강등해 사장님이 다시 골라야 함을 드러낸다.
                (session.query(CategoryMapRow)
                 .filter(CategoryMapRow.market == market,
                         CategoryMapRow.market_cat_code == code,
                         CategoryMapRow.status == 'confirmed')
                 .update({'status': 're_confirm', 'updated_at': now}, synchronize_session=False))
    session.commit()
    return {'added': added, 'updated': updated, 'removed': removed, 'total': len(seen)}
