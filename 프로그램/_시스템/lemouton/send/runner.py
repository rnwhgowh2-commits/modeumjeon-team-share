# -*- coding: utf-8 -*-
"""전송 작업 실행 — 백그라운드로 돌리고, 화면은 로그를 받아 본다.

설계서 §4-3 · 사장님 확정 「전송은 실시간으로 보여지게」(더망고 예시).

━━ 🔴 요청 안에서 돌리지 않는다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  이 저장소에 **요청 안에서 오래 걸리는 일을 돌려 사이트 전체가 502** 난 이력이 있다
  (gunicorn 180초 · Cloudflare 100초 상한). 그래서 실행은 백그라운드 스레드로
  떼어 놓고, 화면은 「새 줄만」 받아 간다(폴링).

━━ 🔴 마켓을 실제로 부르는 것은 두 겹 잠금 뒤 ━━━━━━━━━━━━━━━━━
  서버 열쇠(`MOUM_LIVE_UPLOAD`) + 화면 열쇠(자동화 `autosend_mode=='real'`).
  둘 다 안 켜져 있으면 **게이트까지만 돌고 마켓은 안 부른다** — 무엇이 막히는지
  먼저 보라는 뜻이다. 그 사실을 로그에 그대로 적는다(조용히 성공처럼 굴지 않는다).

━━ 마켓 간 병렬 금지 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  순차로 돈다. 이 저장소의 속도정책(계정별 버킷·ESM 5초/1회)을 등록에도 적용한다.
"""
from __future__ import annotations

import threading

from lemouton.send import service as SS
from lemouton.send.models import (
    KIND_NETWORK, KIND_NO_CATEGORY, KIND_NO_POLICY, KIND_OK,
    KIND_REQUIRED_MISSING, KIND_SKIPPED, KIND_STOCK_UNKNOWN, SendJob,
)

#: 지금 돌고 있는 작업 id — 두 번 눌러 두 벌이 도는 것을 막는다.
#: ⚠️ 프로세스별 메모리다 — 서버는 gunicorn 워커 2개라 **다른 워커에는 안 보인다.**
#:   그래서 「살았나 죽었나」는 이걸로 판정하지 않는다(하트비트로 한다, 아래).
_running: set[int] = set()
_lock = threading.Lock()

#: 하트비트 — 돌고 있는 스레드가 이 주기로 DB 에 시각을 찍는다.
_HEARTBEAT_SEC = 10
#: 이보다 오래 하트비트가 없으면 죽은 것으로 본다(찍는 주기의 4배 + 여유).
_STALE_SEC = 45


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _job_alive(job) -> bool:
    """DB 신호로 본 「살아있음」 — 어느 워커에서 폴링해도 같은 답이 나온다.

    🔴 라이브 사고(job 2): 폴링이 다른 워커에 떨어져 `_running` 에 없다는 이유로
      **살아있는 작업을 고아로 오판해 닫아버렸다.** 그동안 스레드는 사본 조립
      중이었다(큰 상품은 조립만 100초+ · 라이브 524 실측). 판정 근거를
      프로세스 메모리에서 DB 하트비트로 바꾼 이유다.
    """
    last = job.heartbeat_at or job.started_at
    if last is None:
        return False
    return (_now() - last).total_seconds() <= _STALE_SEC


def _heartbeat_loop(job_id: int, stop: threading.Event) -> None:
    """10초마다 살아있음을 찍는다 — 본체가 100초짜리 조립에 들어가 있어도.

    첫 박동은 본체(run_job)가 자기 세션으로 즉시 찍는다 — 여기서 바로 찍으면
    테스트(세션 공유)에서 두 스레드가 한 세션을 만져 깨진다.
    """
    from shared.db import SessionLocal
    while not stop.wait(_HEARTBEAT_SEC):
        try:
            hs = SessionLocal()
            try:
                hs.query(SendJob).filter(SendJob.id == job_id).update(
                    {'heartbeat_at': _now()})
                hs.commit()
            finally:
                hs.close()
        except Exception:                   # noqa: BLE001 — 박동 실패로 본체를 죽이지 않는다
            pass


def is_running(job_id: int) -> bool:
    with _lock:
        return job_id in _running


def any_running() -> bool:
    with _lock:
        return bool(_running)


