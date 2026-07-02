"""[E] T11 — APScheduler job 정의.

`full_cycle()` = [A] crawl → [B] price decide → [C] format → [D] upload.
지금은 high-level orchestration의 골격만 — 실 사이트 크롤링·박스히어로 동기화·
Coupang 어댑터 wiring은 이미 [A]~[D]에서 완료되어 있고, 여기선 그것들을 묶어 호출한다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def full_cycle(*, dry_run: bool = False) -> dict:
    """1회 풀 사이클. 각 단계 실패는 다음 단계 차단하지 않고 결과에 기록.

    BundleRun(model_code=NULL, phase='full', triggered_by='scheduler') 1행으로 기록.
    """
    started = datetime.now(timezone.utc)
    run_id: int | None = None
    try:
        from lemouton.sourcing.run_history import record_start
        run_id = record_start(model_code=None, phase='full',
                              triggered_by='scheduler')
    except Exception:
        logger.exception('run_history.record_start failed')

    result: dict = {
        'started_at': started.isoformat(),
        'dry_run': dry_run,
        'phases': {},
    }
    # Phase A: sourcing — fetch_unique_sources 로 source_products/options 갱신
    # + run_pipeline 으로 옵션-소스 매핑 aggregate (선택)
    a_output: dict = {}
    fetch_summary: dict = {}
    # v27 — scheduler 자동 cycle 도 widget 으로 표시
    try:
        from webapp.progress_state import progress_set, progress_finish, progress_tick
        # [2026-06-03] 'auto' 슬롯 — 수동 per-bundle 크롤('crawl')과 분리(위젯 깜빡임 방지)
        progress_set('auto', total=1, label='자동 cycle (scheduler)', current='Phase A 시작...')
    except Exception:
        pass
    try:
        from shared.db import SessionLocal
        from lemouton.sources.service import fetch_unique_sources
        from lemouton.sourcing.pipeline import run_pipeline
        from lemouton.sourcing.crawlers import build_crawlers
        crawlers = build_crawlers()
        s = SessionLocal()
        try:
            # Step 1: 모든 SourceProduct 실제 크롤 + DB 갱신 (멱등)
            # [2026-06-03] 자동 크롤도 소싱처별 진행을 위젯에 표시 (수동 크롤과 동일한 뷰 유지)
            _AUTO_SRC_LABELS = {'lemouton': '르무통 공홈', 'ss_lemouton': '스마트스토어',
                                'musinsa': '무신사', 'ssf': 'SSF', 'lotteon': '롯데온', 'ssg': 'SSG'}
            def _auto_progress(done, total, site, src_totals, src_done):
                breakdown = []
                for k, t in src_totals.items():
                    d = src_done.get(k, 0)
                    status = 'done' if d >= t else ('wait' if d == 0 else 'run')
                    breakdown.append({'key': k, 'label': _AUTO_SRC_LABELS.get(k, str(k)),
                                      'total': t, 'done': d, 'status': status})
                cur = (f"{_AUTO_SRC_LABELS.get(site, site)} 크롤 중 ({done}/{total})"
                       if site else f"{total}개 상품 크롤 준비...")
                try: progress_tick('auto', done=done, total=total, current=cur, breakdown=breakdown)
                except Exception: pass
            fetch_results = fetch_unique_sources(s, crawlers=crawlers, progress_cb=_auto_progress)
            ok = sum(1 for r in fetch_results.values() if r['status'] == 'ok')
            err = sum(1 for r in fetch_results.values() if r['status'] == 'error')
            none = sum(1 for r in fetch_results.values() if r['status'] == 'no_crawler')
            try: progress_tick('auto', done=1, total=1, current=f'Phase A 완료 ({ok}/{len(fetch_results)} ok)')
            except Exception: pass
            fetch_summary = {'sources_total': len(fetch_results),
                             'ok': ok, 'error': err, 'no_crawler': none}
            s.commit()

            # Step 2: matcher + aggregate (a_output) — 매핑 실패는 무시
            try:
                a_output = run_pipeline(s, crawlers=crawlers,
                                        boxhero_records=[], progress_kind='auto') or {}
            except Exception as agg_e:
                logger.warning('phase A aggregate skipped: %s', agg_e)
                a_output = {}

            result['phases']['A_sourcing'] = {
                'ok': True,
                'detail': (f"fetched {ok}/{len(fetch_results)} sources "
                           f"(err={err}, no_crawler={none}); "
                           f"aggregated {len(a_output)} options"),
            }
        finally:
            s.close()
    except Exception as e:
        logger.exception('phase A failed')
        result['phases']['A_sourcing'] = {'ok': False, 'error': str(e)}

    # Phase B: pricing — Phase A output + 기본 settings.
    # Phase A 가 빈 결과 (0 options) 면 graceful skip — pricing 엔진 호출 자체 안 함.
    b_output: dict = {'decisions': {}, 'alerts': []}
    if not a_output:
        result['phases']['B_pricing'] = {'ok': True, 'detail': 'skipped — Phase A 0 options'}
    else:
        try:
            from lemouton.pricing.engine import run_pricing_engine
            # Phase A 출력은 {canonical_sku: aggregated_dict} 형식.
            # decide_ss/cp 는 각 옵션 dict 안에 canonical_sku 키를 기대 → enrich.
            a_enriched = {sku: {**(opt or {}), 'canonical_sku': sku}
                          for sku, opt in a_output.items()}
            settings = {
                'ss_fee_rate': 0.06,
                'coupang_fee_rate': 0.1155,
                'delivery_fee': 3000,
                'rounding_unit': 100,
            }
            b_output = run_pricing_engine(a_enriched, settings) or b_output
            result['phases']['B_pricing'] = {
                'ok': True,
                'detail': f"decisions {len(b_output.get('decisions', {}))} / alerts {len(b_output.get('alerts', []))}"
            }
        except Exception as e:
            logger.exception('phase B failed')
            result['phases']['B_pricing'] = {'ok': False, 'error': str(e)}

    # Phase C: formatter — Phase A + B 출력 → 마켓별 페이로드
    c_output: dict = {}
    try:
        from shared.db import SessionLocal as _SL
        from lemouton.formatter.pipeline import run_formatter
        s = _SL()
        try:
            c_output = run_formatter(s, a_output, b_output) or {}
            result['phases']['C_formatter'] = {
                'ok': True,
                'detail': f"smartstore {len(c_output.get('smartstore', {}))} / coupang {len(c_output.get('coupang', {}))}"
            }
        finally:
            s.close()
    except Exception as e:
        logger.exception('phase C failed')
        result['phases']['C_formatter'] = {'ok': False, 'error': str(e)}

    # Phase D: uploader — Phase C 페이로드 + 어댑터 (없으면 dry-run skip)
    try:
        if not c_output or not (c_output.get('smartstore') or c_output.get('coupang')):
            # 변동 없음 → uploader 호출할 데이터 없음
            result['phases']['D_uploader'] = {'ok': True, 'detail': 'skipped — no payload'}
        else:
            from shared.db import SessionLocal as _SL2
            from lemouton.uploader.orchestrator import run_uploader
            from lemouton.uploader.runtime import (
                select_adapters, build_sku_by_option, live_upload_enabled,
            )
            s = _SL2()
            try:
                # 실전송 게이트 — LEMOUTON_LIVE_UPLOAD 가 참일 때만 실제 어댑터.
                # 기본 OFF → DryRunAdapter (외부 호출 없음).
                ss_ad, cp_ad = select_adapters()
                # (market, 마켓옵션ID) → canonical_sku (matched 채널옵션만)
                sku_by_option = build_sku_by_option(s)
                import os
                dlq_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'uploader_dlq.jsonl')
                r = run_uploader(s, c_output,
                                 sku_by_option=sku_by_option,
                                 ss_adapter=ss_ad, cp_adapter=cp_ad,
                                 dlq_path=dlq_path,
                                 force=False)
                _mode = 'live' if live_upload_enabled() else 'dryrun'
                result['phases']['D_uploader'] = {
                    'ok': True,
                    'detail': (f"mode={_mode} · uploaded {r.get('uploaded', 0)} / "
                               f"skipped {r.get('skipped', 0)} / failed {r.get('failed', 0)}"
                               + (f" / HELD({r.get('hold_reason')})" if r.get('held') else "")),
                }
            finally:
                s.close()
    except Exception as e:
        logger.exception('phase D failed')
        result['phases']['D_uploader'] = {'ok': False, 'error': str(e)}

    result['ended_at'] = datetime.now(timezone.utc).isoformat()
    result['duration_sec'] = (datetime.now(timezone.utc) - started).total_seconds()

    # BundleRun 종료 기록
    if run_id is not None:
        try:
            from lemouton.sourcing.run_history import (
                record_end, summarize_status, SOURCE_KEYS, MARKET_KEYS,
            )
            phases = result.get('phases', {})
            details: dict = {'duration_sec': result['duration_sec']}
            a = phases.get('A_sourcing') or {}
            details['sources'] = {
                k: {'ok': bool(a.get('ok'))}
                if a.get('ok')
                else {'ok': False, 'error': a.get('error', '')[:200]}
                for k in SOURCE_KEYS
            }
            d = phases.get('D_uploader') or {}
            details['markets'] = {
                k: {'ok': bool(d.get('ok'))}
                if d.get('ok')
                else {'ok': False, 'error': d.get('error', '')[:200]}
                for k in MARKET_KEYS
            }
            status = summarize_status(details)
            err_lines = [v.get('error') for v in phases.values()
                         if isinstance(v, dict) and not v.get('ok')]
            err_str = ' | '.join(filter(None, err_lines)) or None
            record_end(run_id, status=status, details=details, error=err_str)
        except Exception:
            logger.exception('run_history.record_end failed')

    # v27 — scheduler cycle 진행 widget 종료
    try:
        from webapp.progress_state import progress_finish
        progress_finish('auto')
    except Exception:
        pass

    return result


def boxhero_partial_cycle(changed_skus: Optional[list[str]] = None) -> dict:
    """T12 webhook 수신 시 부분 사이클. 변동 SKU만 재계산·재업로드."""
    started = datetime.now(timezone.utc)
    result = {'started_at': started.isoformat(), 'changed_skus': changed_skus or []}
    try:
        from lemouton.uploader.orchestrator import run_uploader
        # orchestrator가 changed_skus 키워드를 안 받으면 전체 재시도
        try:
            r = run_uploader(canonical_skus=changed_skus, dry_run=False)
        except TypeError:
            r = run_uploader(dry_run=False)
        result['ok'] = True
        result['detail'] = str(r)[:200]
    except Exception as e:
        logger.exception('boxhero partial cycle failed')
        result['ok'] = False
        result['error'] = str(e)
    result['ended_at'] = datetime.now(timezone.utc).isoformat()
    return result
