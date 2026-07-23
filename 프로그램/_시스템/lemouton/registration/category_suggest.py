# -*- coding: utf-8 -*-
"""맵핑 자동 제안 — 이름 유사도(순수함수) + 쿠팡 추천 앵커 오케스트레이션 (스펙 §C).

제안은 제안일 뿐이다: confidence 가 얼마든 자동 확정하지 않는다(정직성 원칙).
"""
from __future__ import annotations


def _tokens(path):
    out = set()
    for part in str(path or '').split('>'):
        part = part.strip()
        if part:
            out.add(part)
    return out


def rank_candidates(source_path, market_leaves, top=3):
    """source_path 의 리프명·경로 토큰으로 market_leaves 후보 상위 top 개.

    점수: 리프명 정확일치 1.0 / 리프명이 후보명에 포함(또는 역포함) 0.7
          / 경로 토큰 겹침 0.4×(겹친 토큰 비율). 0 은 제외.
    """
    parts = [p for p in str(source_path or '').split('>') if p.strip()]
    if not parts:
        return []
    leaf = parts[-1].strip()
    stoks = _tokens(source_path)
    ranked = []
    for cand in market_leaves:
        name = str(cand.get('name') or '').strip()
        score = 0.0
        if name == leaf:
            score = 1.0
        elif leaf and (leaf in name or name in leaf) and name:
            score = 0.7
        else:
            ctoks = _tokens(cand.get('full_path'))
            inter = stoks & ctoks
            if inter:
                score = 0.4 * (len(inter) / max(len(stoks), 1))
        if score > 0:
            ranked.append({'code': cand['code'], 'path': cand.get('full_path'),
                           'name': name, 'score': round(score, 3)})
    ranked.sort(key=lambda r: (-r['score'], r['path'] or ''))
    return ranked[:top]