def _kind_for(reasons: list[str]) -> str:
    """게이트가 막은 사유 → 실패 부류. 사장님이 무엇부터 손볼지 정하는 데 쓴다."""
    joined = ' '.join(reasons)
    if '정책이 붙어 있지 않' in joined or '저장된 항목이 하나도' in joined:
        return KIND_NO_POLICY
    if '재고' in joined:
        return KIND_STOCK_UNKNOWN
    if '카테고리' in joined:
        return KIND_NO_CATEGORY
    return KIND_REQUIRED_MISSING


def run_job(job_id: int, *, set_ids: list[int], markets: list[str]) -> None:
    """작업 하나를 끝까지 돈다. **자기 세션을 연다**(호출한 요청의 세션을 쓰지 않는다).

    🔴 한 건이 터져도 다음 건으로 넘어간다 — 한 구성의 실패가 나머지를 막으면
      1,000건 중 3번째에서 멈춰 있게 된다.
    """
    from shared.db import SessionLocal
    from lemouton.policy import to_payload as TP
    from lemouton.policy.service import enabled_markets
    from lemouton.uploader.runtime import real_upload_armed

    with _lock:
        _running.add(job_id)
    s = SessionLocal()
    stop_beat = threading.Event()
    try:
        job = s.get(SendJob, job_id)
        if job is None:
            return
        # 첫 박동 + 첫 단계는 **즉시** — 화면이 1초 안에 「살아있음」을 본다.
        job.heartbeat_at = _now()
        job.stage = f'전송 시작 — 구성 {len(set_ids)}개 × 마켓 {len(markets)}곳'
        s.commit()
        threading.Thread(target=_heartbeat_loop, args=(job_id, stop_beat),
                         daemon=True, name=f'send-beat-{job_id}').start()
        armed = False
        try:
            armed = real_upload_armed(s)
        except Exception:                   # noqa: BLE001 — 못 읽으면 안전하게 미전송
            armed = False

        for sid in set_ids:
            # 🔴 사본 조립은 마켓과 무관한데 안의 재고 읽기(매트릭스 조립)가 큰 상품에서
            #   수십 초다. 마켓 6곳마다 다시 만들면 첫 로그가 몇 분씩 늦는다(라이브 실측).
            #   구성당 한 번만 만들어 전 마켓에 재사용한다. 조립 자체가 실패하면
            #   그 사실을 한 줄 적고 다음 구성으로 넘어간다 — 조용히 죽지 않는다.
            try:
                # 조립이 오래 걸리는 동안 화면이 「죽었나」로 보이지 않게 단계를 적는다.
                job.stage = f'구성 {sid} 사본 조립 중 — 큰 상품은 몇 분 걸릴 수 있습니다'
                s.commit()
                base_view = TP.set_view(s, set_id=sid)
            except Exception as e:          # noqa: BLE001
                # 🔴 터진 세션으로 기록하면 기록도 터져 스레드가 통째로 죽는다 —
                #   라이브 실측(한 줄도 못 적고 고아가 됐다). 먼저 되돌린다.
                _safe_rollback(s)
                SS.record(s, job=job, market=markets[0] if markets else '',
                          kind=KIND_REQUIRED_MISSING, set_id=sid,
                          our_note=f'구성을 읽지 못했습니다: {type(e).__name__}: {e}')
                s.commit()
                continue
            passed = []                     # 게이트를 통과한 마켓 — 이것만 실제로 보낸다
            for mk in markets:
                try:
                    if _one(s, job=job, set_id=sid, market=mk, armed=armed,
                            enabled_markets=enabled_markets, TP=TP,
                            base_view=base_view):
                        passed.append(mk)
                except Exception as e:      # noqa: BLE001
                    # 🔴 조용히 넘어가지 않는다 — 왜 못 했는지 남긴다.
                    #   그리고 **먼저 되돌린다** — 터진 세션으로 적으면 기록도 터져
                    #   스레드가 죽고, 화면엔 「진행 중」인 채 아무것도 안 남는다
                    #   (라이브에서 실제로 그렇게 됐다 — job 1, 기록 0줄 고아).
                    _safe_rollback(s)
                    SS.record(s, job=job, market=mk, kind=KIND_REQUIRED_MISSING,
                              set_id=sid,
                              our_note=f'전송 준비 중 오류: {type(e).__name__}: {e}')
                s.commit()                  # 건마다 커밋 — 중간에 죽어도 앞은 남는다
            if passed and armed:
                # 🔴 마켓 상품번호가 있으면 **갱신**, 없으면 **신규 등록** — 길이 다르다.
                #   갱신은 가격·재고만 보내고, 신규는 상품을 통째로 만든다.
                job.stage = f'구성 {sid} 마켓 전송 중 — {", ".join(passed)}'
                s.commit()
                listed, fresh = _split_by_listed(s, set_id=sid, markets=passed)
                if listed:
                    _send(s, job=job, set_id=sid, markets=listed)
                for mk in fresh:
                    _register(s, job=job, set_id=sid, market=mk,
                              base_view=base_view)
                s.commit()
        job.stage = None                    # 끝났다 — 단계 줄을 지운다
        SS.finish_job(s, job=job)
        s.commit()
    except Exception:                       # noqa: BLE001 — 마지막 방어선
        # 여기까지 왔다는 건 기록조차 못 하는 상태다. 작업만이라도 닫아
        # 화면이 「영원히 진행 중」으로 남지 않게 한다.
        _safe_rollback(s)
        try:
            job = s.get(SendJob, job_id)
            if job is not None and job.status == 'running':
                job.status = 'stopped'
                s.commit()
        except Exception:                   # noqa: BLE001
            pass
    finally:
        stop_beat.set()                     # 박동을 멈춘다 — 죽은 뒤에도 찍으면 고아 판정이 안 된다
        s.close()
        with _lock:
            _running.discard(job_id)


