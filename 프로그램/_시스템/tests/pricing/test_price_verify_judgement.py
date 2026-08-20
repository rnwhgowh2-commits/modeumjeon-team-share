"""3층 대조 판정 로직 테스트.

★ 이 테스트의 핵심 목적은 '확인불가를 일치로 뭉개지 않는다' 를 못 박는 것.
   크롤 실패를 '문제없음' 으로 세면 그게 조용한 실패다.
"""
import pytest

from lemouton.sourcing.price_verify import (
    VERDICT_MATCH, VERDICT_MISMATCH, VERDICT_UNKNOWN,
    LAYER_CRAWL, LAYER_CALC,
    judge, judge_surface, judge_benefits,
    resolve_columns, rows_to_xlsx, ALL_COLUMNS,
)


# ── ①↔② 표면가 ────────────────────────────────────────────────────────
class TestJudgeSurface:
    def test_같으면_일치(self):
        r = judge_surface(116900, 116900)
        assert r["verdict"] == VERDICT_MATCH
        assert r["diff"] == 0

    def test_다르면_불일치_차이금액_포함(self):
        # 롯데아이몰 사고 재현: 카드할인 먹은 값(109,900)을 표면가로 집음
        r = judge_surface(116900, 109900)
        assert r["verdict"] == VERDICT_MISMATCH
        assert r["diff"] == -7000
        assert "116,900" in r["reason"] and "109,900" in r["reason"]

    def test_사람입력_없으면_확인불가(self):
        assert judge_surface(None, 116900)["verdict"] == VERDICT_UNKNOWN

    def test_우리수집_없으면_확인불가(self):
        r = judge_surface(116900, None)
        assert r["verdict"] == VERDICT_UNKNOWN
        assert "크롤 데이터 없음" in r["reason"]

    def test_우리수집_0원은_확인불가_아니라_실제값(self):
        # 0 은 '없음' 이 아니라 유효한 값 — 폴백으로 뭉개면 안 된다
        r = judge_surface(116900, 0)
        assert r["verdict"] == VERDICT_MISMATCH
        assert r["ours"] == 0

    def test_문자열_숫자도_읽는다(self):
        assert judge_surface("116900", 116900)["verdict"] == VERDICT_MATCH

    def test_숫자로_못읽으면_확인불가(self):
        assert judge_surface("몰라요", 116900)["verdict"] == VERDICT_UNKNOWN


# ── ②↔③ 혜택 ─────────────────────────────────────────────────────────
class TestJudgeBenefits:
    STEPS = [
        {"name": "현대카드 청구할인", "type": "rate", "value": 0.0273,
         "deduct": 3191, "base_after": 113709},
        {"name": "L.POINT 적립", "type": "amount", "value": 2000,
         "deduct": 2000, "base_after": 111709},
    ]

    def test_사람이_혜택_안넣으면_확인불가(self):
        r = judge_benefits([], self.STEPS)
        assert r["verdict"] == VERDICT_UNKNOWN
        assert "확인불가" in r["reason"]

    def test_None_도_확인불가(self):
        assert judge_benefits(None, self.STEPS)["verdict"] == VERDICT_UNKNOWN

    def test_계산실패면_확인불가(self):
        r = judge_benefits([{"name": "L.POINT 적립", "amount": 2000}], None)
        assert r["verdict"] == VERDICT_UNKNOWN
        assert "계산 실패" in r["reason"]

    def test_금액_같으면_일치(self):
        r = judge_benefits([{"name": "L.POINT 적립", "amount": 2000}], self.STEPS)
        assert r["verdict"] == VERDICT_MATCH

    def test_금액_다르면_불일치(self):
        r = judge_benefits([{"name": "L.POINT 적립", "amount": 3000}], self.STEPS)
        assert r["verdict"] == VERDICT_MISMATCH
        assert r["items"][0]["status"] == "amount_diff"

    def test_1원_차이도_불일치(self):
        # 반올림 노이즈처럼 보이는 차이가 실제 버그였던 전례 — 삼키지 않는다
        r = judge_benefits([{"name": "L.POINT 적립", "amount": 2001}], self.STEPS)
        assert r["verdict"] == VERDICT_MISMATCH

    def test_우리계산에_없는_혜택은_빠짐(self):
        r = judge_benefits([{"name": "신한카드 할인", "amount": 5000}], self.STEPS)
        assert r["verdict"] == VERDICT_MISMATCH
        assert r["items"][0]["status"] == "missing"

    def test_공백_표기흔들림은_흡수(self):
        r = judge_benefits([{"name": "L . P O I N T 적립", "amount": 2000}], self.STEPS)
        assert r["verdict"] == VERDICT_MATCH

    def test_엔진에만_있는항목_기본은_불일치_아님_참고만(self):
        r = judge_benefits([{"name": "L.POINT 적립", "amount": 2000}], self.STEPS,
                           benefits_complete=False)
        assert r["verdict"] == VERDICT_MATCH
        assert len(r["extra_in_engine"]) == 1
        assert r["extra_in_engine"][0]["name"] == "현대카드 청구할인"

    def test_빠짐없이_입력_선언하면_엔진전용항목은_불일치(self):
        r = judge_benefits([{"name": "L.POINT 적립", "amount": 2000}], self.STEPS,
                           benefits_complete=True)
        assert r["verdict"] == VERDICT_MISMATCH
        assert "페이지에 없는 혜택" in r["reason"]

    def test_금액없는_입력행은_무시(self):
        r = judge_benefits([{"name": "L.POINT 적립", "amount": None}], self.STEPS)
        assert r["verdict"] == VERDICT_UNKNOWN

    def test_빈_steps_와_사람입력_있으면_전부_빠짐(self):
        r = judge_benefits([{"name": "L.POINT 적립", "amount": 2000}], [])
        assert r["verdict"] == VERDICT_MISMATCH
        assert r["items"][0]["status"] == "missing"


