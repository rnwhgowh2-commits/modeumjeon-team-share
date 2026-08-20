# -*- coding: utf-8 -*-
"""[2026-08-12 노션] 상품관리 — 「상태에 따라 눌러서 나오는 결과 다름」 고장.

사장님 확정: **고장 신고. 항상 같아야 한다.**

라이브 실측(2026-08-12 · /bundles 92개):
    상태 1「상품 생성」        89개 → /optgen/product/<id>
    상태 2「정책 적용」         2개 → **/bundles/<code>**   ← 딴 화면
    상태 3「판매중」            1개 → /optgen/product/<id>
상태 2 가 전부 딴 데로 가서 「상태에 따라 다르다」로 보였지만, 실제로 갈린 기준은
**원본 매트릭스(matrix_id)가 있느냐**였다. 상태와는 우연한 상관관계다.

🔴 두 목적지는 서로 다른 화면이다 —
   · /optgen/product/<id> = 조립대(옵션생성 & 상품생성 소속)
   · /bundles/<code>      = 모음전 상세(다른 메뉴·다른 템플릿)
   그런데 단추 이름은 둘 다 「✏️ 편집 (생성 탭)」이다. 이름까지 사실과 다르다.

🔴 원본이 왜 없어지나 — `ensure_origin` 이 `deleted_at` 을 안 본다.
   한 번 지워지면 「이미 있다」고 보고 새로 안 만들어서, 백필 3경로
   (scheduler.jobs · admin_owner_snapshot · admin_display_no)가 영영 못 고친다.
"""
import pytest

from lemouton.matrix.models import MatrixOption, KIND_ORIGIN


def _read(path):
    import io
    return io.open(path, encoding='utf-8').read()


# ── ① 문(door)이 하나인가 ─────────────────────────────────────

def test_편집_단추는_상태와_무관하게_한_곳으로_간다():
    """🔴 목록이 matrix_id 를 못 실어 보내면 딴 화면으로 새는 분기가 있었다.

    코드 기준 주소 하나로 보내면, 원본이 있든 없든 **언제나 같은 화면**에 닿는다.
    """
    html = _read('webapp/templates/bundles/tower.html')
    편집줄 = [ln for ln in html.splitlines() if 'editHref' in ln and '=' in ln]
    assert 편집줄, 'editHref 를 못 찾았다(시험이 헛돌았다)'
    한줄 = '\n'.join(편집줄)
    assert 'dataset.matrix' not in 한줄 and '?' not in 한줄, \
        '편집 목적지가 아직 갈린다 — 상태(원본 유무)에 따라 딴 화면으로 샌다'
    assert '/optgen/product/by-code/' in 한줄, '코드 기준 한 주소로 보내야 한다'


def test_옵션_매트릭스_탭_단추도_같은_문을_쓴다():
    """t2 의 「매트릭스 수정」도 같은 주소여야 한다 — 문이 둘이면 또 갈린다."""
    html = _read('webapp/templates/bundles/tower.html')
    assert html.count('/optgen/product/by-code/') >= 2


# ── ② 지워진 원본이 되살아나는가 ──────────────────────────────

def test_지워진_원본은_되살아난다():
    """🔴 `ensure_origin` 이 지워진 것을 그대로 돌려줘, 한 번 지우면 영영 안 돌아왔다.

    이게 라이브에서 상태 2 상품 2개가 딴 화면으로 가던 뿌리다.
    ★ 새로 만들지 않고 되살린다 — (model_code, kind) 유니크 제약이 `deleted_at` 을
      안 보므로 새 행을 넣으면 터진다(이 시험이 실제로 잡아냈다).
    """
    from datetime import datetime
    from shared.db import SessionLocal
    from lemouton.matrix.service import ensure_origin
    from lemouton.sourcing.models import Model

    s = SessionLocal()
    try:
        code = '테스트_원본되살리기_' + datetime.now().strftime('%H%M%S%f')
        m = Model(model_code=code, model_name_raw='되살리기 시험')
        s.add(m)
        s.flush()

        first = ensure_origin(s, m)
        s.flush()
        first.deleted_at = datetime.now()      # 사장님이 옵션 묶음을 지웠다
        s.flush()

        again = ensure_origin(s, m)
        s.flush()
        assert again.deleted_at is None, \
            '지워진 원본을 그대로 돌려주면 화면은 영영 못 찾는다'
        assert again.id == first.id, \
            '새로 만들면 (model_code, kind) 유니크 제약에 걸려 터진다 — 되살려야 한다'
    finally:
        s.rollback()
        s.close()