def _safe_rollback(s) -> None:
    try:
        s.rollback()
    except Exception:                       # noqa: BLE001
        pass


def _one(s, *, job, set_id, market, armed, enabled_markets, TP,
         base_view=None) -> bool:
    """구성 하나 × 마켓 하나 — **게이트만** 본다. 통과하면 True.

    실제 마켓 호출은 :func:`_send` 가 구성 단위로 한 번에 한다(마켓마다 따로 부르면
    같은 상품을 여러 번 조회·전송하게 된다).
    """
    built = TP.build_for_set(s, set_id=set_id, market=market, base_view=base_view)
    policy = built['policy']
    model_code = getattr(built['view'], 'model_code', '')

    # ① 정책에서 그 마켓을 꺼 뒀나 — 더망고의 「전송제외상품」과 같은 자리.
    if policy is not None and market not in enabled_markets(s, policy):
        SS.record(s, job=job, market=market, kind=KIND_SKIPPED, set_id=set_id,
                  model_code=model_code,
                  our_note=f'전송 제외 — 정책 「{policy.name}」 에서 이 마켓이 꺼져 '
                           f'있습니다. 켜면 나갑니다.')
        return False

    # ② 게이트 — 정책 없음·필수 빔·재고 확인 불가…
    if built['blocking']:
        SS.record(s, job=job, market=market, kind=_kind_for(built['blocking']),
                  set_id=set_id, model_code=model_code,
                  our_note=' / '.join(built['blocking'][:3]))
        return False

    # ③ 여기서부터가 실제 전송 — 두 겹 잠금 뒤에서만.
    if not armed:
        SS.record(s, job=job, market=market, kind=KIND_SKIPPED, set_id=set_id,
                  model_code=model_code,
                  our_note='보낼 준비는 끝났지만 **실전송이 꺼져 있어** 부르지 '
                           '않았습니다 — 자동화 화면에서 켜면 나갑니다.')
        return False
    return True


def _split_by_listed(s, *, set_id: int, markets: list[str]):
    """이미 등록된 마켓 / 아직 안 올린 마켓 으로 가른다."""
    from lemouton.sets.models import SetChannel
    have = {c.market for c in s.query(SetChannel)
            .filter(SetChannel.set_id == set_id).all() if c.market_product_id}
    return ([m for m in markets if m in have], [m for m in markets if m not in have])