# ── 종합 판정 ─────────────────────────────────────────────────────────
class TestJudgeOverall:
    STEPS = [{"name": "L.POINT 적립", "type": "amount", "value": 2000,
              "deduct": 2000, "base_after": 114900}]

    def test_양층_일치라야_일치(self):
        r = judge(human_surface=116900, ours_surface=116900,
                  human_benefits=[{"name": "L.POINT 적립", "amount": 2000}],
                  engine_steps=self.STEPS, engine_final_price=114900)
        assert r["verdict"] == VERDICT_MATCH
        assert r["diverged_layers"] == []

    def test_표면가_갈리면_크롤파싱_문제로_지목(self):
        r = judge(human_surface=116900, ours_surface=109900,
                  human_benefits=[{"name": "L.POINT 적립", "amount": 2000}],
                  engine_steps=self.STEPS)
        assert r["verdict"] == VERDICT_MISMATCH
        assert r["diverged_layers"] == [LAYER_CRAWL]
        assert "크롤 파싱" in r["summary"]

    def test_혜택_갈리면_계산설정_문제로_지목(self):
        r = judge(human_surface=116900, ours_surface=116900,
                  human_benefits=[{"name": "L.POINT 적립", "amount": 5000}],
                  engine_steps=self.STEPS)
        assert r["verdict"] == VERDICT_MISMATCH
        assert r["diverged_layers"] == [LAYER_CALC]
        assert "계산" in r["summary"]

    def test_양층_갈리면_둘다_지목(self):
        r = judge(human_surface=116900, ours_surface=109900,
                  human_benefits=[{"name": "L.POINT 적립", "amount": 5000}],
                  engine_steps=self.STEPS)
        assert set(r["diverged_layers"]) == {LAYER_CRAWL, LAYER_CALC}

    # ★★ 이 프로젝트에서 가장 중요한 테스트 ★★
    def test_혜택_미입력은_표면가_일치해도_전체_확인불가(self):
        r = judge(human_surface=116900, ours_surface=116900,
                  human_benefits=[], engine_steps=self.STEPS)
        assert r["verdict"] == VERDICT_UNKNOWN, "확인불가를 일치로 뭉개면 안 된다"
        assert LAYER_CALC in r["unknown_layers"]

    def test_크롤데이터_없으면_전체_확인불가(self):
        r = judge(human_surface=116900, ours_surface=None,
                  human_benefits=[{"name": "L.POINT 적립", "amount": 2000}],
                  engine_steps=self.STEPS)
        assert r["verdict"] == VERDICT_UNKNOWN
        assert LAYER_CRAWL in r["unknown_layers"]

    def test_계산실패면_전체_확인불가(self):
        r = judge(human_surface=116900, ours_surface=116900,
                  human_benefits=[{"name": "L.POINT 적립", "amount": 2000}],
                  engine_steps=None)
        assert r["verdict"] == VERDICT_UNKNOWN

    def test_불일치가_확인불가보다_우선(self):
        r = judge(human_surface=116900, ours_surface=109900,
                  human_benefits=[], engine_steps=self.STEPS)
        assert r["verdict"] == VERDICT_MISMATCH

    def test_아무것도_없으면_확인불가(self):
        r = judge(human_surface=None, ours_surface=None)
        assert r["verdict"] == VERDICT_UNKNOWN
        assert set(r["unknown_layers"]) == {LAYER_CRAWL, LAYER_CALC}


# ── 엑셀 ──────────────────────────────────────────────────────────────
class TestExcel:
    def test_기본열_전체(self):
        assert resolve_columns(None) == ALL_COLUMNS

    def test_지정열_순서유지_및_미지열_제거(self):
        assert resolve_columns(["소싱처", "없는열", "검증일시"]) == ["소싱처", "검증일시"]

    def test_중복열_제거(self):
        assert resolve_columns(["소싱처", "소싱처"]) == ["소싱처"]

    def test_빈결과면_기본열로_폴백(self):
        assert resolve_columns(["없는열만"]) == ALL_COLUMNS

    def test_xlsx_바이트_생성(self):
        openpyxl = pytest.importorskip("openpyxl")
        data = rows_to_xlsx([{"소싱처": "롯데아이몰", "종합 판정": "불일치"}])
        assert isinstance(data, bytes) and data[:2] == b"PK"
        import io
        wb = openpyxl.load_workbook(io.BytesIO(data))
        ws = wb.active
        assert ws.title == "최종매입가 검증"
        assert [c.value for c in ws[1]] == ALL_COLUMNS
        row2 = {ALL_COLUMNS[i]: c.value for i, c in enumerate(ws[2])}
        assert row2["소싱처"] == "롯데아이몰"
        assert row2["종합 판정"] == "불일치"
