# -*- coding: utf-8 -*-
"""쿠팡 즉시할인쿠폰 **실전송 검증** — 오늘 걸고, 내일 확인하고, 내린다.

사장님 확정(2026-08-06): 「(가) 오늘 걸고 내일 확인」.
쿠팡 쿠폰은 **다음날 0시부터만** 켜진다(문서 명시) — 그래서 오늘/내일 두 번에 나눈다.

MODE 세 가지
  create : 쿠폰을 만들어 시험 상품 옵션 **하나**에만 붙인다 (오늘)
  verify : 쿠폰이 실제로 붙어 값이 깎였는지 읽어서 확인한다 (내일)
  expire : 쿠폰을 내린다 (확인 뒤 · 실패해도 크게 외친다)

왜 이 상품인가
  · **판매중지** 상품 → 고객이 살 수 없어 금전 위험 0
  · 옵션 **하나**에만 붙인다(전체 아님) — 붙는 범위를 최소로

🔴 계약ID(contractId)는 **지어내지 않는다** — 그 계정의 기존 쿠폰에서 읽는다.
   없으면 만들지 않고 멈춘다(추측한 값으로 쿠폰을 만들면 엉뚱한 계약에 걸린다).
env: MODE · TEST_ACCOUNT(기본 세소쿠팡) · TEST_PRODUCT(기본 15782833359)
"""
import json
import os
import sys
import time

sys.path.insert(0, '/app')

MODE = (os.environ.get('MODE') or 'create').strip()
ACCOUNT = os.environ.get('TEST_ACCOUNT') or '세소쿠팡'
PRODUCT = os.environ.get('TEST_PRODUCT') or '15782833359'
COUPON_NAME = '모음전 검증 쿠폰(자동)'
#: 🔴 실측(2026-08-06) — 133,900원 상품에 **100원(0.07%)은 거부**됐다:
#:   [CIE06]「이 프로모션을 적용하면 일부 옵션 ID에 대해 할인이 너무 작거나 너무 큽니다」.
#:   사장님 실쿠폰은 128,900원에 1,400원(약 1.09%)으로 통과 중 →
#:   하한이 **판매가의 1% 언저리**로 보인다(문서엔 없다). 1% 로 잡고 결과로 확정한다.
#:   지어낸 값이 아니라 **관측 두 개(거부 0.07% · 통과 1.09%) 사이에서 고른 값**이다.
DISCOUNT_RATE = 0.01


def _client_and_vendor():
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import UploadAccount
    from lemouton.uploader.market_fetch import _coupang_client
    from shared.platforms.coupang.promotions import vendor_id_of

    s = SessionLocal()
    try:
        a = (s.query(UploadAccount)
             .filter_by(market='coupang', account_key=ACCOUNT).first())
        if a is None:
            print(f'■ 계정을 못 찾았습니다: {ACCOUNT}'); sys.exit(1)
        env = a.env_prefix
    finally:
        s.close()
    client = _coupang_client(env)
    vid = vendor_id_of(client)
    if not vid:
        print('■ vendor_id 가 없습니다'); sys.exit(1)
    return client, vid


def _our_coupons(client, vid):
    """이름이 우리 것인 쿠폰만 골라 돌려준다(남의 쿠폰은 절대 안 건드린다)."""
    resp = client.request(
        'GET', f'/v2/providers/fms/apis/api/v2/vendors/{vid}/coupons',
        query='status=APPLIED&page=1&size=50&sort=desc')
    content = ((resp or {}).get('data') or {}).get('content') or []
    return [c for c in content if (c.get('promotionName') or '') == COUPON_NAME], content


def _any_contract_id(client, vid):
    """지난 쿠폰에서라도 계약ID를 찾는다 — 지어내지 않기 위해서다.

    🔴 실측(2026-08-06) — 세소쿠팡은 2년짜리 넓은 쿠폰이 **전 옵션을 덮어** 검증용
      쿠폰을 붙일 자리가 없었다(후보 12개 전부 [CIR08]). 그래서 쿠폰이 없는 다른
      계정으로 옮겨야 하는데, 그런 계정은 적용 중 쿠폰이 없어 계약ID도 안 나온다.
      계약ID는 쿠폰 상태와 무관한 **그 계정의 계약 번호**라 지난 것에서 읽어도 같다.
      ⚠️ 상태값은 마켓이 정한 것만 받는다 — 400 이 나면 그 상태는 조용히 건너뛴다.
    """
    for st in ('', 'EXPIRED', 'PAUSED', 'READY'):
        try:
            q = 'page=1&size=50&sort=desc'
            if st:
                q = f'status={st}&' + q
            resp = client.request(
                'GET', f'/v2/providers/fms/apis/api/v2/vendors/{vid}/coupons',
                query=q)
        except Exception:                               # noqa: BLE001
            continue                                    # 모르는 상태값 — 건너뛴다
        for c in (((resp or {}).get('data') or {}).get('content') or []):
            if c.get('contractId'):
                print(f'  (계약ID 를 지난 쿠폰 {c.get("couponId")} 에서 읽었습니다)')
                return c['contractId']
    return None


