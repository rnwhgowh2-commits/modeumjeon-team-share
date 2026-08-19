# -*- coding: utf-8 -*-
"""옵션함(옵션 매트릭스)이 「상품을 만들 준비가 됐는가」 — 위상 3종.

여기서 말하는 대상은 **옵션함**이다(`Model.is_option_box=True`).
옵션함은 아직 파는 물건이 아니라, 상품을 만들 때 쓰는 **재료 묶음**이다.

위상은 셋뿐이다:
  · draft — 상품생성 준비 미완료 (아직 재료가 덜 갖춰짐)
  · ready — 상품생성 준비 완료   (지금 바로 상품을 만들 수 있음)
  · used  — 상품 생성에 사용됨   (이미 이 옵션함으로 상품을 만들었음)

🔴 사장님 확정 — 「준비 완료」는 아래 **네 가지를 전부** 만족할 때만이다.
   ① 옵션(SKU)이 1개 이상
   ② 축마다 값이 채워져 있다  ← **축이 0개면 불만족이다**
   ③ 소싱처 URL 이 1개 이상 붙어 있다
   ④ 모든 옵션이 소싱처와 이어져 있다
   하나라도 빠지면 draft. 이미 상품을 만들었으면(bundle_matrix_links 에 기록) used.

🔴 ②의 「축이 0개면 불만족」이 이 파일에서 제일 조심할 자리다.
   「모든 축에 값이 있나」를 곧이곧대로 물으면 **축이 하나도 없을 때 참이 된다**
   (수학에서 말하는 공허참). 그러면 아무것도 안 짠 빈 옵션함이 「준비 완료」로
   초록불이 뜨고, 사장님이 상품 생성을 눌렀다가 옵션 0개짜리 상품을 만들게 된다.
   그래서 축 개수를 **따로** 센다.

🔴 `bundles_tower.stage_of` 와 중복이 아니다 — **정의역이 서로소다.**
   · `stage_of`  : 판매 상품(`is_option_box=False`)이 정책·마켓까지 어디까지 갔나
   · `phase_of`  : 옵션함(`is_option_box=True`)이 상품이 될 준비가 됐나
   한 모델이 둘 다인 경우는 없다. 물어보는 것도 다르다(파는 진도 ↔ 만들 준비).
   그래서 상태값을 합치면 안 된다 — 합치면 「정책 적용」 같은 말이 옵션함에도
   붙어 화면이 거짓말을 한다.

🔴 라벨(한국어 이름)과 색(CSS 클래스)은 **이 파일 한 곳에서만** 정한다.
   화면(템플릿)이나 다른 모듈이 「상품생성 준비 완료」 같은 글자를 또 적으면,
   한쪽만 고쳤을 때 같은 옵션함이 화면마다 다른 이름으로 불린다.
   (`tests/design/test_screen_truthfulness.py` 의 「상태 이름과 색은 한 곳에서만
    온다」 규칙과 같은 취지다.)
   클래스 이름 체계는 `bundles_tower.STAGE_CLS` 와 **같은 것**을 쓴다
   (wait=회색 / mid=파랑 / sale=초록). 색 뜻이 화면 어디서나 같아야 하기 때문이다.
   다만 **라벨 글자는 겹치지 않는다** — 옵션함과 판매 상품은 다른 것이니까.

🔴 **축은 여기서 읽지 않는다.** 「값이 빈 축」을 세는 규칙은
   `lemouton/sourcing/axis_summary.py` 한 곳에만 있고, 여기는 그 결과를 받아 쓴다.
   안 그러면 무슨 사고가 나나 — 실제로 났던 일이다(2026-08-14 검수):
   같은 표(`bundle_option_steps`)를 두 모듈이 각자 읽어 **다른 숫자**를 냈다.
   축 값이 `["", "  "]`(공백만) 이거나 `[null]` 일 때 축 요약은 「값 없음」으로
   세는데 여기는 「값 있음」으로 세어, 목록 화면은 「값 없음」이라 적어 놓고
   배지는 **초록불(준비 완료)** 이 떴다. 사장님은 초록불을 믿고 상품을 만들고,
   만들어진 상품은 옵션이 텅 빈다. 규칙이 두 벌이면 언젠가 이렇게 갈린다.
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════
#  위상 3종 — 단일 진실 원천
# ═══════════════════════════════════════════════════════════════════════════
PHASE_DRAFT = 'draft'
PHASE_READY = 'ready'
PHASE_USED = 'used'

#: 화면에 보이는 순서 (덜 된 것 → 된 것 → 쓴 것)
PHASES = (PHASE_DRAFT, PHASE_READY, PHASE_USED)

PHASE_LABEL = {
    PHASE_DRAFT: '상품생성 준비 미완료',
    PHASE_READY: '상품생성 준비 완료',
    PHASE_USED: '상품 생성에 사용됨',
}
#: 배지 색 — 회색 / 파랑 / 초록. `bundles_tower.STAGE_CLS` 와 같은 이름 체계다.
PHASE_CLS = {
    PHASE_DRAFT: 'wait',
    PHASE_READY: 'mid',
    PHASE_USED: 'sale',
}

#: 한 번에 IN 절(`.in_(…)`)에 넣는 개수 — 이 값은 **여기 한 곳에서만** 정한다.
#: 쓰는 곳: `matrix/unbuilt.py` · `sourcing/axis_summary.py` ·
#:          `webapp/routes/optgen_sku.py`. 셋 다 **함수 안에서 그때그때 읽어** 쓴다
#:          (`from lemouton.matrix.readiness import _CHUNK`). 숫자를 그쪽에 또 적으면
#:          한쪽만 고쳐졌을 때 그 화면만 라이브에서 계속 터진다.
#:
#: 🔴 [2026-08-14 실측으로 바로잡음] 예전엔 여기에 「SQLite 파라미터 상한(999)」이라
#:    적혀 있었는데 **틀린 근거였다.** 999 는 SQLite 3.32 **이전**의 기본값이다.
#:    이 환경에서 직접 재 본 결과:
#:      · SQLite 3.50.4 — 32,766개까지 받고 **32,767개에서** `too many SQL variables`
#:      · 라이브 PostgreSQL — 한 번에 보내는 값 개수를 2바이트로 세는 프로토콜이라
#:        65,535개가 한도다. (여기서 직접 재지는 못했다 — 문서상 한도다.)
#:    틀린 숫자를 근거로 남겨 두면 다음 사람이 「999 가 한도라니 800 까진 괜찮겠지」
#:    같은 엉뚱한 판단을 한다. 그래서 실제로 잰 숫자를 적어 둔다.
#:
#: 그러면 한도가 훨씬 큰데 왜 그래도 500 에서 자르나 — 정직하게 적는다.
#:   ① 한도는 **DB 마다·빌드마다 다르다.** SQLite 를 낮은 값으로 컴파일해 넣은
#:      파이썬, 중간에 낀 연결 대리인(pgbouncer 류) 등 우리가 못 고르는 변수가 있다.
#:      벽이 어디인지 환경마다 다르면, 벽에서 멀찍이 떨어져 있는 게 맞다.
#:   ② 자르는 값이 **거의 공짜다.** 이 환경에서 코드 32,000개를 물어본 실측 —
#:      한 번에 = 36.6ms, 500개씩 64묶음 = 41.8ms. 크게 잡아 봐야 5ms 아낀다.
#:   ③ 한 번에 받아 오는 줄 수가 묶여 있어야 응답 시간과 메모리가 갑자기 안 튄다.
#: 🔴 「한도가 크더라」가 「안 잘라도 되더라」는 아니다. 안 자르면 옵션함이 쌓인
#:    날에만 조회가 통째로 실패한다 — 개발할 땐 영영 멀쩡하고 라이브에서만 어느 날
#:    갑자기 화면이 죽는, 제일 늦게 발견되는 부류의 사고다.
_CHUNK = 500

#: 축 요약에 아예 없는 코드에 쓰는 「축 0개」. `axis_batch` 는 물어본 코드를 전부
#: 돌려주므로 여기 걸리는 건 배선이 어긋난 때뿐이고, 그때는 미완료 쪽으로 떨어진다.
#: 🔴 읽기만 한다 — 고쳐 쓰면 다음 줄 판정까지 같이 바뀐다(딕트는 같은 물건이다).
_NO_AXIS = {'axis_names': (), 'empty_axes': 0}


def phase_of(*, options: int, axes: int, empty_axes: int,
             urls: int, mapped_full: bool | None, used: bool) -> tuple[str, list[str]]:
    """네 가지 사실을 받아 (위상, 미완료 사유 목록) 을 돌려준다.

    Args:
        options: 이 옵션함이 가진 옵션(SKU) 개수.
        axes: 축(단계) 개수. **0이면 그것만으로 미완료다**(위 ② 참조).
        empty_axes: 값이 하나도 안 채워진 축의 개수.
        urls: 붙어 있는 소싱처 URL 개수.
        mapped_full: 모든 옵션이 소싱처와 이어졌나. **3값이다.**
            True  — 전부 이어짐
            False — 일부만 이어짐
            None  — 판정 불가(붙은 URL 이 0개라 이을 대상 자체가 없다)
            🔴 None 을 False 로 뭉개면 안 된다. 「아니다」와 「모른다」는 다른 값이고,
               뭉개면 화면이 「소싱처 맵핑 미완료」라고 **단정**해 버린다. 실제로는
               URL 이 없어서 못 잰 것뿐이라, 사장님이 엉뚱한 곳을 손보게 된다.
        used: 이 옵션함으로 이미 상품을 만들었나.

    Returns:
        (위상, 사유 목록). 사유는 화면에 그대로 찍는 짧은 한국어 구.
        준비 완료면 사유는 빈 목록이다.

    🔴 사유가 중복되면 안 된다 — URL 이 0개일 때 「소싱처 URL 없음」과
       「소싱처 맵핑 …」이 같이 뜨면, 손볼 곳이 두 군데인 줄 알게 된다.
       실제 손볼 곳은 하나(URL 붙이기)뿐이다.
    """
    missing: list[str] = []

    # ① 옵션이 있나
    if options < 1:
        missing.append('옵션 없음')

    # ② 축마다 값이 채워져 있나 — 🔴 축이 0개면 「전부 채워짐」이 아니라 미완료다.
    #    else 로 이어 붙인 이유: 축이 0개면 빈 축도 0개라, 두 사유가 같이 뜰 수 없다.
    if axes < 1:
        missing.append('축 없음')
    elif empty_axes > 0:
        missing.append(f'값이 빈 축 {empty_axes}개')

    # ③ 소싱처 URL 이 붙어 있나
    if urls < 1:
        missing.append('소싱처 URL 없음')

    # ④ 모든 옵션이 소싱처와 이어졌나
    if mapped_full is False:
        missing.append('소싱처 맵핑 미완료')
    elif mapped_full is None and urls >= 1:
        # URL 은 있는데 이어졌는지 못 쟀다 — 「안 이어졌다」로 단정하지 않고
        # 「모른다」를 그대로 말한다. 모르는 채로 준비 완료라고 할 수는 없다.
        # (urls 가 0이면 위 ③ 이 이미 같은 말을 하므로 여기선 침묵한다.)
        missing.append('소싱처 맵핑 확인 불가')

    if used:
        # 이미 만든 것은 준비 여부를 따질 단계가 지났다. 사유는 참고로 그대로 둔다
        # (화면이 「사용됨인데 축이 비었다」 같은 뒷정리 거리를 보여 줄 수 있게).
        return PHASE_USED, missing
    return (PHASE_READY if not missing else PHASE_DRAFT), missing


def _axis_counts(summary) -> tuple[int, int]:
    """축 요약 한 줄 → (축 개수, 값이 빈 축 개수).

    받는 것은 `axis_summary.axis_batch()` 가 코드마다 돌려주는 딕트다
    (`axis_names` · `empty_axes` 만 쓴다).

    🔴 엉뚱한 모양이 들어오면 **조용히 넘어가지 않고 바로 말한다.** 예전처럼
       축 개수 숫자(`{code: 2}`)를 넘기면 이 함수가 그걸 「축 0개」로 읽어,
       멀쩡히 채워진 옵션함이 전부 「축 없음」 미완료가 된다. 에러가 안 나므로
       화면만 조용히 틀리고, 사장님은 다 채운 옵션함을 계속 들여다보게 된다.
    """
    if not isinstance(summary, dict) or 'axis_names' not in summary:
        raise TypeError(
            'axes 에는 axis_summary.axis_batch() 가 돌려준 것을 그대로 넘겨야 합니다 '
            "— 축 개수 숫자가 아니라 {'axis_names': [...], 'empty_axes': n} 모양입니다. "
            f'받은 것: {summary!r}')
    return len(summary['axis_names']), int(summary.get('empty_axes') or 0)


def phase_batch(session, codes: list[str], *,
                options: dict, urls: dict, mapped: dict, axes: dict) -> dict:
    """옵션함 여러 개의 위상을 **쿼리 1개**로 한꺼번에 판정한다.

    Args:
        session: SQLAlchemy 세션.
        codes: 옵션함 `model_code` 목록.
        options: {model_code: 옵션 개수}. 없는 열쇠는 0으로 본다.
        urls: {model_code: 소싱처 URL 개수}. 없는 열쇠는 0으로 본다.
        mapped: {model_code: True|False|None}. 없는 열쇠는 **None**(모름)으로 본다.
            🔴 여기서 기본값을 False 로 두면 안 된다 — 안 넘어온 것을
               「안 이어졌다」로 단정하게 된다.
        axes: `axis_summary.axis_batch(session, codes)` 결과 **그대로**.
            🔴 축을 여기서 다시 읽지 않는 이유는 모듈 맨 위 설명에 있다 —
               규칙이 두 벌이 되면 같은 옵션함을 두고 목록 글자와 배지가
               서로 다른 말을 한다(실제로 갈려 있었다).
            🔴 `axis_batch` 는 물어본 코드를 **전부** 돌려주므로 여기에 빠진 코드가
               있다면 배선이 어긋난 것이다. 그때는 축 0개로 본다 — 「미완료」쪽으로
               떨어져야지, 모르는 채로 초록불이 켜지면 안 된다.

    Returns:
        {model_code: {'phase','label','cls','missing'}} — 물어본 코드는 **전부** 들어간다.
        (줄이 없는 코드가 빠지면 화면에 구멍이 생기고, 화면은 그걸 「모름」이 아니라
         「없음」으로 그린다.)

    🔴 옵션 개수·URL 개수·맵핑 여부·축 요약은 **호출자가 넘겨준다.** 여기서 또 세지 않는다.
       그 넷은 이미 다른 곳(소싱처 집계·옵션 목록·축 요약)이 화면을 그리려고 세고 있다.
       여기서 다시 세면 (a) 같은 일을 두 번 하고 (b) 언젠가 두 셈이 갈려
       같은 화면의 배지와 숫자가 서로 다른 말을 한다.

    🔴 **쿼리는 codes 길이와 무관하게 묶음당 1개다**(used 판정 하나뿐).
       줄마다 한 번씩 묻는 순간(N+1) 옵션함 200개짜리 화면이 200쿼리가 되어
       눈에 띄게 느려진다. 이 계약은 시험(`test_readiness.py`)이 쿼리 수를 세어
       못 박아 두었다. 축 조회 1개는 `axis_batch` 쪽으로 옮겨 갔을 뿐 사라진 게 아니다.
    """
    from sqlalchemy import func
    from sqlalchemy.orm import aliased

    from lemouton.matrix.models import BundleMatrixLink, MatrixOption

    # 중복·빈 값을 걷어내되 순서는 지킨다(화면이 준 순서 그대로 돌려주기 위해).
    clean: list[str] = []
    seen: set[str] = set()
    for c in codes or []:
        if c and c not in seen:
            seen.add(c)
            clean.append(c)
    if not clean:
        return {}

    used: set[str] = set()

    # 이 옵션함의 매트릭스로 만든 상품이 있나 (used 판정).
    # bundle_matrix_links 는 「만든 상품 → 재료 매트릭스」를 가리키므로,
    # 매트릭스를 거쳐야 옵션함 코드에 닿는다.
    #
    # 🔴 **파생 매트릭스는 `model_code` 가 비어 있다**(`service.create_derived` 는
    #    `origin_id` 만 채운다). 그래서 예전처럼 `MatrixOption.model_code` 로만 이으면
    #    파생으로 만든 상품이 이 조인에 **영영 안 걸린다**. 안 고치면 무슨 사고가 나나 —
    #    이미 상품을 만든 옵션함에 초록불(준비 완료)이 켜져 사장님이 같은 옵션함으로
    #    상품을 **또** 만드시고, 마켓에 같은 상품이 두 번 올라간다. 게다가 같은 행위가
    #    원본에서 하면 used, 파생에서 하면 ready 로 갈린다 — 정하고 그런 게 아니라
    #    조인이 흘린 것이다. (상품 만들기는 파생에서도 열려 있다:
    #    `build_service.create_bundle_from_matrix` 독스트링 「원본·파생 모두 가능」,
    #    `webapp/routes/matrix.py` build_bundle_api 가 kind 를 안 가린다.)
    #    그래서 파생이면 `origin_id` 를 한 번 더 타고 **원본의 코드로 접는다.**
    #    파생의 파생은 없다(`create_derived` 가 막는다) — 한 번만 타면 충분하다.
    Origin = aliased(MatrixOption)
    owner_code = func.coalesce(MatrixOption.model_code, Origin.model_code)
    for i in range(0, len(clean), _CHUNK):
        chunk = clean[i:i + _CHUNK]
        for (code,) in (session.query(owner_code)
                        .join(BundleMatrixLink,
                              BundleMatrixLink.matrix_option_id == MatrixOption.id)
                        .outerjoin(Origin, Origin.id == MatrixOption.origin_id)
                        .filter(owner_code.in_(chunk))
                        .distinct().all()):
            if code:
                used.add(code)

    out: dict[str, dict] = {}
    for code in clean:
        n_axes, n_empty = _axis_counts(axes.get(code) or _NO_AXIS)
        phase, missing = phase_of(
            options=int(options.get(code) or 0),
            axes=n_axes,
            empty_axes=n_empty,
            urls=int(urls.get(code) or 0),
            mapped_full=mapped.get(code),      # 없으면 None(모름) — False 아님
            used=code in used,
        )
        out[code] = {
            'phase': phase,
            'label': PHASE_LABEL[phase],
            'cls': PHASE_CLS[phase],
            'missing': missing,
        }
    return out
