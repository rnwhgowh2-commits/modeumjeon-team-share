# AWS Lightsail 이전 — 사장님 체크리스트 (약 10분)

> 제(Claude)가 코드·자동배포·검증은 다 합니다. 아래 **계정·결제·키 붙여넣기**만 사장님이 해주세요.
> (보안상 제가 계정 생성·로그인·결제·키 입력을 대신 못 합니다.)

## STEP 1. AWS 가입 + Lightsail 인스턴스 생성
1. https://lightsail.aws.amazon.com 접속 → AWS 계정 생성(이메일·카드 등록).
2. **Create instance** 클릭:
   - 리전: **서울 (ap-northeast-2)**  ← 꼭 서울
   - 플랫폼: **Linux/Unix** → 블루프린트: **OS Only → Ubuntu 22.04 LTS**
   - 플랜: **$10/월 (2GB RAM, 2 vCPU, 60GB SSD)**  ← 2GB
   - 이름: `modeumjeon` → **Create instance**
3. 인스턴스 생성 후 **Networking 탭 → Create static IP** (고정 IP 할당·연결).
   - 이 **고정 IP**를 메모 (예: 13.124.x.x) — 마켓 허용목록·배포에 씀.
4. **Networking → IPv4 Firewall** 에 **HTTP(80)** 규칙 추가 (없으면).

## STEP 2. SSH 키 받기
- Lightsail → **Account → SSH keys** → 기본 키 **Download** (`.pem` 파일).
  (또는 인스턴스 생성 시 받은 키)

## STEP 3. GitHub Secret 2개 등록
GitHub 저장소 → **Settings → Secrets and variables → Actions → New repository secret**:
| 이름 | 값 |
|---|---|
| `LIGHTSAIL_HOST` | STEP 1의 **고정 IP** |
| `LIGHTSAIL_SSH_KEY` | STEP 2 `.pem` 파일 **내용 전체** 복붙 |

## STEP 4. 서버 1회 셋업 (Lightsail 콘솔의 브라우저 SSH 사용)
인스턴스 → **Connect using SSH** (브라우저 터미널) 에서:
```bash
curl -fsSL https://raw.githubusercontent.com/rnwhgowh2-commits/modeumjeon-team-share/main/deploy/lightsail-bootstrap.sh | bash
nano ~/app.env     # 실제 키 값 입력 후 Ctrl+O, Enter, Ctrl+X
```
- `app.env` 값들은 **현재 Fly에 들어있는 그 키들**과 동일합니다. (제가 어떤 값인지 함께 정리해 드립니다.)

## STEP 5. 저에게 알려주기
"IP·키 등록 끝" 이라고만 알려주시면 → 제가:
1. GHCR 패키지 공개 전환 안내 + 자동배포 워크플로 `push` 활성화,
2. 첫 배포 실행 + **헬스체크·매트릭스·마켓연동 전수 검증**,
3. 고정 IP를 마켓 허용목록에 등록하도록 그 IP를 정리해 드림(등록은 셀러센터라 사장님),
4. 문제없으면 Fly → Lightsail 완전 전환.

---
### 이후 = Fly와 동일
`git push` 하면 자동으로 빌드·배포됩니다. 사장님은 더 손댈 것 없음.