def _register(s, *, job, set_id, market, base_view=None) -> None:
    """마켓에 **처음** 올린다.

    🔴 등록 경로를 새로 만들지 않는다 — `registration/service.register_draft()` 가
      컴파일·이미지 CDN 재호스팅·게이트·장부(중복 등록 방지)·등록 후 판매중지까지
      다 들고 있다. 무엇이 모자란지도 `preflight_rows()` 가 **단일 판정기**로 답한다.
      구성을 초안 한 줄로 비춰 주기만 하면 그대로 돈다(`send/as_draft.py`).

    ⚠️ 구성에는 아직 이미지·고시·A/S 칸이 없다. 그래서 대부분 preflight 에서 걸린다 —
      그게 맞는 답이다. 지어내 채우면 가짜 값이 마켓에 게시된다.
    """
    from lemouton.policy import to_payload as TP
    from lemouton.send import as_draft as AD
    from lemouton.send.models import KIND_MARKET_REJECTED

    try:
        built = TP.build_for_set(s, set_id=set_id, market=market,
                                 base_view=base_view)
        try:
            draft = AD.upsert(s, set_id=set_id, market=market, view=built['view'])
        except AD.DraftIncomplete as e:
            # 값을 지어내지 않고 멈춘 것 — 사유를 그대로 보여준다.
            SS.record(s, job=job, market=market, kind=KIND_REQUIRED_MISSING,
                      set_id=set_id, action='create', our_note=str(e))
            return
        s.flush()
        missing = AD.missing_fields(draft)

        from webapp.routes.bulk.drafts import preflight_rows
        rows = preflight_rows(s, draft, [market])
        row = rows[0] if rows else {}
    except Exception as e:                  # noqa: BLE001
        _safe_rollback(s)
        SS.record(s, job=job, market=market, kind=KIND_REQUIRED_MISSING, set_id=set_id,
                  action='create',
                  our_note=f'신규 등록 준비 중 오류: {type(e).__name__}: {e}')
        return

    if row.get('status') != 'ready':
        why = row.get('reason') or '아직 올릴 수 없습니다.'
        if missing:
            why += f' · 구성에 아직 없는 칸: {", ".join(missing)}'
        SS.record(s, job=job, market=market,
                  kind=(KIND_NO_CATEGORY if row.get('status') == 'need_category'
                        else KIND_REQUIRED_MISSING),
                  set_id=set_id, model_code=draft.model_code, action='create',
                  our_note=why)
        return

    from lemouton.registration.service import register_draft
    try:
        got = register_draft(s, draft.id, market,
                             category_code=row.get('category_code'),
                             account_key=row.get('account_key') or 'default')
    except Exception as e:                  # noqa: BLE001
        SS.record(s, job=job, market=market, kind=KIND_NETWORK, set_id=set_id,
                  model_code=draft.model_code, action='create',
                  our_note=f'등록을 부르다 실패했습니다: {type(e).__name__}: {e}')
        return

    if got.get('ok'):
        mpid = str(got.get('market_product_id') or '')
        _link_channel(s, set_id=set_id, market=market,
                      account_key=row.get('account_key') or 'default',
                      market_product_id=mpid)
        note = ''
        if got.get('excluded'):
            note = (f'옵션 {len(got["excluded"])}개는 재고 0·확인 불가라 빠졌습니다 — '
                    f'지어내지 않고 뺐습니다.')
        SS.record(s, job=job, market=market, kind=KIND_OK, set_id=set_id,
                  model_code=draft.model_code, action='create',
                  market_product_id=mpid, our_note=note)
        return

    code, msg, from_market = SS.split_market_error(got.get('error'))
    SS.record(s, job=job, market=market,
              kind=KIND_MARKET_REJECTED if from_market else KIND_NETWORK,
              set_id=set_id, model_code=draft.model_code, action='create',
              market_code=code, market_message=msg,
              our_note=('' if from_market else str(got.get('error') or '')))


def _link_channel(s, *, set_id, market, account_key, market_product_id) -> None:
    """등록으로 생긴 마켓 상품번호를 구성에 붙인다 — 다음부터는 **갱신** 경로로 간다.

    🔴 이걸 안 하면 같은 상품을 또 등록해 마켓에 **중복 상품**이 생긴다.
    """
    if not market_product_id:
        return
    from lemouton.sets.channel_service import add_channel, set_channel_product
    ch = add_channel(s, set_id=set_id, market=market, account_key=account_key)
    set_channel_product(s, channel_id=ch.id, market_product_id=market_product_id)