def test_살아있는_원본은_두_번_안_만든다():
    """멱등 — 원본은 모델당 하나여야 한다(안 그러면 어느 쪽이 진짜인지 모른다)."""
    from datetime import datetime
    from shared.db import SessionLocal
    from lemouton.matrix.service import ensure_origin
    from lemouton.sourcing.models import Model

    s = SessionLocal()
    try:
        code = '테스트_원본멱등_' + datetime.now().strftime('%H%M%S%f')
        m = Model(model_code=code, model_name_raw='멱등 시험')
        s.add(m)
        s.flush()
        a = ensure_origin(s, m)
        s.flush()
        b = ensure_origin(s, m)
        assert a.id == b.id
    finally:
        s.rollback()
        s.close()


def test_백필도_지워진_원본을_메운다():
    """`ensure_all_origins` 의 「이미 있다」 판정도 같은 눈으로 봐야 한다.

    여기가 어긋나 있으면 스케줄러가 매 사이클 돌아도 구멍이 안 메워진다.
    """
    from datetime import datetime
    from shared.db import SessionLocal
    from lemouton.matrix.service import ensure_origin, ensure_all_origins
    from lemouton.sourcing.models import Model
    from sqlalchemy import select

    s = SessionLocal()
    try:
        code = '테스트_백필_' + datetime.now().strftime('%H%M%S%f')
        m = Model(model_code=code, model_name_raw='백필 시험')
        s.add(m)
        s.flush()
        mo = ensure_origin(s, m)
        s.flush()
        mo.deleted_at = datetime.now()
        s.flush()

        ensure_all_origins(s, limit=None)
        s.flush()
        alive = s.scalars(select(MatrixOption).where(
            MatrixOption.model_code == code,
            MatrixOption.kind == KIND_ORIGIN,
            MatrixOption.deleted_at.is_(None))).all()
        assert len(alive) == 1, '백필이 지워진 원본을 못 메웠다'
    finally:
        s.rollback()
        s.close()


# ── ③ 코드 기준 주소가 실제로 닿는가 ──────────────────────────

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_코드로_들어가면_조립대로_보낸다(client):
    from datetime import datetime
    from shared.db import SessionLocal
    from lemouton.matrix.service import ensure_origin
    from lemouton.sourcing.models import Model

    code = '테스트_코드주소_' + datetime.now().strftime('%H%M%S%f')
    s = SessionLocal()
    try:
        m = Model(model_code=code, model_name_raw='코드 주소 시험')
        s.add(m)
        s.flush()
        mo = ensure_origin(s, m)
        s.commit()
        mo_id = mo.id
    finally:
        s.close()

    try:
        r = client.get(f'/optgen/product/by-code/{code}')
        assert r.status_code in (301, 302)
        assert r.headers['Location'].endswith(f'/optgen/product/{mo_id}')
    finally:
        s = SessionLocal()
        try:
            s.query(MatrixOption).filter(MatrixOption.model_code == code).delete()
            s.query(Model).filter(Model.model_code == code).delete()
            s.commit()
        finally:
            s.close()


def test_원본이_없어도_만들어서_같은_곳으로_보낸다(client):
    """🔴 이게 「항상 같아야 함」의 마지막 자물쇠 —
    원본이 없다는 이유로 딴 화면으로 새지 않는다. 없으면 만들어서 보낸다."""
    from datetime import datetime
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model

    code = '테스트_원본없음_' + datetime.now().strftime('%H%M%S%f')
    s = SessionLocal()
    try:
        s.add(Model(model_code=code, model_name_raw='원본 없음 시험'))
        s.commit()
    finally:
        s.close()

    try:
        r = client.get(f'/optgen/product/by-code/{code}')
        assert r.status_code in (301, 302), '원본이 없다고 딴 데로 보내면 안 된다'
        assert '/optgen/product/' in r.headers['Location']
        assert 'by-code' not in r.headers['Location'], '실제 id 로 풀어서 보내야 한다'
    finally:
        s = SessionLocal()
        try:
            s.query(MatrixOption).filter(MatrixOption.model_code == code).delete()
            s.query(Model).filter(Model.model_code == code).delete()
            s.commit()
        finally:
            s.close()


def test_없는_상품코드는_404(client):
    r = client.get('/optgen/product/by-code/__없는코드__')
    assert r.status_code == 404