def _taken_items(client, vid):
    """이미 **다른 쿠폰이 쓰고 있는** 옵션들.

    🔴 실측(2026-08-06) — 한 옵션은 쿠폰 하나에만 붙는다:
      [CIR08]「해당 옵션은 이미 다른 쿠폰(89450797)에 발행되어져 있습니다」.
      사장님 기존 쿠폰이 쓰는 옵션을 골랐다가 거부당했다. 비켜 가야 한다.

    🔴🔴 **한 페이지만 읽으면 안 된다** — 2026-08-06 실측에서 50개만 읽고
      「비켜 갔다」고 말했는데 정작 고른 옵션이 51번째 이후에 있어 또 거부당했다.
      조용한 절반 읽기는 「다 봤다」로 읽힌다. 끝까지 넘긴다.
    """
    taken = set()
    for cpage in range(1, 11):
        resp = client.request(
            'GET', f'/v2/providers/fms/apis/api/v2/vendors/{vid}/coupons',
            query=f'status=APPLIED&page={cpage}&size=50&sort=desc')
        coupons = ((resp or {}).get('data') or {}).get('content') or []
        if not coupons:
            break
        for c in coupons:
            cid = c.get('couponId')
            if cid is None:
                continue
            for ipage in range(1, 41):          # 옵션은 수백 개일 수 있다
                r = client.request(
                    'GET',
                    f'/v2/providers/fms/apis/api/v1/vendors/{vid}'
                    f'/coupons/{cid}/items',
                    query=f'status=APPLIED&page={ipage}&size=50&sort=desc')
                items = ((r or {}).get('data') or {}).get('content') or []
                if not items:
                    break
                for it in items:
                    if it.get('vendorItemId') is not None:
                        taken.add(str(it['vendorItemId']))
        if len(coupons) < 50:
            break
    return taken


def _first_vendor_item(client, skip=None):
    """시험 상품의 옵션 하나 — 신형/구형 두 모양 모두 본다(2026-08-06 실측).

    skip 에 든 옵션(남의 쿠폰이 쓰는 것)은 건너뛴다.
    """
    from shared.platforms.coupang.products import get_product
    skip = skip or set()
    d = get_product(PRODUCT, client=client)
    for it in (d.get('items') or []):
        mp = it.get('marketplaceItemData') or {}
        vid_item = it.get('vendorItemId') or mp.get('vendorItemId')
        price = it.get('salePrice')
        if not isinstance(price, (int, float)):
            price = (mp.get('priceData') or {}).get('salePrice')
        if vid_item and str(vid_item) in skip:
            continue
        if vid_item and isinstance(price, (int, float)):
            return int(vid_item), int(price), d.get('sellerProductName') or PRODUCT
    return None, None, None