def _skus_of(s, set_id: int) -> list[str]:
    from lemouton.sets.models import SetOption, SetProduct
    return [r[0] for r in
            s.query(SetOption.canonical_sku)
            .join(SetProduct, SetProduct.id == SetOption.set_product_id)
            .filter(SetProduct.set_id == set_id).all()]


def _send(s, *, job, set_id, markets: list[str]) -> None:
    """게이트를 통과한 구성을 **실제로** 보낸다.

    🔴 전송 경로를 새로 만들지 않는다 — `uploader/scoped_send.run()` 이 이미
      두 겹 잠금·어댑터 선택·계정별 속도조절·실패함(DLQ)·변동감지 기준선까지
      다 들고 있는 **검증된 경로**다. 여기서 다시 짜면 그 규율이 전부 빠진다.
      (재고 판정을 `_option_matrix_data` 로 되쓴 것과 같은 판단이다)

    결과는 마켓별로 한 줄씩 적는다 — 마켓이 준 사유는 원문 그대로.
    """
    from lemouton.send.models import KIND_MARKET_REJECTED, KIND_OK
    from lemouton.uploader import scoped_send

    skus = _skus_of(s, set_id)
    if not skus:
        for mk in markets:
            SS.record(s, job=job, market=mk, kind=KIND_SKIPPED, set_id=set_id,
                      our_note='이 구성에 담긴 옵션이 없습니다 — 보낼 것이 없습니다.')
        return

    try:
        # set_id 를 넘긴다 — 마켓 상품번호를 **구성(SetChannel)** 에서 읽게 하는 열쇠.
        #   안 넘기면 옛 경로(Model.*_product_id)로 조립돼 후보 0건이 된다(2026-08-06 실측).
        got = scoped_send.run(skus, want_live=True, confirmed=True,
                              markets=markets, set_id=set_id)
    except Exception as e:                  # noqa: BLE001
        for mk in markets:
            SS.record(s, job=job, market=mk, kind=KIND_NETWORK, set_id=set_id,
                      our_note=f'전송을 부르다 실패했습니다: {type(e).__name__}: {e}')
        return

    # 서버키가 꺼져 있으면 드라이런으로 돈다 — 「보냈다」고 적지 않는다.
    if not got.get('use_real'):
        why = got.get('refusal') or '실전송이 꺼져 있어 드라이런으로 돌았습니다.'
        for mk in markets:
            SS.record(s, job=job, market=mk, kind=KIND_SKIPPED, set_id=set_id,
                      our_note=why)
        return

    res = got.get('result') or {}
    if res.get('held'):
        for mk in markets:
            SS.record(s, job=job, market=mk, kind=KIND_SKIPPED, set_id=set_id,
                      our_note=f'자동 보류 — {res.get("hold_reason") or "확인 필요"}')
        return

    # 실패는 마켓별로 원문 그대로. 어댑터가 준 `error` 를 코드/메시지로 가른다.
    errs: dict[str, list] = {}
    for e in (res.get('errors') or []):
        errs.setdefault(e.get('market') or '', []).append(e)
    for mk in markets:
        bad = errs.get(mk) or []
        if not bad:
            SS.record(s, job=job, market=mk, kind=KIND_OK, set_id=set_id)
            continue
        for e in bad[:5]:                   # 한 마켓에 여러 옵션이 실패할 수 있다
            code, msg, from_market = SS.split_market_error(e.get('error'))
            SS.record(s, job=job, market=mk,
                      kind=KIND_MARKET_REJECTED if from_market else KIND_NETWORK,
                      set_id=set_id, market_code=code, market_message=msg,
                      our_note=('' if from_market else str(e.get('error') or '')))


