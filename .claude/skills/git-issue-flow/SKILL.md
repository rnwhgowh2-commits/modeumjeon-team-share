---
name: git-issue-flow
description: 이 저장소에서 코드를 변경하는 모든 작업의 Git/GitHub 표준 절차 (정본). 새 기능·버그수정·이슈 작업을 시작할 때, 또는 add-source·update-data-code-map 등 다른 스킬이 "브랜치 생성"이나 "PR·머지" 단계에 도달했을 때 이 스킬 절차를 따른다. 트리거 — "이슈 작업 시작해줘", "OO 브랜치 만들어줘", "작업 끝났으니 PR 올려줘", 또는 코드 변경이 필요한 모든 작업 착수 시점.
---

# 이슈 단위 Git 작업 흐름 (git-issue-flow)

이 저장소의 모든 코드 변경은 **main 최신화 → 이슈 확인 → 브랜치 생성 → 작업 → push → PR → 사용자 확인 → 머지 → 정리** 순서를 따른다.

## 🚨 절대 원칙

1. **main에 직접 push 금지.** 항상 origin/main 기준 새 브랜치에서 작업 후 PR을 거친다. (사용자가 "이번엔 바로 main에 push해"처럼 명시적으로 예외를 지시한 경우에만 예외 — 긴급 핫픽스 등)
2. **merge는 항상 사용자 확인 후 진행.** PR 생성까지는 자동으로 진행하되, 실제 merge는 사용자 승인 없이 실행하지 않는다.
3. **각 단계마다 1~2줄로 간단히 보고한다** — 무엇을 했고 왜 했는지 (브랜치 생성/push/PR 생성/머지 시점마다).
4. **브랜치 작업은 항상 별도 워크트리에서.** 이 PC에는 Claude Code 세션이 여러 개 동시에 떠 있을 수 있다(2026-08-19 실측 22개). 본체 워크트리(메인 체크아웃)에서 `git checkout -b`로 브랜치를 만들면, 동시에 열린 다른 세션이 같은 폴더에서 브랜치를 바꿔치기해 작업이 꼬일 수 있다(실제 발생 사례: 작업 중 체크아웃 브랜치가 다른 세션에 의해 `issue-1048-db-pruning`으로 바뀜). "병행 작업이 필요하면"이 아니라 **항상** §1-3처럼 워크트리를 새로 판다.

## §1 — 작업 시작 (main 최신화 + 브랜치 생성)

1. `git fetch origin main:main` — 로컬 main 레퍼런스만 최신화 (세션 시작 시 hook으로 이미 됐을 수 있으나 작업 착수 직전 한 번 더 확인). **본체 경로에서 `git checkout main`은 하지 않는다** — 다른 동시 세션이 본체를 다른 브랜치로 쓰고 있을 수 있다(원칙 4).
2. 이슈 확인: `gh issue list`로 관련 이슈가 있는지 확인. 없고 작업이 이슈로 남길 만하면 `gh issue create --title "..." --body "..."`로 생성
3. **브랜치+워크트리 생성 (origin/main 기준, 본체 체크아웃은 건드리지 않음)**:
   `git worktree add ../<repo>-issue-<번호> -b issue-<번호>-<짧은설명> main` (예: `git worktree add ../modeumjeon-team-share-issue-42 -b issue-42-price-calc-fix main`)
   이후 모든 작업(커밋 포함)은 이 새 워크트리 경로 안에서 진행한다. 본체 경로에서 `git checkout -b`로 브랜치를 바꾸지 않는다(다른 동시 세션이 쓰고 있을 수 있음).
4. 보고 예: "이슈 #42 워크트리(`../modeumjeon-team-share-issue-42`, 브랜치 `issue-42-price-calc-fix`) 생성, 여기서 작업 시작합니다."

## §2 — 작업 중

- 논리적 단위로 커밋 (커밋 메시지에 이슈 번호 참조 권장: `... (#42)`)
- 이 브랜치 안에서만 작업 — main·다른 브랜치는 건드리지 않음

## §3 — 작업 종료 (push → PR → 확인 → 머지 → 정리)

1. **push**: `git push -u origin issue-<번호>-<설명>`
2. **PR 생성**:
   - `gh` CLI 사용 가능하면: `gh pr create --title "..." --body "..."` (본문에 `Closes #42`로 이슈 연결)
   - `gh` 없으면: push 후 나오는 compare URL(`https://github.com/<owner>/<repo>/compare/main...issue-42-...?expand=1`)을 사용자에게 전달 — 사용자가 브라우저에서 버튼만 누르면 PR 생성됨
3. **보고 + 확인 요청**: PR 링크와 변경 요약 1~2줄을 알리고, **머지해도 되는지 사용자에게 명시적으로 확인 요청**. 확인 없이 다음 단계로 진행하지 않는다.
4. **사용자 확인 후 머지**:
   - `gh` 사용 가능: `gh pr merge --squash --delete-branch`
   - `gh` 없으면: 사용자가 GitHub 웹에서 직접 머지하도록 안내
5. **정리**: 본체 경로에서 `git fetch origin main:main` (로컬 main 최신화, 본체 체크아웃은 건드리지 않음) + `git worktree remove <워크트리 경로>`로 작업용 워크트리 제거
6. **보고**: "머지 완료, main 최신화됨. AWS 자동배포 진행 확인해 주세요." (배포는 push-to-main 트리거이므로 머지 시점에 자동 시작됨)

## 예외

- 사용자가 "바로 main에 push해" 등으로 명시적으로 브랜치·PR 절차 생략을 지시하면 그 지시를 따른다. 기본값은 항상 브랜치+PR+확인.
- `gh` CLI 인증(`gh auth login`)은 사용자가 직접 브라우저에서 완료해야 한다 (Claude가 로그인·OAuth 승인을 대신 하지 않음). 미인증 상태면 §3의 URL 방식으로 대체.