def _candidate_items(client, taken, limit=25, want=12):
    """붙여 볼 후보 옵션들 — (옵션ID, 판매가, 상품명).

    🔴🔴 실측(2026-08-06) — **목록에 없는 옵션도 그 쿠폰에 묶여 있다.**
      `status=APPLIED` 로 1,841개를 모았는데 거기 없던 93697560813 이
      [CIR08]「이미 다른 쿠폰(89450797)에 발행」으로 거부됐다.
      그 쿠폰은 2026-02-08~2028-11-04 짜리 넓은 프로모션이라, 개별로 나열되지
      않은 옵션까지 덮는 것으로 보인다.
      → **미리 읽어 피하는 방식엔 한계가 있다.** 후보를 여러 개 뽑아 두고
        붙여 보다 거부되면 다음 것으로 넘어간다(해 보고 배우기).
    """
    from shared.db import SessionLocal
    from lemouton.catalog.models import MarketProduct
    from shared.platforms.coupang.products import get_product

    s = SessionLocal()
    try:
        rows = (s.query(MarketProduct.market_product_id, MarketProduct.name)
                .filter_by(market='coupang', account_key=ACCOUNT)
                .filter(MarketProduct.status != 'sale')
                .filter(MarketProduct.deleted_at.is_(None))
                .order_by(MarketProduct.id.desc()).limit(limit).all())
    finally:
        s.close()

    out = []
    for pid, nm in rows:
        try:
            d = get_product(pid, client=client)
        except Exception as e:                          # noqa: BLE001
            print(f'    {pid} 상세 실패: {str(e)[:60]}')
            continue
        pname = d.get('sellerProductName') or nm or str(pid)
        for it in (d.get('items') or []):
            mp = it.get('marketplaceItemData') or {}
            iid = it.get('vendorItemId') or mp.get('vendorItemId')
            pr = it.get('salePrice')
            if not isinstance(pr, (int, float)):
                pr = (mp.get('priceData') or {}).get('salePrice')
            if not iid or not isinstance(pr, (int, float)):
                continue
            if str(iid) in taken:
                continue                # 확실히 물린 것은 애초에 뺀다
            out.append((int(iid), int(pr), pname))
            if len(out) >= want:
                return out
    return out


def _find_free_product(client, taken, limit=25):
    """안 물린 옵션이 하나라도 있는 **판매중지** 상품을 찾는다.

    우리 캐시(market_products)에서 그 계정의 판매중지 상품을 꺼내 차례로 본다 —
    마켓 목록을 다시 훑지 않는다(이미 밤마다 훑어 둔 것을 쓴다).
    """
    from shared.db import SessionLocal
    from lemouton.catalog.models import MarketProduct
    from shared.platforms.coupang.products import get_product

    s = SessionLocal()
    try:
        rows = (s.query(MarketProduct.market_product_id, MarketProduct.name)
                .filter_by(market='coupang', account_key=ACCOUNT)
                .filter(MarketProduct.status != 'sale')
                .filter(MarketProduct.deleted_at.is_(None))
                .order_by(MarketProduct.id.desc()).limit(limit).all())
    finally:
        s.close()

    for pid, nm in rows:
        if str(pid) == str(PRODUCT):
            continue
        try:
            d = get_product(pid, client=client)
        except Exception as e:                          # noqa: BLE001
            print(f'    {pid} 상세 실패: {str(e)[:80]}')
            continue
        for it in (d.get('items') or []):
            mp = it.get('marketplaceItemData') or {}
            iid = it.get('vendorItemId') or mp.get('vendorItemId')
            pr = it.get('salePrice')
            if not isinstance(pr, (int, float)):
                pr = (mp.get('priceData') or {}).get('salePrice')
            if iid and str(iid) not in taken and isinstance(pr, (int, float)):
                print(f'    → 찾았습니다: {pid} 옵션 {iid} ({nm or ""})'[:100])
                return int(iid), int(pr), (d.get('sellerProductName') or nm or pid)
    return None, None, None


