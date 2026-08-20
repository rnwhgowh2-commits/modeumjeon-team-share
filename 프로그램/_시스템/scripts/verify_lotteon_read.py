"""[롯데온] 읽기경로 실검증 — 쓰기 없음, 상품 상세조회(옵션)만.

목적:
  - 롯데온 Open API 인증(Bearer 인증키 + 출발지 IP 등록)이 실제 통과하는지 확인
  - 상품 상세조회로 옵션(sitmNo·색·사이즈·재고·가격)이 실제로 오는지 실증
  - 가져온 옵션을 모음전 옵션과 매칭해 매칭률 보고

선행:
  .env 에 LOTTEON_MAIN_API_KEY, LOTTEON_MAIN_TR_NO 설정 +
  판매자 센터에서 인증키에 이 서버의 출발지 IP 등록(미등록 시 403).

사용 (cd 프로그램/_시스템):
  python -m scripts.verify_lotteon_read LO13640xx        # 판매자상품번호(spdNo) 지정
  python -m scripts.verify_lotteon_read LO13640xx AF     # spdNo + 모음전 model_code
"""
import io
import sys
from pathlib import Path

# Windows cp949 콘솔에서도 이모지·em-dash 출력이 깨지지 않게 (코드베이스 관용구)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# .env 를 shared.platforms(LOTTEON dict) import 전에 먼저 로드해야 api_key/tr_no 가 채워진다.
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from shared.db import SessionLocal
from shared.platforms import LOTTEON
from lemouton.sourcing.models import Option
from lemouton.uploader.market_fetch import fetch_market_options
from lemouton.uploader.linker import match_market_options_to_skus


def main(argv):
    if len(argv) < 2:
        print("판매자상품번호(spdNo)를 인자로 주세요.  예) python -m scripts.verify_lotteon_read LO13640xx")
        return 2
    spd_no = argv[1]
    model_code = argv[2] if len(argv) > 2 else None

    if not LOTTEON.get("api_key"):
        print("❌ LOTTEON_MAIN_API_KEY 가 비어있어요. .env 확인 후 다시 시도하세요.")
        return 2
    if not LOTTEON.get("tr_no"):
        print("❌ LOTTEON_MAIN_TR_NO(거래처번호) 가 비어있어요. .env 확인 후 다시 시도하세요.")
        return 2

    print(f"[읽기호출] lotteon 상품 {spd_no} 상세조회 중... (base={LOTTEON['base_url']})")
    fr = fetch_market_options("lotteon", spd_no)
    if not fr.success:
        print(f"❌ 조회 실패: {fr.error}")
        print("   · 401 → 인증키 오류(LOTTEON_MAIN_API_KEY)")
        print("   · 403 → 출발지 IP 미등록(판매자 센터에서 이 서버 IP 를 인증키에 등록)")
        return 1

    print(f"✅ 응답 OK — 상품명: {fr.product_name} / 옵션 {len(fr.options)}개")
    for o in fr.options[:30]:
        print(f"   - opt {o.option_id}: 색상={o.color} 사이즈={o.size} 재고={o.stock} 가격={o.price}")

    if model_code:
        s = SessionLocal()
        try:
            opts = s.query(Option).filter_by(model_code=model_code).all()
            bundle = [{"canonical_sku": x.canonical_sku, "color_code": x.color_code,
                       "color_display": x.color_display, "size_code": x.size_code,
                       "size_display": x.size_display} for x in opts]
        finally:
            s.close()
        rows = match_market_options_to_skus(bundle, fr.options)
        matched = sum(1 for r in rows if r.status == "matched")
        print(f"\n[매칭] model_code={model_code} 옵션 {len(bundle)}개 기준")
        print(f"   매칭 {matched} / 전체 {len(rows)} "
              f"(unmatched {sum(1 for r in rows if r.status=='unmatched')}, "
              f"ambiguous {sum(1 for r in rows if r.status=='ambiguous')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
