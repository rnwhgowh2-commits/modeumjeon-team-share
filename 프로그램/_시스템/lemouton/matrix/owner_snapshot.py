# -*- coding: utf-8 -*-
"""옵션 주인 이관 — 기준 지문(fingerprint) 계산.

설계서: docs/superpowers/specs/2026-08-01-옵션생성-상품생성-탭-design.md §9

2단계는 옵션 5,018개의 주인을 **상품(Model) → 매트릭스 옵션**으로 옮긴다.
크롤·마켓전송·주문매칭·재고가 전부 지금 칸을 보고 돌기 때문에, 한 곳이라도
빠지면 **경고 없이 가격·재고가 틀린다.** 그래서 옮기기 전후로 같은 지문을
떠서 대조하고, 하나라도 다르면 되돌린다.

🔴 지문에 **가격·재고를 넣지 않는다.**
   크롤이 몇 분마다 그 값을 바꾼다. 넣으면 이관과 무관하게 지문이 달라져
   「틀렸다」는 거짓 경보가 난다. 가격은 소싱처 연결이 같으면 같은 입력으로
   계산되므로, 연결만 지키면 값도 지켜진다.

🔴 소싱처 주소는 **두 곳에 나뉘어 있다.**
   · 신 : bundle_source_urls(모델 소유) + option_source_url_links(옵션↔URL N:N)
   · 구 : option_source_urls(옵션 × 소싱처 → URL)
   한쪽만 보면 없어진 걸 못 잡는다. 둘 다 지문에 넣는다.
   (이 분열 자체를 이관에서 하나로 합친다 — 설계서 규칙 11)
"""
from __future__ import annotations

import hashlib


def _line(parts) -> str:
    """한 줄을 만든다. 값 안에 구분자가 있어도 섞이지 않게 이스케이프."""
    return '\x1f'.join(str('' if p is None else p).replace('\x1f', '\\x1f')
                       for p in parts)


def model_digest(options, links, legacy) -> str:
    """묶음 하나의 지문. 순서와 무관하다(DB 반환 순서는 보장되지 않는다).

    Args:
        options: [(canonical_sku, color_code, size_code, is_active), ...]
        links:   [(canonical_sku, source_key, url, url_type), ...]   신 저장소
        legacy:  [(canonical_sku, source_id, product_url), ...]      구 저장소

    Returns:
        sha256 앞 16자. 사람이 눈으로 대조할 수 있는 길이.
    """
    body = []
    body.append('OPT')
    body.extend(sorted(_line(o) for o in options))
    body.append('LINK')
    body.extend(sorted(_line(l) for l in links))
    body.append('LEGACY')
    body.extend(sorted(_line(g) for g in legacy))
    blob = '\n'.join(body).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()[:16]


# ── DB 에서 읽어 지문을 만든다 (읽기 전용) ────────────────────────────────

def _fetch(session):
    """옵션·신 저장소·구 저장소를 각각 한 번씩만 읽는다(N+1 회피)."""
    from lemouton.sourcing.models import (BundleSourceUrl, Option,
                                          OptionSourceUrlLink)
    from lemouton.sourcing.models_pricing import OptionSourceUrl

    opts = session.query(
        Option.canonical_sku, Option.model_code,
        Option.color_code, Option.size_code, Option.is_active).all()

    links = (session.query(
        OptionSourceUrlLink.option_canonical_sku,
        BundleSourceUrl.source_key, BundleSourceUrl.url, BundleSourceUrl.url_type)
        .join(BundleSourceUrl,
              BundleSourceUrl.id == OptionSourceUrlLink.bundle_source_url_id)
        .all())

    legacy = session.query(
        OptionSourceUrl.canonical_sku, OptionSourceUrl.source_id,
        OptionSourceUrl.product_url).all()

    return opts, links, legacy


def collect(session) -> dict:
    """전체 기준 지문. 이관 전후로 두 번 떠서 대조한다.

    Returns:
        {'counts': {...}, 'overall': sha, 'by_model': {model_code: sha},
         'orphans': {...}}   orphans = 어느 묶음에도 못 붙은 것(있으면 안 된다)
    """
    opts, links, legacy = _fetch(session)

    model_of = {o[0]: o[1] for o in opts}
    by_model: dict[str, dict] = {}
    for sku, code, color, size, active in opts:
        by_model.setdefault(code, {'options': [], 'links': [], 'legacy': []})
        by_model[code]['options'].append((sku, color, size, bool(active)))

    orphan_links = 0
    for sku, key, url, utype in links:
        code = model_of.get(sku)
        if code is None:
            orphan_links += 1                 # 옵션 없는 매핑 — 이관과 무관하게 이미 이상
            continue
        by_model[code]['links'].append((sku, key, url, utype))

    orphan_legacy = 0
    for sku, src_id, url in legacy:
        code = model_of.get(sku)
        if code is None:
            orphan_legacy += 1
            continue
        by_model[code]['legacy'].append((sku, src_id, url))

    digests = {code: model_digest(**rows) for code, rows in by_model.items()}
    overall = hashlib.sha256(
        '\n'.join(f'{c}\x1f{d}' for c, d in sorted(digests.items()))
        .encode('utf-8')).hexdigest()[:16]

    return {
        'counts': {
            'models': len(by_model),
            'options': len(opts),
            'links_new': len(links) - orphan_links,
            'links_legacy': len(legacy) - orphan_legacy,
        },
        'overall': overall,
        'by_model': digests,
        'orphans': {'links_new': orphan_links, 'links_legacy': orphan_legacy},
    }


def model_rows(session, model_code: str) -> dict:
    """지문이 달라진 묶음 하나를 한 줄씩 펴서 본다 — 어디가 달라졌는지 찾을 때."""
    opts, links, legacy = _fetch(session)
    skus = {o[0] for o in opts if o[1] == model_code}
    return {
        'model_code': model_code,
        'options': sorted((s, c, z, bool(a)) for s, m, c, z, a in opts if m == model_code),
        'links': sorted(l for l in links if l[0] in skus),
        'legacy': sorted(g for g in legacy if g[0] in skus),
    }


def diff(before: dict, after: dict) -> dict:
    """두 지문을 대조한다. 같으면 changed 가 빈 목록이다."""
    b, a = before.get('by_model', {}), after.get('by_model', {})
    return {
        'same': before.get('overall') == after.get('overall'),
        'counts_before': before.get('counts'),
        'counts_after': after.get('counts'),
        'gone': sorted(set(b) - set(a)),          # 묶음이 사라짐
        'new': sorted(set(a) - set(b)),           # 묶음이 생김
        'changed': sorted(k for k in (set(b) & set(a)) if b[k] != a[k]),
    }