def do_create(client, vid):
    from shared.platforms.coupang import promotions as P

    ours, allc = _our_coupons(client, vid)
    if ours:
        print(f'■ 이미 우리 검증 쿠폰이 있습니다(couponId={ours[0].get("couponId")}) — '
              f'새로 만들지 않습니다. verify 로 확인하거나 expire 로 내리세요.')
        return 0
    # 🔴 계약ID는 그 계정의 **실제 쿠폰**에서 읽는다(지어내지 않는다).
    #   적용 중 쿠폰이 없는 계정도 있어서, 지난 쿠폰까지 뒤진다 —
    #   계약ID는 쿠폰의 상태와 무관한 그 계정의 계약 번호다.
    contract_id = next((c.get('contractId') for c in allc if c.get('contractId')), None)
    if not contract_id:
        contract_id = _any_contract_id(client, vid)
    if not contract_id:
        print('■ 이 계정에서 계약ID를 찾지 못했습니다(쿠폰 이력 없음) — 만들지 않습니다.')
        return 1

    taken = _taken_items(client, vid)
    print(f'  (목록에 물린 것으로 나온 옵션 {len(taken)}개는 애초에 뺍니다)')
    cands = _candidate_items(client, taken)
    if not cands:
        print('■ 붙여 볼 옵션 후보를 못 찾았습니다'); return 1
    print(f'  후보 옵션 {len(cands)}개 확보 — 붙여 보며 되는 것을 찾습니다')
    item_id, price, pname = cands[0]

    start = P.tomorrow_midnight()
    end = start[:10] + ' 23:59:59'
    print('=' * 70)
    print(f'■ 쿠팡 쿠폰 실전송 — {pname}')
    print(f'  계정 {ACCOUNT} · 판매중지 상품 · 옵션 {item_id} 하나만')
    print(f'  판매가의 약 {DISCOUNT_RATE:.0%} 정액 · {start} ~ {end} · 계약ID {contract_id}')
    print('=' * 70)

    disc = max(int(-(-price * DISCOUNT_RATE // 10)) * 10, 100)   # 10원 단위 올림
    print(f'  깎을 값 {disc:,}원 = 판매가 {price:,} 의 약 {DISCOUNT_RATE:.0%}')
    rid = P.create_coupon(client, vid, contract_id=contract_id, name=COUPON_NAME,
                          unit='WON', value=disc, start_at=start, end_at=end)
    print(f'① 쿠폰 접수 — requestedId={rid}')

    coupon_id = None
    for _ in range(10):                       # 접수 ≠ 완료. 결과가 날 때까지 본다.
        time.sleep(3)
        st = P.check_request(client, vid, rid)
        print(f'  상태 {st["status"]} · 성공 {st["succeeded"]} · 실패 {st["failed"]}')
        if st['done']:
            coupon_id = st['coupon_id']
            break
    if not coupon_id:
        print('■ 쿠폰이 아직 만들어지지 않았습니다 — 잠시 뒤 verify 로 확인하세요')
        return 1
    print(f'② 쿠폰 생성됨 couponId={coupon_id}')

    # 🔴 붙여 보고 거부되면 **다음 후보로** — 목록만 읽어선 물린 옵션을 다 못 거른다
    attached = False
    for cand_id, cand_price, cand_name in cands:
        rids = P.add_items(client, vid, coupon_id, [cand_id])
        print(f'③ 옵션 {cand_id} 붙이기 접수 — {rids}')
        ok_this = False
        for r2 in rids:
            for _ in range(10):
                time.sleep(3)
                st = P.check_request(client, vid, r2)
                status = st['status']
                print(f'  상태 {status} · 성공 {st["succeeded"]} · 실패 {st["failed"]}'
                      + (f' · 사유 {st["failed_items"]}' if st['failed'] else ''))
                # 🔴 FAIL 도 **끝난 것**이다 — done 만 보고 돌면 실패를 성공처럼 끝낸다
                #   (2026-08-06 실제로 그렇게 보고했다: 붙이기 실패인데 「오늘 할 일 끝」).
                if st['done'] or status in ('FAIL', 'FAILED', 'ERROR'):
                    ok_this = bool(st['done'] and st['succeeded'] and not st['failed'])
                    break
            if ok_this:
                break
        if ok_this:
            item_id, price, pname = cand_id, cand_price, cand_name
            attached = True
            break
        print('    → 이 옵션은 안 됩니다. 다음 후보로 넘어갑니다.')

    if not attached:
        # 붙지 않은 쿠폰을 남기면 윙에 빈 쿠폰이 쌓인다 — 그 자리에서 내린다.
        print('\n🔴 옵션에 붙지 않았습니다 — 만든 쿠폰을 도로 내립니다.')
        ok = P.expire_coupon(client, vid, coupon_id)
        print(f'  쿠폰 {coupon_id} 내리기 → '
              f'{"✅" if ok else "🔴🔴 실패 — 쿠팡 윙에서 직접 내려 주세요"}')
        return 1

    print('\n' + '=' * 70)
    print(f'■ 오늘 할 일 끝 — 내일 {start[:10]} 0시부터 적용됩니다.')
    print(f'  내일 MODE=verify 로 확인하고, MODE=expire 로 내리세요.')
    print(f'  기준값: 옵션 {item_id} 판매가 {price:,} → 내일 {price - disc:,} 이어야 합니다')
    print('=' * 70)
    return 0


def do_verify(client, vid):
    from shared.platforms.coupang import promotions as P

    ours, _ = _our_coupons(client, vid)
    if not ours:
        print('■ 적용 중(APPLIED) 우리 쿠폰이 없습니다 — 아직 시작 전이거나 이미 내렸습니다')
        return 1
    c = ours[0]
    cid = c.get('couponId')
    print('=' * 70)
    print(f'■ 쿠폰 확인 — couponId={cid} · type={c.get("type")} · '
          f'discount={c.get("discount")} · {c.get("startAt")} ~ {c.get("endAt")}')

    r = client.request(
        'GET', f'/v2/providers/fms/apis/api/v1/vendors/{vid}/coupons/{cid}/items',
        query='status=APPLIED&page=1&size=50&sort=desc')
    items = ((r or {}).get('data') or {}).get('content') or []
    print(f'  붙은 옵션 {len(items)}개: '
          f'{[i.get("vendorItemId") for i in items][:5]}')

    # 우리 프로그램이 실제로 그 값을 읽어 내는지 — 같은 함수로 확인한다
    from lemouton.catalog.coupang_coupon import fetch_coupon_discounts
    table = fetch_coupon_discounts(client, vid)
    hit = {k: v for k, v in table.items()
           if k in {str(i.get('vendorItemId')) for i in items}}
    print(f'  우리 프로그램이 읽은 할인: {hit}')

    item_id, price, _ = _first_vendor_item(
        client, skip=_taken_items(client, vid) - {str(i.get('vendorItemId'))
                                                 for i in items})
    want = int(c.get('discount') or 0)      # 고정값이 아니라 **쿠폰이 말한 값**과 대조
    got = table.get(str(item_id))
    ok = (got == want)
    print(f'\n  옵션 {item_id} 판매가 {price:,} · 읽은 할인 {got} → '
          f'{"✅ 맞습니다" if ok else "❌ 다릅니다"}')
    if ok:
        print(f'  고객이 보는 값 = {price:,} − {got:,} = {price - got:,}')
    print('=' * 70)
    return 0 if ok else 1


def do_expire(client, vid):
    from shared.platforms.coupang import promotions as P
    ours, _ = _our_coupons(client, vid)
    if not ours:
        print('■ 내릴 우리 쿠폰이 없습니다(이미 내렸거나 만료)'); return 0
    bad = 0
    for c in ours:
        cid = c.get('couponId')
        ok = P.expire_coupon(client, vid, cid)
        print(f'  쿠폰 {cid} 내리기 → {"✅" if ok else "🔴🔴 실패"}')
        bad += 0 if ok else 1
    if bad:
        print('🔴🔴 내리지 못한 쿠폰이 있습니다 — 쿠팡 윙에서 직접 내려 주세요')
    return 1 if bad else 0


def do_diag(client, vid):
    """왜 「안 물렸다」고 본 옵션이 물려 있었나 — **읽기만** 해서 재본다.

    🔴 실측(2026-08-06) — status=APPLIED 로 모은 1,841개에 없던 옵션
      93697560813 이 [CIR08] 로 거부됐다. 무엇을 빠뜨렸는지 값으로 확인한다:
      상태 필터별 건수 · 그 옵션이 어느 목록에 있나.
    """
    targets = {'93697561761', '93697560813'}
    resp = client.request(
        'GET', f'/v2/providers/fms/apis/api/v2/vendors/{vid}/coupons',
        query='status=APPLIED&page=1&size=50&sort=desc')
    coupons = ((resp or {}).get('data') or {}).get('content') or []
    print(f'■ 적용 중 쿠폰 {len(coupons)}개')
    for c in coupons:
        print(f'  couponId={c.get("couponId")} · {c.get("promotionName")} · '
              f'{c.get("startAt")} ~ {c.get("endAt")}')

    for st in ('APPLIED', 'PENDING', 'EXPIRED', ''):
        for c in coupons:
            cid = c.get('couponId')
            found, total = set(), 0
            for page in range(1, 61):
                q = f'page={page}&size=50&sort=desc'
                if st:
                    q = f'status={st}&' + q
                r = client.request(
                    'GET',
                    f'/v2/providers/fms/apis/api/v1/vendors/{vid}'
                    f'/coupons/{cid}/items', query=q)
                items = ((r or {}).get('data') or {}).get('content') or []
                if not items:
                    break
                total += len(items)
                for it in items:
                    v = str(it.get('vendorItemId'))
                    if v in targets:
                        found.add(v)
            print(f'  [status={st or "(없음)"}] 쿠폰 {cid} 옵션 {total}개'
                  f' · 찾던 옵션 {sorted(found) or "없음"}')
    return 0


def main() -> int:
    client, vid = _client_and_vendor()
    if MODE == 'diag':
        return do_diag(client, vid)
    if MODE == 'create':
        return do_create(client, vid)
    if MODE == 'verify':
        return do_verify(client, vid)
    if MODE == 'expire':
        return do_expire(client, vid)
    print(f'■ 모르는 MODE: {MODE}'); return 1


if __name__ == '__main__':
    sys.exit(main())
