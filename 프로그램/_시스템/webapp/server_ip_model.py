"""우리 서버 IP 명부 — 팀 공유 영속화 모델.

목적: 마켓(11번가·롯데온 등)의 "출발지 IP 등록" 칸에 붙여넣을 **우리 서버 IP**를
      이름과 함께 관리한다. 팀 전체가 같은 목록을 본다(per-user 분리 ❌).

영속화 이유(icon_store_model 선례와 동일):
  · Fly.io/멀티 인스턴스 + deploy 시 파일시스템 reset → 로컬 파일은 휘발.
  · Supabase(또는 SQLite fallback) 테이블로 두면 머신·재배포 무관 영구 보존.

신규 테이블이라 create_all(init_db)이 자동 생성한다(기존 테이블 ALTER 아님).
"""
from sqlalchemy import Column, Integer, String, DateTime, func
from shared.db import Base


class ServerIp(Base):
    """우리 서버 IP 한 건 (이름 + 주소)."""
    __tablename__ = "server_ips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False, default="")   # 예: "업로드 서버"
    ip = Column(String(64), nullable=False)                 # 예: "54.116.196.90"
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name or "", "ip": self.ip}
