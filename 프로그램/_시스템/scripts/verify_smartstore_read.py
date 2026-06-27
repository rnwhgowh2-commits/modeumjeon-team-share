"""[P0-2] 스마트스토어 읽기경로 실검증 — 쓰기 없음, 옵션조회만.

목적:
  - 스마트스토어 API 가 실제로 응답하는지(기존 ok 36건이 라이브인지) 확인
  - 가져온 옵션을 모음전 옵션과 매칭해 매칭률 보고

사용 (cd 프로그램/_시스템):
  python -m scripts.verify_smartstore_read              # DB의 기존 상품ID 자동 선택
  python -m scripts.verify_smartstore_read 12345678     # 특정 상품번호 지정
  python -m scripts.verify_smartstore_read 12345678 AF  # 상품번호 + 모음전 model_code
"""
import io
import sys

# Windows cp949 콘솔에서도 이모지·em-dash 출력이 깨지지 않게 (코드베이스 관용구)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from shared.db import SessionLocal
from lemouton.sourcing.models import Option
from lemouton.uploader.models import MarketRegistration
from lemouton.uploader.market_fetch import fetch_market_options
from lemouton.uploader.linker import match_market_options_to_skus


def _pick_existing_product_id(s) -> str | None:
    row = (s.query(MarketRegistration)
           .filter(MarketRegistration.market == "smartstore",
                   MarketRegistration.market_product_id.isnot(None))
           .first())
    return row.market_product_id if row else None


def main(argv):
    product_id = argv[1] if len(argv) > 1 else None
    model_code = argv[2] if len(argv) > 2 else None

    s = SessionLocal()
    try:
        if not product_id:
            product_id = _pick_existing_product_id(s)
            if not product_id:
                print("DB에 저장된 스마트스토어 상품ID가 없어요. 상품번호를 인자로 주세요.")
                return 2
            print(f"[자동선택] DB의 기존 상품ID: {product_id}")

        print(f"[읽기호출] smartstore 상품 {product_id} 옵션 조회 중...")
        fr = fetch_market_options("smartstore", product_id)
        if not fr.success:
            print(f"❌ 조회 실패: {fr.error}")
            return 1

        print(f"✅ 응답 OK — 상품명: {fr.product_name} / 옵션 {len(fr.options)}개")
        for o in fr.options[:30]:
            print(f"   - opt {o.option_id}: 색상={o.color} 사이즈={o.size} 재고={o.stock}")

        if model_code:
            opts = s.query(Option).filter_by(model_code=model_code).all()
            bundle = [{"canonical_sku": x.canonical_sku, "color_code": x.color_code,
                       "color_display": x.color_display, "size_code": x.size_code,
                       "size_display": x.size_display} for x in opts]
            rows = match_market_options_to_skus(bundle, fr.options)
            matched = sum(1 for r in rows if r.status == "matched")
            print(f"\n[매칭] model_code={model_code} 옵션 {len(bundle)}개 기준")
            print(f"   매칭 {matched} / 전체 {len(rows)} "
                  f"(unmatched {sum(1 for r in rows if r.status=='unmatched')}, "
                  f"ambiguous {sum(1 for r in rows if r.status=='ambiguous')})")
        return 0
    finally:
        s.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