def start(session, *, set_ids: list[int], markets: list[str], mode: str = 'send',
          filters: dict | None = None, started_by: str = '') -> int:
    """작업을 열고 백그라운드로 띄운다. `job_id` 를 돌려준다.

    🔴 이미 도는 작업이 있으면 막는다 — 같은 상품을 두 벌이 동시에 보내면
      마켓이 같은 값을 두 번 받거나 서로 덮어쓴다.
    """
    if any_running():
        raise SS.SendError('이미 전송이 돌고 있습니다 — 끝난 뒤에 다시 눌러 주세요.')
    # 🔴 다른 워커에서 돌고 있을 수도 있다(메모리로는 안 보인다) — DB 하트비트로 본다.
    for j in session.query(SendJob).filter(SendJob.status == 'running').all():
        if _job_alive(j):
            raise SS.SendError(f'이미 전송이 돌고 있습니다(작업 {j.id}) — '
                               f'끝난 뒤에 다시 눌러 주세요.')
    if not set_ids:
        raise SS.SendError('보낼 구성이 하나도 없습니다.')
    if not markets:
        raise SS.SendError('보낼 마켓을 하나도 고르지 않았습니다.')
    job = SS.start_job(session, mode=mode, filters=filters, started_by=started_by)
    session.commit()
    jid = job.id
    t = threading.Thread(target=run_job, args=(jid,),
                         kwargs={'set_ids': list(set_ids), 'markets': list(markets)},
                         daemon=True, name=f'send-job-{jid}')
    t.start()
    return jid


# ── 화면이 받아 갈 로그 ─────────────────────────────────────────────────

#: 부류 → 로그 줄 색. 화면이 이 값으로 초록·회색·주황·빨강을 고른다.
TONE = {'OK': 'ok', 'SKIPPED': 'skip'}


def log_since(session, job_id: int, after_id: int = 0, limit: int = 300) -> dict:
    """`after_id` 뒤에 생긴 줄들 + 지금 진행 상황.

    화면은 마지막으로 받은 줄 id 를 들고 있다가 그 뒤만 받아 간다 —
    통째로 다시 받으면 목록이 깜빡이고 스크롤이 튄다.
    """
    from lemouton.send.models import FAILURE_KINDS, KIND_LABEL, SendJobRow

    job = session.get(SendJob, job_id)
    if job is None:
        raise SS.SendError('그런 전송 작업이 없습니다.')
    # 🔴 고아 작업 — 서버가 재시작(배포·워커 교체)되면 돌던 스레드는 죽는데 DB 상태는
    #   'running' 으로 남는다. 그대로 두면 화면이 **영원히 폴링**한다.
    # 🔴🔴 단 「이 프로세스에 스레드가 없다」는 근거가 못 된다 — 워커가 2개라
    #   폴링이 다른 워커에 떨어지면 늘 없다. 그 근거로 닫았다가 **살아있는 작업을
    #   죽였다**(라이브 사고 job 2 — 스레드는 100초짜리 조립 중이었다).
    #   판정은 DB 하트비트 신선도로만 한다.
    alive = is_running(job_id)
    if job.status == 'running' and not alive:
        if _job_alive(job):
            alive = True                    # 다른 워커에서 살아 돌고 있다
        else:
            job.status = 'stopped'
            session.commit()
    rows = (session.query(SendJobRow)
            .filter(SendJobRow.job_id == job_id, SendJobRow.id > int(after_id or 0))
            .order_by(SendJobRow.id).limit(limit).all())
    out = []
    for r in rows:
        out.append({
            'id': r.id, 'at': r.created_at.strftime('%Y%m%d %H:%M:%S') if r.created_at else '',
            'market': r.market, 'account': r.account_key or '',
            'set_id': r.set_id, 'model_code': r.model_code or '',
            'kind': r.kind, 'label': KIND_LABEL.get(r.kind, (r.kind, ''))[0],
            'tone': ('ok' if r.kind == KIND_OK else
                     'skip' if r.kind == 'SKIPPED' else 'fail'),
            # 🔴 마켓이 한 말과 우리 말을 화면에도 **따로** 준다.
            'market_code': r.market_code or '', 'market_message': r.market_message or '',
            'our_note': r.our_note or '',
            'how_to_fix': KIND_LABEL.get(r.kind, ('', ''))[1],
            'failed': r.kind in FAILURE_KINDS,
        })
    # 🔴 성공 건수를 `ok` 라고 부르지 않는다 — 응답 봉투의 `ok`(성공 여부)를 덮어
    #   0건일 때 화면이 「실패」로 읽는다. 실측으로 걸린 버그다(200 OK 인데 화면은 실패).
    return {'job_id': job.id, 'status': job.status, 'running': alive,
            'stage': (job.stage or '') if job.status == 'running' else '',
            'total': job.total or 0, 'sent': job.ok_count or 0,
            'fail': job.fail_count or 0,
            'last_id': out[-1]['id'] if out else int(after_id or 0),
            'lines': out}
