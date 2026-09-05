// background.js — 확장 서비스 워커. 실제 크롤(소싱처 수집)을 담당.
//  v0.4.1(소싱처별 창 재사용): 소싱처 1곳당 보이는 창 1개를 열고(openWin), 그 소싱처의
//   URL들을 그 창에서 차례로 이동(navGrab/navExtract)하며 크롤 → 사용자가 과정을 눈으로 본다.
//   그 소싱처가 끝나면 창을 닫는다(closeWin). URL마다 창을 열었다 닫던 v0.4.0 의 깜빡임 제거.
//   - navGrab : 비로그인 4개(르무통·SSF·SSG·스스르무통) — 창에서 렌더 HTML 만 수집 →
//               서버 /api/sources/parse 가 추출(ext_bridge 가 배선). SPA 안정화 대기 포함.
//   - navExtract : 무신사·롯데온 — 창 안에서 기존 JS 추출기(EXTRACTORS) 실행.
//   (로그인된 브라우저로 직접 긁으므로 무신사 회원가·롯데온 SPA가 그대로 읽힘.)
//   sysinfo: chrome.system.cpu/memory 로 CPU·메모리 사용률 측정(적응형 컨트롤러 보조 신호).
//  결과 저장은 mou-m.com /api/sources/crawl-result (ext_bridge.crawlBundleAll 이 호출).
//  grabHtml/crawl(URL마다 창 생성·즉시 닫기) 핸들러는 하위호환 위해 유지.

// [2026-07-07 화해] 리포 ↔ 데스크톱 로드본(v0.7.17) 동기화 완료 — 롯데온 익스트랙터
//   (롯데오너스 lotte_member_discount_rate·재고 base/sitm 우선, 2026-07-03 fix Ⓑ·B) 이관.
//   이제 리포가 원천. 데스크톱은 리포에서 동기화(통째복사 금지·패치만).
const MOUM_EXT_VERSION = "0.8.03";  // 0.8.03 = [대량등록] **훑기 잠금이 스스로 풀린다.** 라이브에서 새 필터를 걸어도 「한 번도 실행되지 않음」인 채 수십 분이 지났다 — 확장은 살아서 다른 청에는 답하는데 훑기만 안 돌았다. 어딘가에서 죽은 회차가 _listingBusy 를 쥔 채였다(finally 가 있어도 SW 가 죽었다 되살아나는 등 빠져나가는 길이 있다). 「한 번에 하나」는 지키되 30분을 넘겨 쥐고 있으면 걸린 것으로 보고 놓아 준다(정산 회차 0.7.72 와 같은 처방). ★★배운 것 — 「한 번에 하나」 잠금에는 반드시 시한이 있어야 한다. 시한 없는 잠금은 언젠가 그 기능을 통째로 멈춘다. 0.8.02 = [대량등록] **못 걸은 쪽을 기억했다가 다시 건다.** 크롬이 바쁠 때 탭이 열리다 죽는데(「페이지 로드 시간 초과」·「No tab with id」) 그 쪽 상품이 통째로 빠지고 어느 쪽이었는지 아무도 기억하지 않아 다시 걸 수 없었다 — 라이브 H몰 463쪽 중 **16%(2,748개)가 그렇게 비었는데 화면엔 「끝남」**이었다. 표본 30쪽을 손으로 훑어 겹침 0 을 확인했으니 「그것뿐」이 아니라 못 걷은 것이다. ①실패하면 2.5초 쉬고 **한 번 더** 열어 본다(대개 일시적) ②두 번 다 실패하면 그 주소를 서버에 보내고 **다음 회차 맨 앞**에 세운다. ★못 걸은 쪽이 줄고 있으면 실패가 있어도 이어가고, 안 줄면 멈춘다(영원히 두들기기 방지). 0.8.01 = [대량등록] **건너뛸 쪽도 시간 예산에 넣는다.** 이어서 걷기가 깊어질수록 눌러 건너뛸 횟수가 늘어나는데(121쪽부터면 120번) 예산이 걷는 몫만 세면 건너뛰다 시한이 끝나 한 건도 못 걷는다 → 「새로 걷은 것 0」 → 자동 이어걷기가 멈춘다 → **그 자리에서 굳는다.** ★안전장치(0이면 멈춤)는 그대로 둔다 — 그게 없으면 소싱처를 영원히 두들긴다. 대신 예산을 정직하게 잡는다. 건너뛰기는 훑지 않아 빠르므로 쪽당 3초(걷기 6초). 0.8.00 = [대량등록] **누른 뒤 「바뀔 때까지 지켜본다」.** 아이몰 쪽 넘김 선택자를 고친 뒤 60쪽으로 시켰는데 새로 걷은 것이 0개였다 — 범인은 누른 뒤 고정 1.2초였다. 아이몰이 아직 다시 그리기 전이라 같은 쪽을 읽고 「안 늘었다」며 첫 쪽에서 멈췄다. 내가 손으로 잴 때 3.5초를 기다린 것이 우연히 넉넉했을 뿐이다. ★고정 시간은 두 가지가 다 나쁘다 — 짧으면 같은 쪽을 읽고 멈추고, 길면 쪽마다 느려진다. 첫 상품번호가 바뀌면 바로 넘어가고(빠름) 느린 곳도 안 놓친다(정확). ★★배운 것 — 「기다린다」와 「바뀐 것을 확인한다」는 다르다. 손으로 재서 되던 값을 그대로 코드에 넣으면 그건 실측이 아니라 우연이다. 0.7.99 = [대량등록] **「다음」 단추 소싱처도 이어서 걷는다.** 늘 1쪽에서 눌러 가야 해서 중간부터 시작할 수단이 없다고 봤는데 — 걷지 않고 **누르기만** 하면 된다(click_skip). 301쪽부터면 300번 누르고 시작한다. 훑지 않으니 훨씬 빠르다. 이걸 안 하면 한 회차 상한 60쪽=3,600개가 영원한 천장이라 아이몰 나이키 신발 46,009개(767쪽)의 92%를 영영 못 걷는다. 🔴건너뛰다 시한에 걸려도 「더 있음」이라 말한다(조용한 「끝남」 금지). ★★배운 것 — 「구조상 안 된다」는 판정도 낡는다. 「그 수단이 없다」와 「내가 아직 못 찾았다」는 다르다. 0.7.98 = [대량등록] **끝까지 걷는다.** ①「다음」 단추로 넘기는 곳(롯데온·아이몰)을 **걸음마다 따로 주입**하도록 바꿈 — 예전엔 「눌렀다 훑었다」를 한 번의 긴 주입 안에서 다 해서, 시한을 넘기면 그때까지 걷은 것이 통째로 사라졌고(라이브: 60쪽 시켜 새로 걷은 것 0개) 「다음」이 진짜 페이지 이동이면 주입된 코드가 함께 죽어 영영 안 돌아왔다. 이제 배경이 결과를 들고 있어 페이지가 갈아 끼워지든 통째로 이동하든 걷은 것은 남는다. ②쪽당 예산 4초→6초. ③서버에 **이어서 걷기**(next_page_from) 신설 — 한 회차 60쪽 상한은 소싱처 보호선이라 못 없애지만, 「더 있음」이면 다음 회차가 그 다음 창부터 걷는다. H몰 나이키 신발은 456쪽 16,413개라 60쪽이면 13%뿐이었다. ★끝까지 걸으면 커서를 처음으로 되돌린다(새 상품은 앞쪽에 들어오므로). ★단추로 넘기는 곳은 이어걷기가 안 된다(늘 1쪽에서 눌러 가야 함) — 되는 척하면 거짓말. 0.7.97 = [대량등록] **다 걷고도 「더 있다」고 하던 것.** 라이브 무신사에서 1,204개를 전부 걷고 21쪽에서 끝났는데(22쪽 0개) 「더 있음」이 켜져 있었다 — 무신사는 마지막 쪽 뒤에도 nextPageUrl 을 계속 준다. 0개짜리 쪽에서 빠져나와도 url 이 남아 아래 `if (url) capped=true` 가 켜 버린다. → 한 개도 없는 쪽이 나오면 url 을 비운다. ★★「덜 걷고 끝났다 하기」와 「다 걷고 더 있다 하기」는 둘 다 거짓말이다 — 앞은 없는 상품을 없다고 믿게 하고, 뒤는 있지도 않은 상품을 찾아 쪽 수를 계속 늘리게 만든다. 0.7.96 = [대량등록] 0건 진단이 「받은 글에는 있나」까지 답한다. SSG 실측에서 링크 62개가 전부 메뉴·고객센터·이벤트였다(/ ×24 · /search.ssg ×7 · /customer/* ×6) — 상품 링크가 0개. 현대H몰과 같은 모양새다. 화면에 없다고 안 온 것이 아니므로(H몰: 화면 1쪽 / 받은 글 3쪽 · 겹침 0) 받은 글에 우리 규칙이 몇 개 걸리는지를 같이 센다. 크면 답은 html_scan, 0이면 그 화면엔 정말 상품이 없다. ★이 한 줄이 없어서 H몰 때 있지도 않은 「진짜 마우스 휠」 문제를 며칠 쫓았다. 0.7.95 = [대량등록] 무신사가 60쪽을 시켜도 첫 쪽 47개만 걷고 「끝남」이라 답하던 것. 다음 쪽 주소를 푸는 식이 정규식이 아니었다 — `/\\\\//g` 는 JS 가 세 번째 `/` 에서 정규식을 닫아 버려 뒤의 `/g` 가 정의 안 된 변수 g 로 나누기가 되고 ReferenceError 를 던졌다. 그게 catch(e){} 에 삼켜져 url 이 늘 null → 쪽 넘김이 한 번도 시작되지 않았다(2026-08-12 라이브 실측: 확장 0.7.94 인데도 47). 문법은 맞아 node --check 로는 안 잡힌다. 앞 세션이 이 47 을 「확장이 옛 판이라서」로 진단한 것은 오진이었다. ★같이: 여러 쪽을 시켰는데 다음 쪽 주소를 못 찾으면 capped=true 로 「더 있음」을 말한다 — 조용한 「끝남」은 사장님이 「이 검색엔 47개뿐」이라 믿게 만든다. 0.7.94 = [대량등록] 진단 2건 — 🔴🔴**화면 새로고침(F5)은 확장 본체를 안 바꾼다.** 화면 쪽(content_mou)만 새로 붙어 data-moum-ext 는 새 판을 보여 주는데 일하는 본체(서비스워커)는 옛 판 그대로다. 2026-08-08 라이브에서 「확장 0.7.92 맞음」인데 동작은 0.7.88 이라 한참 헤맸다 → 결과에 **ext_version 을 실어 보낸다**(서버·화면이 알아본다). ★0건이면 **무엇을 봤는지**도 보낸다(그 화면 제목·링크 수·우리 선택자에 걸린 수) — 「상품이 없다」와 「규칙이 안 맞는다」가 똑같이 0으로 보이면 못 고친다(SSG 0건에서 겪음). 0.7.93 = [대량등록] 🔴**현대H몰은 화면이 아니라 받은 글에서 읽는다.** 라이브에서 6쪽을 시켰는데 36개(1쪽 분량)만 나왔다 — page=3 을 열어 재 보니 화면(DOM [data-slitm-cd])은 1쪽 36개, 받은 글(HTML "slitmCd":)은 3쪽 36개, **겹침 0**. 서버는 3쪽을 보내는데 브라우저 안 앱이 다시 1쪽을 불러 화면을 덮어쓴다. → html_scan 규칙 신설(H몰만). ★다른 곳은 화면에서 읽는다 — 화면에 없는 배너·광고가 안 딸려 오는 장점이 있어 추측으로 넓히지 않는다. 0.7.92 = [대량등록] SSG 리스팅 규칙 추가 — 소싱처 7곳. 페이지 넘김 page=(사장님이 2쪽 주소를 그대로 주심)·상품주소 itemView.ssg?itemId= (sourcing/crawlers/ssg.py 첫 줄, 라이브에서 실제로 긁는 값). 🔴**검색 결과 화면은 내 눈으로 못 봤다** — SSG 는 앱 브라우저·크롬 연결 둘 다 정책 차단이고 서버로 받아도 403(2026-08-08). 확장이 사장님 크롬에서 대신 재 보게 하고, 첫 결과를 화면 숫자와 대조하기 전에는 「검증됨」이라 적지 않는다. ★결과0건 추천상품 글귀도 아직 모름 → 비워 둠(지어 넣으면 가짜 통과 또는 멀쩡한 수집이 통째로 0건). 0.7.91 = [대량등록] 🔴**현대H몰은 「스크롤」로 보이지만 주소로 쪽이 넘어간다.** 사장님이 「스크롤 형태」라 하셔서 스크롤을 파고들었는데 — window.scrollTo·안쪽 상자 scrollTop·new WheelEvent 흉내 전부 실패, **진짜 마우스 휠**로 굴리니 화면 상품은 바뀌는데 [data-slitm-cd] 는 계속 같은 36개(합집합 36·새로 생긴 것 0)였다. 화면이 36개짜리 창을 갈아 끼우고 있었던 것. → __NEXT_DATA__ 에 totalCount 16,406·totalPages 456(쪽당 36)이 있었고 검색 주소에 page= 를 붙이니 그대로 넘어갔다(6쪽 216개·중복 0). ★pageNo= 는 안 먹는다(1쪽과 같음). ★배운 것 — 「스크롤로 보인다」가 「스크롤로만 된다」는 뜻은 아니다. 화면 동작을 흉내 내기 전에 주소부터 눌러 볼 것. 0.7.90 = [대량등록] 🔴**SSF 는 같은 소싱처인데 주소 종류에 따라 페이지 넘김이 다르다** — 카테고리 목록은 currentPage 가 진짜 먹고(1쪽·2쪽 상품 60개가 다름), **검색 결과는 안 먹는다**(1쪽·2쪽·page=2 가 상품 60개까지 완전히 겹침, 2026-08-08 실측). 규칙이 소싱처 단위라 구분을 못 해, 검색 주소로 만든 필터가 같은 1쪽을 반복하고 「5장 봤다」고 거짓말할 뻔했다 → 주소 모양별 예외(_NO_PAGE_PATH). ★검색 주소여도 첫 쪽 60개는 그대로 걷는다(예외로 막지 않는다). 0.7.89 = [대량등록] 🔴🔴**무신사 page= 는 서버가 아예 무시한다** — 1쪽과 2쪽 응답의 상품번호가 완전히 같았다(둘 다 totalCount 2412). 그대로 뒀으면 「5쪽까지」로 시켜도 같은 1쪽을 5번 긁고 「5장 봤다」고 거짓말했다. → 응답이 스스로 주는 nextPageUrl 을 따라간다. ★주소를 우리가 조립하면 안 된다 — hmacId 서명이 붙어 있어 page=2 로 손수 바꾸면 403 「잘못된 접근입니다」(실측). 받은 주소를 글자 그대로 따라간다. 실측: 무신사 나이키 41쪽 2,412개(쪽당 60개) · 6쪽 돌려 47→347개 확인. ★쪽 사이 0.7초 쉼. ★안 늘면 중단(헛돌기 방지)·남은 쪽이 있으면 capped 로 「더 있음」. 0.7.88 = [대량등록] **단추로 넘기는 소싱처도 여러 장을 걷는다.** 롯데온·롯데아이몰은 주소로도 스크롤로도 못 넘겨 첫 장(47·60)만 걷혔다 — 「다음」 단추를 눌러 가며 모은다. 실측: 롯데온 47→283 · 아이몰 60→300(5장). ★몇 번 누를지는 서버가 준다(사장님이 적은 「몇 쪽부터~까지」 그대로 — 칸을 새로 만들지 않는다). ★단추가 사라지면(마지막 장) 그만둔다. 🔴눌렀는데 안 늘면 넘어가지 않은 것이라 중단한다(같은 장 헛돌기 방지). ★주소로 넘기는 곳(무신사·SSF·르무통)은 안 누른다 — 두 번 걷게 된다. 🔴훑기 중 20초 심장박동 — MV3 SW 는 30초 조용하면 죽는다. 20쪽이면 1분 반이라 그 사이 SW 가 죽으면 훑기가 기록도 없이 증발한다(0.7.73 정산 회차가 같은 함정에 죽었다). 0.7.87 = [대량등록] 훑기 정확도 3건. 🔴🔴①소싱처 대부분이 **결과 0건이어도 추천 상품을 화면에 깐다** — 그대로 두면 오타 한 번에 엉뚱한 상품이 크롤 대기에 들어가 초안까지 된다(실측: 롯데온 25·롯데아이몰 25·현대H몰 12). 서버가 준 「결과 없음」 글귀가 보이면 0건으로 답한다. ②롯데아이몰은 **링크를 보면 안 된다** — a[href*=viewGoodsDetail] 25건은 전부 메뉴 속 추천 배너다(결과 0건 검색에서도 25건 그대로). 진짜는 data-goods-no(나이키 60·없음 0). ③「더 있다」를 말한다. ★처음엔 「무한 스크롤이라 내리면 더 나온다」고 보고 스크롤을 넣었는데 **틀렸다** — 롯데온 48→48·롯데아이몰 24→24·현대H몰 40→40, 화면을 끝까지 내려도(H몰은 안쪽 스크롤 상자까지) 개수가 그대로였다. 셋 다 **단추로 넘기는** 방식이다(롯데온 「2」를 눌러 상품이 바뀌는 것 확인). → 스크롤을 걷어내고 「다음」 단추가 살아 있는지로 판정한다(선택자는 서버가 준다·모르는 곳은 비워 둬 추측 금지). 🔴capped:true 로 말한다 — 조용히 두면 사장님이 「이 검색엔 48개뿐」이라고 믿는다(개수·페이지 상한도 같이 capped). 단추를 눌러 여러 장을 걷는 건 다음 걸음. 0.7.86 = [정산] 11번가 **구매확정 전** 정산예정액 크롤 — 하루 전엔 「11번가는 그 구간을 마켓 자체가 안 준다(구조적 한계)」고 결론 냈는데 **틀렸다**. 근거로 삼은 「정산 미확정 0건」이 조회 축을 구매확정일(BUY_CNFRM_DT)로 놓은 결과였고, 구매확정 전 주문은 구매확정일이 없어 애초에 조회 대상이 아니었을 뿐이다. 결제일 축(searchDtType=STL_DT) + 정산 미확정(dtlSearchStlmntType=N)으로 부르니 발주확인·배송완료 건이 주문번호(ordNo·ordPrdSeq)와 정산예정액(stlAmt)까지 그대로 온다(2026-08-08 실측 10건 464,691원 — 화면 합계와 일치). ★0건은 「없다」가 아니라 「이 축으론 안 보인다」일 수 있다. ★화면 조회 상한이 한 달이라 90일을 달 단위로 토막내 부른다. ★로그인 풀리면 HTML 이 오므로 조용한 0건이 아니라 needLogin 으로 정직하게 실패. ★못 읽은 토막 수를 돌려준다(덜 긁은 합계를 온전한 값처럼 쓰지 않게).  0.7.85 = [정산] 롯데온 지급내역 크롤 — 롯데온은 정산 OpenAPI 8종·정산예정금액조회·정산요약·셀러머니 어디에도 **실지급일이 없다**. 셀러오피스 「중개거래정산관리 > 지급내역」 selectMediationSettleDetail 의 seCmptDt(정산완료일)가 유일한 답(2026-08-07 실브라우저 확인). 구매확정일(seStdDt) 단위 일정산이라 그 축으로 조인한다.  0.7.84 = 0.7.84 = [대량등록] 훑기 규칙을 **서버가 준다**. 여태 _listingCollectIds 에 a[href*="/products/"] 가 박혀 있어 무신사 전용이었다 — 서버에 SSF·롯데온 규칙을 넣어도 확장은 무신사 링크만 찾아 **에러 없이 0건**(「규칙을 넣었다」와 「그 규칙이 쓰인다」는 다른 사실). → /api/crawl/due-listings 가 sel·attr·id_re 를 같이 내려주고 확장은 요소마다 `속성="값"` 문자열을 만들어 정규식을 건다(링크에서 뽑는 곳과 속성에서 뽑는 곳 H몰 data-slitm-cd 가 규칙 한 벌로 끝난다 — H몰 상품 카드는 <a href> 가 아니다, 실측). ★규칙이 안 오면 훑지 않는다(옛 규칙으로 대신 훑으면 엉뚱한 번호를 긁고 「수집됨」이라 말한다 — 0건보다 나쁘다). 넓힌 소싱처 = SSF·롯데온·롯데아이몰·현대H몰(2026-08-08 실측). 0.7.83 = [대량등록] 구성에 안 걸린 **낱개 주소**도 크롤한다. 검색필터가 넣은 주소 30개가 크롤 4바퀴 도는 동안 하나도 안 긁혔다(2026-08-07 라이브) — due-bundles 는 모음전 **코드**만 주는데 낱개 주소는 어느 구성(BundleSourceUrl)에도 안 걸려 목록에 영영 안 들어가고 에러도 안 났다(조용한 누락). → 서버 /api/crawl/due-urls 신설(구성에 걸린 건 제외 — 겹치면 두 경로가 같은 상품을 두 번 긁는다), 확장이 기존 moum-auto-poll 알람에 얹어 폴링. 크롤·저장은 기존 것 그대로 — crawlItemInTabBG(8소싱처 라우터) + ★saveItemsBG(=toItemBG 매핑) 로 저장. 직접 조립하면 혜택·카테고리경로·사진·상세가 통째로 빠진다. ★한 틱에 5건까지(알람은 1분마다 다시 온다) + _loneBusy 로 창 쌓임 차단. ★서버 enabled 게이트를 여기서도 지킨다(껐는데 도는 상태 금지).  0.7.82 = 0.7.82 = [대량등록] 검색필터 — 검색 결과 URL 한 줄을 훑어 상품 주소를 캔다. 서버 /api/crawl/due-listings 폴링(기존 moum-auto-poll 알람에 얹음 — 알람을 더 만들면 서로 카운트다운을 리셋시키는 사고 표면이 넓어진다) → 페이지를 백그라운드 탭으로 열고 a[href*="/products/"] 번호 수집 → /api/crawl/listing-result 로 전송. ★탭에 재우기 금지(_pinTab) — 크롬 메모리 세이버가 재우면 executeScript 가 영영 안 돌아온다(0.7.75 재발 방지). ★로드 45초 하드 타임아웃 + 한 번에 한 필터(_listingBusy)로 탭 쌓임 차단. ★번호만 보내고 주소 조립은 서버(listing_discover)가 한다 — 주소 규칙을 아는 곳이 둘이 되면 소싱처를 붙일 때마다 확장까지 고쳐야 한다. ★한 장이 실패하면 error 로 실어 보낸다(0건과 구분 — 조용한 실패 금지).  0.7.81 = 0.7.81 = [정산] 로켓그로스 정산 수집 — 로켓그로스 정산액을 주는 **쿠팡 OpenAPI 가 없다**(2026-08-07 실측: 매출내역에 로켓그로스 주문 0건, 정산 회차도 마켓플레이스 몫만). Wing 화면 API `/tenants/rfm/v2/settlements/status/api` 가 유일한 창구인데 로그인 세션 쿠키가 필요해 서버에서 못 부른다 → 롯데온과 같은 로컬 크롤. ★totalArFactoringDeductionAmount = 빠른정산 계좌인출액(이미 받은 돈) 전용 필드가 있어 마켓플레이스보다 정확. ★로그인 만료 시 xauth HTML 이 오므로 0건으로 삼키지 않고 needLogin 으로 정직하게 실패.  0.7.76 = [정산] 「예기치 못한 오류: No tab with id」의 정체 — 감시에 끊긴 옛 회차가 뒷정리까지 흘러와 **지금 도는 새 회차의 롯데온 탭을 닫아** 그 계정을 죽였다(2026-08-06 17:47 라이브: 브랜드마켓). 깃발·기록엔 세대 가드가 있었는데 탭 정리에만 빠져 있었다 → 뒷정리도 내 세대일 때만.  0.7.75 = [정산] 자동 회차 실패 2~3계정의 진짜 원인 — 롯데온 전용 백그라운드 탭에 **재우기 금지(autoDiscardable=false) 핀이 없었다**. 크롬 메모리 세이버가 그 탭을 재우면 executeScript 가 영구 대기하고(→30분 감시가 회차를 통째로 끊음), 깨어난 탭은 로그인 세션을 잃어 「로그아웃 실패·로그인 실패」로 떨어진다 (2026-08-06 실측: 하루 4회 강제중단·매 회차 실패 2~3, 같은 계정을 손으로 돌리면 정상 — 손 회차는 짧고 브라우저를 쓰는 중이라 탭이 안 재워진다). 서비스 탭엔 2026-06-22 에 같은 이유로 이미 핀이 있었는데 롯데온 탭만 빠져 있었다. 같이 막은 무한대기 3곳: ①주입 1회 하드 타임아웃(45초·수집은 예산만큼) ②페이지 안 XHR timeout 30초(기본은 무한) ③수집 루프 자체 예산. 더불어 ④실패 계정 1회 자동 재시도(손으로 다시 누르면 되던 것을 회차가 스스로) ⑤회차 예산 25분·감시 30→40분(감시가 「회차 끝내는 정상 수단」이 되어 있었다 — 끊기면 계정별 기록이 안 남는다) ⑥순서가 못 온 계정부터 다음 회차 출발(뒷자리 계정이 영영 굶는 것 방지).  0.7.74 = [정산] 회차 이력(hist) — 화면 「기록」이 페이지가 손수 돌린 회차만 적어, 자동을 확장으로 옮긴 뒤론 기록이 하루 통째로 비었다(2026-08-05 실측: 최근 22:40 인데 기록 마지막이 어제 00:07 = 한 화면 모순). 이력의 주인은 회차의 주인(확장) — 완료·강제중단·도중끊김을 storage hist(최근 60회)에 남기고 getState 로 화면이 그린다. 화면이 꺼져 있던 시간의 회차도 이제 기록에 보인다.  0.7.73 = [정산] 회차 심장박동+시작 도장 —MV3 SW 는 30초 조용하면 크롬이 죽인다. 회차가 탭 로드를 조용히 기다리다 SW 와 함께 증발했다(실측 2026-08-04 저녁: 19:56·20:56 연속, 기록 0 — 낮엔 다른 크롤 활동이 우연히 SW 를 깨워 둬 살아남음). ①회차 중 20초마다 storage.get 심장박동으로 SW 유지 ②시작 도장(runStartedAt)을 스토리지에 박고 SW 재기동 시 끝맺음 없는 도장이 보이면 「회차 도중 크롬이 확장을 재워 끊김」을 last.error 로 남긴다(증발 금지 — 여태 「거른 것」과 구분 불가였다).  0.7.72 = [정산] 회차 감시 —한 회차가 30분을 넘겨 안 끝나면(롯데온 페이지 무한 대기 등) 강제로 내려놓고 다음 회차부터 다시 돈다. 걸린 회차가 _settleRunning 을 영영 쥐면 틱이 매번 busy 로 빠져 회차를 1~2시간씩 걸렀다(2026-08-04 실측: 17:10 다음이 19:56). 세대표(_settleGen)로 옛 회차는 나아가지도·상태를 쓰지도 못하게 해 새 회차와의 이중 실행·이중 기록을 막는다. 강제 중단은 last.error 로 남긴다(조용한 복구 금지).  0.7.71 = 병합 —0.7.70(정산 via=auto)과 0.7.69(폰 리모컨 상시 폴링)를 합침(내용 변경 없음).  0.7.70 = [정산] 회차 기록에 via="auto" 를 명시. 화면에서 손으로 돌린 회차(via="manual")와 섞이면 안 된다 — 배너는 「자동이 살아 있나」를 묻는데 수동까지 세면 한 번 눌러 본 것만으로 조용해져 자동이 죽어도 모른다.  0.7.68b = [정산] 계정별 회차 결과를 서버에 남긴다(/api/margin/lotteon-crawl-run). 여태 「자동이 돌고 있나」를 정산표 updated_at 으로 짐작했는데 그건 「값이 바뀐 시각」이라 양방향으로 틀린다(안 바뀌면 멀쩡해도 낡아 보이고, 막혀도 남이 바꾸면 최신으로 보임). 화면도 「실패 2」만 알려줘 어느 계정인지 몰랐다 → 계정 단위 ok|verify|fail 기록.  0.7.69 = 폰 크롤 리모컨 — 크롤 폴링 알람을 상시화. 멈춰 있어도 확장이 1분마다 서버를 물어 ①폰에서 시작 가능 ②서버가 PC 생존 판정 가능. 크롤 동작 자체는 불변(서버 enabled 게이트가 이중 안전). ★부수효과 = 열린 mou-m 탭이 하나도 없으면 백그라운드 탭 1개가 상주한다 — 폴링이 bgFetch→ensureServiceTab 을 타는데 자동 폴링 경로엔 closeServiceTabIfOwned 가 없다(크롤 PC 는 세션 유지가 이득이라 의도적으로 둠). 같이: 알람은 없을 때만 생성(alarms.create 는 대체라 SW 가 깰 때마다 리셋되면 영영 안 터진다) + onStartup/onInstalled 에서 1회 즉시 폴(첫 신호까지 60초 공백 제거).  0.7.68 = [정산] 롯데온 정산 자동 회차가 최근 60일만 훑어, 그 창을 지나서 확정된 정산은 영영 못 보고 0/공란으로 굳었다(라이브 실측: 롯데온 결손 915건 중 크롤없음 874건). → 2단 회차(매 회차 60일 · 하루 1회 180일). 같이: source="auto" 로 push 해 서버가 「자동이 돌고 있나」를 답할 수 있게 + 여태 수집해놓고 버리던 주문 크롤분(orderRows)을 /lotteon-so-upsert 로 1,000개씩 나눠 전송(rows>2000 은 400 인데 .catch 로 삼켜져 조용히 유실).  0.7.67 = [노션 보고] 캡처에 옆 요일 칸이 같이 찍히던 것 — 위로 올라가며 「충분히 큰 블록」을 잡으니 여러 요일을 감싸는 바깥 덩어리가 잡혔다(2026-08-02 실측: 일요일 옆에 목요일이 반쯤). → **요일 이름이 하나만 들어있는** 가장 큰 덩어리로 판별(dayCount>1 이면 거기서 멈춤). 라벨 개수 기준이라 노션 DOM 구조가 바뀌어도 버틴다.  0.7.66 = [노션 보고] 캡처 백지 재발 — 스크롤로 렌더를 유도한 게 틀렸다. 노션은 화면을 벗어난 블록을 **위아래 양쪽** 모두 지운다(2026-08-02 실측: 아래를 그리러 내려가니 위가 지워져 「일요일」 라벨만 남고 전부 백지). → 스크롤을 버리고 Emulation.setDeviceMetricsOverride 로 **화면 높이를 9000px 로 위장**한다. 노션이 칸 전체를 「보이는 것」으로 여겨 한꺼번에 그리므로 스크롤이 아예 필요 없다. 끝나면 clearDeviceMetricsOverride.  0.7.65 = [노션 보고] 캡처 아래가 잘리던 것 — 노션은 화면 밖 블록을 미리 안 그린다(지연 렌더). 재는 순간 높이만 믿고 찍으면 아직 안 그려진 아래쪽이 백지로 나온다(2026-08-02 실측: 「오후」 아래 전부 빈 칸). → 칸 끝까지 조금씩 훑어 내려 다 그리게 한 뒤 높이가 3회 연속 그대로일 때 잰다. 스크롤 중 요소가 교체될 수 있어 매 회 다시 찾는다. 높이 상한 6000→12000.  0.7.64 = [노션 보고] 노션 「투두리스트 (영빈)」 오늘 요일 칸을 잘라 mou-m 에 올린다(카톡 보고 사진). 1분 알람 → /api/reports/notion-todo/shot/needed 로 「발송 10분 전인가·신선한 캡처가 있나」 확인 → 필요할 때만 노션을 백그라운드 탭으로 열어 캡처 후 닫는다. ★captureVisibleTab 이 아니라 chrome.debugger 의 Page.captureScreenshot(captureBeyondViewport) — 보이는 화면만 찍으면 화면보다 긴 요일 칸이 잘린다. ★노션 CSS 클래스는 수시로 바뀌므로 클래스에 안 기댄다: 「요일 글자」 텍스트노드를 찾아 위로 올라가며 충분히 큰 [data-block-id] 블록을 고른다. 업로드는 mou-m 탭 안 same-origin fetch(SW 직접 fetch 는 SameSite=Lax 세션쿠키가 안 실림). 권한 추가: debugger + notion.so/notion.com/notion.site.  0.7.63 = [M4-5] 확장 경로 소싱처(무신사·롯데온) 상품 사진·상세설명 수집·전달 — 무신사 = 이미 부르는 api2/goods/{id} 응답의 thumbnailImageUrl(대표)+goodsImages[](추가컷)+goodsContents(상세HTML), 추가호출 0. 호스트 image.msscdn.net 은 PDP og:image 와 문자열 일치 실측·렌디션 _500 치환 금지(떼면 404). 롯데온 = JSON-LD Product.image 1순위 + base API imgInfo.imageList(imgRteNm+imgFileNm, 접두 contents.lotteon.com/itemimage) 폴백, 상세는 descInfo.epnJsn DSCRP → contents.lotteon.com/itemdetail 파일(★후보 6개 중 이것만 200, 나머지 403). 🔴 상세 파일은 CORS 헤더가 없어 페이지에서 못 받는다 → host_permissions 로 서비스워커(fetchDetailFileBG)가 받는다. 조립 규칙 단일 원천 = M4IMG-HELPERS 블록(추출기는 원문 조각만 넘김). 배관 = BG_JS 결과조립 분기 + fetchMusinsaAdapter + toItemBG image_urls/detail_html 명시 통과. ★BENEFIT_PASSTHROUGH 금지(중복 저장). 사진 0장이면 콘솔 경고(조용한 실패 금지). 0.7.62 = 0.7.62 = [M3 Task5] 소싱처 카테고리 경로(빵부스러기) 수집·전달 — 무신사 = api2/goods/{id} 응답의 category.categoryDepth{1..4}Name(★PDP 엔 빵부스러기 DOM 도 BreadcrumbList JSON-LD 도 없다, 2026-07-23 실측 → 이 API 가 유일 원천. baseCategoryFullPath 는 1단계가 영문이라 미사용) · 롯데온 = JSON-LD Product.category 1순위 + DOM ol.locationList 폴백(실측 두 원천 값 동일). 조립 규칙은 서버 base.build_category_path 와 동일(구분자 '>'·조각 공백정리·맨 앞 '홈'류 더미만 제외). 배관 = crawlItemInTabBG 6개 결과조립 분기(same-origin·BG_JS·navGrab+parse·fetchRawParse·fetchMusinsa·fetchHmall) + toItemBG 에 category_path 명시 통과. ★BENEFIT_PASSTHROUGH 에는 넣지 않는다 — 그 배열은 혜택 화이트리스트(서버 OPTION_DYNAMIC_KEYS 와 정적 핀)라 넣으면 dynamic_benefits_json 에 중복 저장된다(전용 컬럼 source_products.category_path 가 진실 원천). 빈 값은 서버가 건너뛰어 기존값 보존(무스톰프). 0.7.61 = [2차 T6] N쇼핑 경유(naver_via) 수집 — Hmall = item-ptc 의 tcDcInf(tcCdNm "네이버가격비교"·dcRate·tcDcAmt) 로 판별(★raw HTML 엔 없다 — 할인내역이 JS 렌더라 12KB 스켈레톤뿐, 로드 전 실측으로 확정) · 롯데온 = favorBox 의 「제휴할인」 항목. 둘 다 표시가에 **선반영**이라 naver_via_preapplied=true 로 보내 서버가 재차감하지 않게 한다(이중차감 방지). naver_via_{rate,amount,preapplied,label} 4키 화이트리스트 통과. 0.7.60 = [2차 T1 핫픽스] Hmall 카드 수집 코드가 범용 fetchRawParseAdapter 에 잘못 들어가 hmall 경로(fetchHmallAdapter)에서 실행되지 않던 것 교정 + content_mou 버전 동기화(0.7.54 로 굳어 로드버전 진단이 틀렸음). 0.7.59 = 0.7.58(롯데온 SO 주문크롤 자동사이클 배선, 별도 세션) + [2차 T1] Hmall 카드 즉시할인·결제 프로모션 창없이 수집 — item-prmo-lst API + 쿠키 uh2oxid 를 헤더로 재전송(쿠키만이면 401). crdImdtDcPrmoList → hmall_card_discounts[{label,rate,amount,min_order,promo,valid_until}] · stlmWayPrmoList → hmall_pay_promos. 기간·노출·PC적용 가드로 만료분 차단(매입가 과소 방지).  // 0.7.56 = [Task10] parse 소싱처(르무통·SSF·SSG·스스르무통·현대H몰·롯데아이몰) 혜택 필드 crawl-result 전달 — 서버 파서가 옵션에 채워 주는 동적 혜택 키(SSF point_rate/gift_point·SSG MONEY/카드혜택가/상품쿠폰·H.Point·아이몰 카드할인·리뷰적립 등 BENEFIT_PASSTHROUGH 22키)를 4개 결과조립 분기(same-origin·navGrab·fetchRawParseAdapter·fetchHmallAdapter)의 options 매핑과 item 레벨(pickBenefitsFromOptions — hmall 은 per-size 교체로 옵션혜택이 사라져 교체 전 parse 옵션에서 승격)에 실어 보낸다. 있는 키만 전송(pickBenefits 가 null/0/''/false/빈배열 제거) — 키 부재 시 서버는 parse 영속값 보존(무스톰프 핀: tests/pricing/test_parse_path_benefit_no_stomp.py). 효과 = ①신규 URL 첫 크롤 상품레벨 혜택 즉시 영속(기존엔 parse 의 _save 가 SP 부재로 스킵) ②hmall 콤보 혜택 유지 ③payload 단일 진실. 0.7.55 = [T6] 롯데온 pbf 혜택 API 이식 — lotteonExtractor 가 favorBox/benefits·qtyChangeFavorInfoList(둘 다 POST, body=base API 재구성+상수 — Playwright 실측으로 원본 body 와 응답 일치 확인, 최소 body 는 rc=422)를 직접 불러 lotteon_max_price(최대혜택 적용가 = qty.orderDcAplyTotAmt, 폴백 favor.totAmt)·lotteon_card_discounts([{label,amount,rate}] — 카드 판정 = lotteon.py is_card_coupon: 그룹 title=="카드즉시할인/장바구니쿠폰" OR prKndCd∈{CRD_IMMD,CPN_BSK_CPN} OR prTypCd=="CRD_PR")·lotteon_store_discount(1ST 스토어 즉시할인 합, 정보용) 3필드 emit. 실패=null/[] (폴백 금지 — 서버가 기존 베이스로 계산). MAIN world 로그인 쿠키라 로그인 한정 ORDER 그룹(카드) 보임. crawlItemInTabBG BG_JS 분기·toItemBG 화이트리스트에 3필드 통과 배선(서버 키는 T7). 0.7.54 = [S5] crawl.one — 소싱처 지도 예시 주소 「▶ 크롤」용 단건 크롤. 엔진과 같은 라우터(crawlItemInTabBG)를 태워 8개 소싱처 전부 지원(기존 crawl 은 EXTRACTORS=무신사·롯데온만 알아 나머지 6개가 "레시피 없음"으로 실패했다). 저장 안 함 — /api/sources/crawl-result 를 안 불러 실상품 데이터를 건드리지 않는다. 계산·저장은 서버 /sourcing-guide/api/<sid>/url-result. 0.7.53 = 정산 「자동 반복」을 확장이 소유(moum.settle-auto.set/getState) — chrome.alarms+storage.local 로 스케줄·순회를 SW 가 돌려 크롤-로그인 탭을 닫아도(크롬만 켜져 있으면) 계속 돈다. 계정목록은 서버 /accounts/api/crawl-login/accounts. 페이지는 토글·표시만(supported 응답으로 위임 판정 — 구버전이면 페이지 폴백 유지해 기능이 죽지 않게). 0.7.52 = 정산 「자동 반복」 탭 지킴이(moum.settle-keepawake) — 켜진 동안 크롤-로그인 탭 재우기 금지 + 재워졌으면 1분 알람이 되살림 → 다른 탭을 봐도 회차가 안 끊긴다. 스케줄 계산은 페이지가 단독(이중화 금지). ※manifest 와 이 상수가 어긋나 있었다(0.7.51 vs 0.7.36) — 맞춰 둔다. 0.7.34 = winless 동시 레인 — fetch형 소싱처(SW: lemouton·ssf·hmall = 창0 / same-origin: ssg·lotteimall = 도메인탭1개)는 창을 URL마다 안 열고 탭 1개(또는 0개) 안에서 '동시 상한'개 동시 fetch. '동시 상한'=레인수(창수 아님). winless 레인은 fetchOnly(창 폴백 생략·정직 error). 렌더(무신사·롯데온)만 창=레인 유지. 0.7.33 = 소싱처별 동시상한 클램프 3→8. 0.7.26 = [E2] 마진계산기 소싱처 주문상태 확인(sourcing.check-order → 주문 URL 창 오픈+사이트별 파서 주입, 크롤=로컬). spike = 무신사 창없는 probe(진단 전용, 엔진 미배선). 0.7.17 = 실시간 집계(agg done/total) 브로드캐스트 → 자동화 링이 위젯과 동일. 0.7.16 = 상세 전체크롤 최우선. 0.7.6 = 자동화 워커 폴링 + 무신사 상품쿠폰(product_coupon_list) 전량수집 API우선+DOM폴백. 0.7.5 = manifest 버전동기화. 0.7.4 = content_mou 백그라운드 로그 중계. 0.7.3 = 현대H몰 sellGbcd 품절판정(S19). 0.6.x: 백그라운드 크롤 상태 영속+SW 자동재개

// cascade 위치 시퀀서 — 창이 여러 개 열려도 서로 어긋나 보임
let _winSeq = 0;

// SPA(르무통·SSG·스스르무통) 가격 DOM 이 로드 완료 후에도 늦게 뜰 수 있어
//  navGrab 은 로드 완료 뒤 추가 안정화 대기 후 outerHTML 을 뜬다(빈 HTML 방지).
const NAVGRAB_SETTLE_MS = 1200;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const type = msg && msg.type;
  if (type === "ping") {
    sendResponse({ pong: true, version: MOUM_EXT_VERSION,
      from: sender && sender.url ? new URL(sender.url).host : null, ts: Date.now() });
    return false;
  }
  if (type === "crawl") {
    handleCrawl(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  if (type === "grabHtml") {
    handleGrabHtml(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  if (type === "openWin") {
    handleOpenWin(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  if (type === "navGrab") {
    handleNavGrab(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  if (type === "navExtract") {
    handleNavExtract(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  if (type === "closeWin") {
    handleCloseWin(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  // ── [2026-07-19 · S5] 소싱처 지도 예시 주소 「▶ 크롤」 — URL 1건, 저장 없음 ──
  //   기존 "crawl" 은 EXTRACTORS(무신사·롯데온) 만 알아 나머지 6개 소싱처에서
  //   "레시피 없음"으로 실패한다. 여기서는 엔진이 실제로 쓰는 라우터
  //   crawlItemInTabBG 를 그대로 태워 8개 소싱처 전부 같은 경로로 긁는다
  //   (= 화면 값과 실크롤 값이 어긋나지 않는다).
  if (type === "crawl.one") {
    handleCrawlOne(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, status: "error", error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  // ── [2026-07-12 · Task E2] 소싱처 주문상태 확인 (마진계산기 '✓ 확인' 버튼) ──
  //   서버 Playwright(원본 /api/check-sourcing) 를 대체 — 로그인된 이 브라우저로 주문 URL 을 열어
  //   사이트별 파서를 주입해 상태를 읽고 창을 닫는다(크롤=로컬 원칙). 미로그인/파싱실패 정직 표면화.
  if (type === "sourcing.check-order") {
    handleCheckOrder(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({
        ok: false, order_status: "", courier: "", tracking: "",
        site_name: (msg.payload || {}).site_name || "", source: "ext-local", logs: [],
        is_logged_in: null, error: String(e && e.message ? e.message : e),
      }));
    return true; // async
  }
  if (type === "sysinfo") {
    handleSysinfo()
      .then((r) => sendResponse(r))
      .catch((_) => sendResponse({ ok: true, cpu: null, mem: null }));
    return true; // async
  }
  if (type === "probe.musinsa") {
    probeMusinsaWindowless((msg.payload || {}).goodsId)
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  // [2026-07-07] 어댑터 단건 테스트(읽기 전용·저장 안 함) — G1 검증용. payload={sk,url}.
  if (type === "probe.adapter") {
    const _p = msg.payload || {};
    const _fn = FETCH_ADAPTERS[_p.sk];
    if (typeof _fn !== "function") { sendResponse({ ok: false, error: "어댑터 없음: " + _p.sk }); return false; }
    Promise.resolve(_fn({ source_key: _p.sk, url: _p.url, url_type: _p.url_type || "dan" }))
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  // ── [2026-06-14] 2단계: 백그라운드 오케스트레이터 제어 메시지 ──
  //   크롤 엔진이 이 서비스워커에서 돌아 페이지(탭)를 닫거나 이동해도 지속된다.
  if (type === "crawl.enqueue") {
    const _p = msg.payload || {};
    // [v0.6.7] 서버 타깃(base) = enqueue 한 페이지 origin 자동 — 라이브(mou-m)에서 크롤하면
    //   라이브, 로컬(localhost)에서 크롤하면 로컬 새코드 서버로 저장(배포 전 '크롤·검증').
    if (!_p.base && sender && sender.tab && sender.tab.url) {
      try { _p.base = new URL(sender.tab.url).origin; } catch (_) {}
    }
    sendResponse(mgrEnqueue(_p));
    return false;
  }
  if (type === "crawl.pause")  { sendResponse(mgrPause());  return false; }
  if (type === "crawl.resume") { sendResponse(mgrResume()); return false; }
  if (type === "crawl.stop")   { sendResponse(mgrStop());   return false; }
  if (type === "crawl.cancel") { sendResponse(mgrCancel((msg.payload || {}).code)); return false; }
  if (type === "crawl.getState") { sendResponse(mgrSnapshot()); return false; }
  // ── [2026-07-04] 자동화: 서버 due-bundles 폴링 시작/중지 (실행/정지 토글에서 발동) ──
  if (type === "moum.auto-poll.start") {
    if (!_mgr.base && sender && sender.tab && sender.tab.url) {
      try { _mgr.base = new URL(sender.tab.url).origin; } catch (_) {}
    }
    moumAutoPollStart();
    sendResponse({ ok: true });
    return false;
  }
  if (type === "moum.auto-poll.stop") { moumAutoPollStop(); sendResponse({ ok: true }); return false; }
  // ── [2026-07-17] 정산 「자동 반복」 켜짐 동안 크롤-로그인 탭 재우기 금지(다른 탭에 있어도 계속) ──
  if (type === "moum.settle-keepawake") {
    if ((msg.payload || {}).on) settleKeepAwakeStart(); else settleKeepAwakeStop();
    sendResponse({ ok: true });
    return false;
  }
  // ── [2026-07-17] 정산 「자동 반복」 스케줄을 확장이 소유(탭 닫아도 돎) ──
  //   페이지는 여기에 토글만 넘기고 상태를 받아 표시한다. supported:true 가 곧 '이 확장은
  //   탭 없이 돌릴 수 있다'는 신호 — 페이지는 이게 없으면 예전 방식(자체 타이머)으로 폴백한다.
  if (type === "moum.settle-auto.set") {
    const _p = msg.payload || {};
    let _base = _p.base || "";
    if (!_base && sender && sender.tab && sender.tab.url) { try { _base = new URL(sender.tab.url).origin; } catch (_) {} }
    settleAutoSet(!!_p.on, _p.min, _base)
      .then(() => settleLoad()).then((st) => sendResponse({ ok: true, supported: true, state: st }))
      .catch((e) => sendResponse({ ok: false, supported: true, error: String(e) }));
    return true; // async
  }
  if (type === "moum.settle-auto.getState") {
    settleLoad()
      .then((st) => sendResponse({ ok: true, supported: true, state: st, running: _settleRunning }))
      .catch((e) => sendResponse({ ok: false, supported: true, error: String(e) }));
    return true; // async
  }
  // ── [2026-07-16] 롯데온 정산 크롤: 로그인된 판매자센터 세션서 soapi selectBgt 페이징 수집 → 서버 push ──
  if (type === "lotteon.settle.crawl") {
    let base = "https://mou-m.com";
    if (sender && sender.tab && sender.tab.url) { try { base = new URL(sender.tab.url).origin; } catch (_) {} }
    handleLotteonSettleCrawl(msg.payload || {}, base)
      .then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // ── [2026-07-23] 롯데온 주문 크롤: 통합주문조회(getOrderList) — OpenAPI 가 못 주는
  //    취소 라인·취소건 구매자·철회 취소 신호의 유일 원천(라이브 실측 164필드) ──
  if (type === "lotteon.orders.crawl") {
    let base2 = "https://mou-m.com";
    if (sender && sender.tab && sender.tab.url) { try { base2 = new URL(sender.tab.url).origin; } catch (_) {} }
    handleLotteonOrdersCrawl(msg.payload || {}, base2)
      .then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // ── [2026-07-16] 롯데온 방식A 자동 로그인: 저장 자격증명으로 판매자센터 로그인폼 자동입력·제출 ──
  if (type === "lotteon.autologin") {
    handleLotteonAutoLogin(msg.payload || {})
      .then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // 로그아웃(계정 전환용) — 판매자센터 로그아웃 후 로그인 페이지 대기
  if (type === "lotteon.logout") {
    handleLotteonLogout()
      .then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // ── [2026-07-16] 롯데온 계정 1건 완전 자동(전용 탭서 로그아웃→로그인→정산수집 한 메시지로) ──
  //   전용 백그라운드 탭만 사용 → 사용자의 다른 롯데온 탭을 건드리지 않음(탭 오판 제거).
  if (type === "lotteon.account.collect") {
    handleLotteonAccountCollect(msg.payload || {})
      .then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // ── [2026-08-07] 롯데온 지급내역 크롤: 「언제 실제로 입금됐나」 ──
  //   🔴 롯데온은 정산 OpenAPI 8종·정산예정금액조회·정산요약·셀러머니 어디에도 **실지급일이
  //     없다**(pymtTgtAmt 는 예정액). 셀러오피스 「중개거래정산관리 > 지급내역」의
  //     `seCmptDt`(정산완료일)가 유일한 답이다(2026-08-07 실브라우저로 확인).
  if (type === "lotteon.paid.crawl") {
    handleLotteonPaidCrawl(msg.payload || {})
      .then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // ── [2026-08-07] 로켓그로스 정산 크롤: Wing 화면 API 를 로그인 세션으로 긁어 서버 push ──
  //   🔴 왜 크롤인가 — 로켓그로스 정산액을 주는 **OpenAPI 가 없다**(라이브 실측: 매출내역에
  //     로켓그로스 주문 0건, 정산 회차도 마켓플레이스 몫만). Wing 화면 API 가 유일한데
  //     로그인 세션 쿠키가 필요해 서버(AWS)에서 못 부른다 → 롯데온과 같은 로컬 크롤 구조.
  if (type === "coupang.rg.settle.crawl") {
    handleCoupangRgSettleCrawl(msg.payload || {})
      .then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // ── [2026-08-08] 11번가 구매확정 전 정산예정액: 결제일 축 + 정산 미확정 ──
  //   🔴 전날 나는 「11번가는 구매확정 전 정산예정액을 안 준다」고 잘못 결론 냈다.
  //     구매확정일 축으로만 조회해 0건이 나온 걸 「없다」로 읽은 것이다. 결제일(STL_DT)
  //     축 + 정산 미확정(N) 으로 보면 주문번호·금액이 그대로 온다(사장님 화면 실증).
  if (type === "eleven11.unconf.crawl") {
    handleEleven11UnconfCrawl(msg.payload || {})
      .then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // ── [2026-08-13] 롯데온 지급내역(실입금일) ────────────────────────────────────
  //   🔴 `handleLotteonPaidCrawl` 은 2026-08-07 에 이미 만들어져 있었는데 **여기 등록이
  //     빠져 있었다.** 그래서 화면에서 부를 방법이 없었고, 롯데온만 「이미 받았다」가
  //     라이브에서 **0건**이었다(받는 날 1,175건 전부 추정 — 쿠팡·스스·11번가는 실값).
  //     함수는 지어 놓고 문고리를 안 단 상태였다. 「조용히 안 도는」 부류의 사고다.
  if (type === "lotteon.paid.crawl") {
    handleLotteonPaidCrawl(msg.payload || {})
      .then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // 전용 탭 닫기(전체 순회 종료 후 정리)
  if (type === "lotteon.closetab") {
    (async () => {
      if (_loTabId != null) { try { await chrome.tabs.remove(_loTabId); } catch (_) {} _loTabId = null; }
      sendResponse({ ok: true });
    })();
    return true;
  }
  sendResponse({ error: "unknown type: " + type });
  return false;
});

// ── [2026-08-07] 롯데온 지급내역 크롤 ──────────────────────────────────────────
//  창구: GET soapi.lotteon.com/settle/v1/so/mediationSettleManagement/selectMediationSettleDetail
//        ?trNo=&strtDttm=YYYYMMDD&endDttm=YYYYMMDD&searchDtFg=02&pageNo=1&rowsPerPage=100
//  ★ 로그인된 store.lotteon.com 세션에서 불러야 한다(soapi 는 store 오리진만 허용).
//  ★ 응답 data.settleDetailList.dataList[] — 구매확정일(seStdDt) 단위 일정산 행.
async function handleLotteonPaidCrawl(payload) {
  const since = String(payload.since || "").replace(/-/g, "") || _ymdOffset(-180);
  const until = String(payload.until || "").replace(/-/g, "") || _ymdOffset(0);
  let tab = (await chrome.tabs.query({ url: "https://store.lotteon.com/*" }))[0];
  let opened = false;
  if (!tab) {
    tab = await chrome.tabs.create({
      url: "https://store.lotteon.com/cm/main/index_SO.wsp", active: false });
    opened = true;
    try { await waitTabComplete(tab.id, 25000); } catch (_) {}
  }
  let res;
  try {
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: "MAIN",
      func: lotteonPaidCrawlInPage, args: [since, until, payload.trNo || ""],
    });
    res = (out && out[0] && out[0].result) || { ok: false, error: "실행 결과 없음" };
  } finally {
    if (opened) { try { await chrome.tabs.remove(tab.id); } catch (_) {} }
  }
  return res;
}
// MAIN world 주입 — store.lotteon.com 페이지 컨텍스트(세션)에서 실행. 외부 스코프 참조 금지.
function lotteonPaidCrawlInPage(sinceYMD, untilYMD, trNoArg) {
  return (async () => {
    try {
      let trNo = trNoArg || "";
      if (!trNo) {
        const el = document.querySelector("#mf_sellerShop_trNo");
        trNo = (el && (el.innerText || "").trim()) || "";
        if (!trNo) {
          const m = (document.body.innerText || "").match(/LO\d{6,}/);
          trNo = m ? m[0] : "";
        }
      }
      if (!trNo) return { ok: false, error: "trNo not found" };
      let tok = "";
      for (let i = 0; i < sessionStorage.length; i++) {
        const v = sessionStorage.getItem(sessionStorage.key(i)) || "";
        if (/^[0-9a-f]{56}$/i.test(v)) { tok = v; break; }
      }
      if (!tok) return { ok: false, error: "session token missing", needLogin: true };
      const rows = [];
      for (let page = 1; page <= 20; page++) {
        const url = "https://soapi.lotteon.com/settle/v1/so/mediationSettleManagement"
          + "/selectMediationSettleDetail?spclAprvCmsn=&odNo=&sitmNo=&ltrtNo="
          + "&strtDttm=" + sinceYMD + "&endDttm=" + untilYMD + "&trNo=" + trNo
          + "&searchDt=&searchDtFg=02&pageNo=" + page + "&rowsPerPage=100";
        const body = await new Promise((resolve, reject) => {
          const x = new XMLHttpRequest();
          x.open("GET", url, true);
          x.withCredentials = true;
          x.timeout = 30000;
          x.setRequestHeader("authorization", "Bearer " + tok);
          x.setRequestHeader("x-timezone", "GMT+09:00");
          x.setRequestHeader("accept", "application/json");
          x.onload = () => { try { resolve(JSON.parse(x.responseText)); }
                            catch (e) { reject(new Error("parse fail " + x.status)); } };
          x.onerror = () => reject(new Error("network error"));
          x.ontimeout = () => reject(new Error("timeout 30s"));
          x.send();
        });
        const lst = (((body || {}).data || {}).settleDetailList || {}).dataList || [];
        rows.push.apply(rows, lst);
        if (lst.length < 100) break;
      }
      return { ok: true, trNo: trNo, rows: rows, collected: rows.length };
    } catch (e) {
      return { ok: false, error: String((e && e.message) || e) };
    }
  })();
}

// ── [2026-08-08] 11번가 구매확정 전 정산예정액 크롤 ─────────────────────────────
//  창구: POST soffice.11st.co.kr/remittance/SellerRemittanceAction.tmall
//        ?method=getSelAllStatDtlsSoffice&dtlSearchStlmntType=N&searchDtType=STL_DT
//  ★ dtlSearchStlmntType=N(정산 미확정) + searchDtType=STL_DT(결제일) 두 개가 핵심이다.
//    구매확정일(BUY_CNFRM_DT) 축이면 구매확정 전 주문은 **조회 대상이 아니라 0건**이 나온다.
//  ★ 화면 조회 상한이 **한 달**이라 기간을 달 단위로 토막내 부른다(2026-08-08 실측).
//  ★ 셀러오피스 세션 쿠키가 필요해 서버에선 못 부른다 → 로컬 크롤(롯데온·로켓그로스와 동일).
async function handleEleven11UnconfCrawl(payload) {
  const days = Number(payload.days || 90) || 90;      // 기본 90일 — 배송완료로 굳는 건이 있다
  const chunks = _monthChunks(days);
  let tab = (await chrome.tabs.query({ url: "https://soffice.11st.co.kr/*" }))[0];
  let opened = false;
  if (!tab) {
    tab = await chrome.tabs.create({
      url: "https://soffice.11st.co.kr/view/35936", active: false });
    opened = true;
    try { await waitTabComplete(tab.id, 30000); } catch (_) {}
  }
  let res;
  try {
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, func: eleven11UnconfCrawlInPage, args: [chunks],
    });
    res = (out && out[0] && out[0].result) || { ok: false, error: "실행 결과 없음" };
  } finally {
    if (opened) { try { await chrome.tabs.remove(tab.id); } catch (_) {} }
  }
  return res;
}
// 오늘부터 거꾸로 days 일을 **한 달 이하** 토막으로 자른다 (화면 상한이 한 달).
function _monthChunks(days) {
  const out = [];
  const fmt = (d) => d.toISOString().slice(0, 10).replace(/-/g, "");
  let end = new Date();
  for (let left = days; left > 0; left -= 30) {
    const span = Math.min(30, left) - 1;
    const start = new Date(end.getTime() - span * 86400000);
    out.push([fmt(start), fmt(end)]);
    end = new Date(start.getTime() - 86400000);
  }
  return out;
}
// 페이지 컨텍스트 주입 — same-origin 이라 세션 쿠키가 자동으로 실린다. 외부 스코프 참조 금지.
function eleven11UnconfCrawlInPage(chunks) {
  return (async () => {
    const BASE = "https://soffice.11st.co.kr/remittance/SellerRemittanceAction.tmall";
    const rows = []; const per = []; let failed = 0;
    for (const [st, ed] of chunks) {
      const q = new URLSearchParams({
        method: "getSelAllStatDtlsSoffice", start: "0", limit: "500",
        dtlSearchStlmntType: "N", cnsgnDlvYn: "N", quickStlYn: "N",
        searchType: "ALL", stDate: st, edDate: ed, ordPrdStat: "",
        searchDtType: "STL_DT", dtlSearchType: "", dtlSearchVal: "",
      });
      try {
        const r = await fetch(BASE + "?" + q, { method: "POST", credentials: "include" });
        const t = await r.text();
        // 로그인이 풀리면 HTML 이 온다 → 조용한 0건이 아니라 정직한 실패로 돌린다.
        if (!r.ok || /^\s*</.test(t)) {
          failed++; per.push({ st: st, ed: ed, error: "http " + r.status, needLogin: /login/i.test(t) });
          continue;
        }
        const lst = (JSON.parse(t) || {}).list || [];
        rows.push.apply(rows, lst);
        per.push({ st: st, ed: ed, n: lst.length });
      } catch (e) {
        failed++; per.push({ st: st, ed: ed, error: String((e && e.message) || e) });
      }
    }
    // 한 토막이라도 실패하면 알린다 — 「덜 긁은 합계」를 온전한 값처럼 쓰면 안 된다.
    return { ok: failed === 0, rows: rows, collected: rows.length,
             chunks: per, failedChunks: failed,
             needLogin: per.some((c) => c.needLogin) };
  })();
}

// ── [2026-08-07] 로켓그로스 정산 크롤 ────────────────────────────────────────────
//  창구: GET https://wing.coupang.com/tenants/rfm/v2/settlements/status/api
//  화면: /tenants/rfm/settlements/status-new (「/settlements/home」은 요약이라 이 API 가 안 뜬다)
//  ★ 로그인 세션이 없으면 xauth 로그인 페이지 HTML 이 와서 JSON 파싱이 깨진다 →
//    조용한 0건이 아니라 **정직하게 실패**로 돌려준다(사장님이 로그인하면 다시 누르면 됨).
async function handleCoupangRgSettleCrawl(payload) {
  let tab = (await chrome.tabs.query({ url: "https://wing.coupang.com/*" }))[0];
  let opened = false;
  if (!tab) {
    tab = await chrome.tabs.create({
      url: "https://wing.coupang.com/tenants/rfm/settlements/status-new", active: false });
    opened = true;
    try { await waitTabComplete(tab.id, 30000); } catch (_) {}
  }
  let res;
  try {
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: "MAIN",
      func: coupangRgSettleCrawlInPage, args: [Number(payload.budgetMs) || 60000],
    });
    res = (out && out[0] && out[0].result) || { ok: false, error: "실행 결과 없음" };
  } finally {
    if (opened) { try { await chrome.tabs.remove(tab.id); } catch (_) {} }
  }
  return res;
}
// MAIN world 주입 — wing.coupang.com 페이지 컨텍스트(세션 쿠키)에서 실행. 외부 스코프 참조 금지.
function coupangRgSettleCrawlInPage(budgetMs) {
  return (async () => {
    const t0 = Date.now();
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), Math.max(5000, budgetMs || 60000));
      let r;
      try {
        r = await fetch("/tenants/rfm/v2/settlements/status/api",
                        { credentials: "include", headers: { accept: "application/json" },
                          signal: ctrl.signal });
      } finally { clearTimeout(timer); }
      if (!r.ok) return { ok: false, error: "HTTP " + r.status };
      const ct = r.headers.get("content-type") || "";
      if (ct.indexOf("json") < 0) {
        // 로그인 만료 → xauth HTML. 0건으로 삼키면 「정산이 없다」는 거짓이 된다.
        return { ok: false, error: "로그인 필요(응답이 JSON 이 아님)", needLogin: true };
      }
      const b = await r.json();
      const rows = (b && b.settlementStatusReports) || [];
      // 계정 별칭 — 화면 제목이 "Coupang Wing - 유영빈, 세소" 꼴. 없으면 빈값(서버가 그대로 둠).
      let acc = "";
      try {
        const m = String(document.title || "").split("-").pop();
        acc = (m || "").split(",").pop().trim();
      } catch (_) { acc = ""; }
      return { ok: true, rows: rows, collected: rows.length, account: acc,
               ms: Date.now() - t0 };
    } catch (e) {
      return { ok: false, error: String((e && e.message) || e) };
    }
  })();
}

// ── [2026-07-16] 롯데온 정산 크롤 — 로그인된 store.lotteon.com 세션서 soapi 페이징 수집 → 서버 push ──
function _ymdOffset(days) {
  const d = new Date(); d.setDate(d.getDate() + days);
  return "" + d.getFullYear() + String(d.getMonth() + 1).padStart(2, "0") + String(d.getDate()).padStart(2, "0");
}
async function handleLotteonSettleCrawl(payload, base) {
  const since = (payload.since || "").replace(/-/g, "") || _ymdOffset(-60);
  const until = (payload.until || "").replace(/-/g, "") || _ymdOffset(0);
  const trNo = payload.trNo || "";   // 판매자ID(예 LO10161082). 없으면 페이지 캡처값 시도.
  // 1) 로그인된 store.lotteon.com 탭 확보(없으면 임시로 열고 크롤 후 닫음 — 쿠키 공유로 로그인됨)
  let tab = (await chrome.tabs.query({ url: "https://store.lotteon.com/*" }))[0];
  let opened = false;
  if (!tab) {
    tab = await chrome.tabs.create({ url: "https://store.lotteon.com/cm/main/index_SO.wsp", active: false });
    opened = true;
    try { await waitTabComplete(tab.id, 25000); } catch (_) {}
  }
  // 2) MAIN world 크롤(세션 토큰 읽어 selectBgt 페이징)
  let res;
  try {
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: "MAIN",
      func: lotteonSettleCrawlInPage, args: [since, until, trNo],
    });
    res = (out && out[0] && out[0].result) || { ok: false, error: "실행 결과 없음" };
  } finally {
    if (opened) { try { await chrome.tabs.remove(tab.id); } catch (_) {} }
  }
  if (!res.ok) return res;
  // 2-b) 같은 세션·같은 탭에서 주문(통합주문조회)도 수집(부가 — 실패해도 정산은 살린다).
  let ores2 = null;
  try {
    const out2 = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: "MAIN",
      func: lotteonOrdersCrawlInPage, args: [since, until, res.trNo || trNo],
    });
    ores2 = (out2 && out2[0] && out2[0].result) || null;
  } catch (_) { ores2 = null; }
  const orderRows2 = (ores2 && ores2.ok && ores2.rows) ? ores2.rows : [];
  // 3) 서버 push 는 페이지가 한다(SW fetch 는 mou-m 인증 쿠키 미전송 → upserted 0). rows 를
  //    호출 페이지(mou-m, 인증됨)로 돌려주고 페이지가 POST /api/margin/lotteon-settlement
  //    + POST /api/orders-ingest/lotteon-so-upsert.
  return { ok: true, rows: res.rows, collected: res.rows.length, lines: res.lines, total: res.total,
           trNo: res.trNo, orderRows: orderRows2, orderCollected: orderRows2.length };
}
// MAIN world 주입 — 페이지 컨텍스트(store.lotteon.com origin·세션쿠키)서 실행. 외부 스코프 참조 금지.
// ★[2026-08-06] budgetMs — 페이지 안 수집 루프에도 상한을 준다.
//   XHR 은 기본 타임아웃이 없어 롯데온 API 가 한 번 물리면 **영영** 안 끝난다.
//   그 한 페이지가 회차 전체를 붙잡아 30분 감시로만 빠져나왔다. 요청마다 30초,
//   루프 전체는 부르는 쪽이 준 예산까지만 — 넘으면 조용히 반쪽을 주지 않고 정직하게 실패한다.
function lotteonSettleCrawlInPage(sinceYMD, untilYMD, trNoArg, budgetMs) {
  return new Promise(function (resolve) {
    (async function () {
      var _t0 = Date.now(), _budget = budgetMs || 240000;
      try {
        var tok = null, hex = /[0-9a-f]{56}/;
        for (var i = 0; i < sessionStorage.length; i++) {
          var v = "" + (sessionStorage.getItem(sessionStorage.key(i)) || "");
          var m = v.match(hex); if (m) { tok = m[0]; break; }
        }
        if (!tok) return resolve({ ok: false, error: "세션 토큰 없음 — 판매자센터 로그인 후 재시도" });
        // trNo(판매자ID) — 지정 없으면 로그인된 판매자센터 DOM에서 자동감지
        //   #mf_sellerShop_trNo(브랜드박스 옆 판매자코드) → 없으면 본문 LO######## 정규식.
        var trNo = trNoArg || (window.__H && window.__H.trNo) || "";
        if (!trNo) {
          try {
            var elT = document.getElementById("mf_sellerShop_trNo");
            if (elT) trNo = (elT.textContent || "").trim();
          } catch (e) {}
        }
        if (!trNo) {
          try { var mm = (document.body.innerText || "").match(/LO\d{8,}/); if (mm) trNo = mm[0]; } catch (e) {}
        }
        if (!trNo) return resolve({ ok: false, error: "trNo(판매자ID) 자동감지 실패 — 판매자센터 로그인 확인 or payload로 지정" });
        function get(p) {
          return new Promise(function (res) {
            var x = new XMLHttpRequest();
            var qs = "strtDttm=" + sinceYMD + "&endDttm=" + untilYMD + "&trNo=" + encodeURIComponent(trNo) +
                     "&lrtrNo=&inqDvsCd=&odSearchTypCd=01&odSearchTypNm=&pageNo=" + p + "&rowsPerPage=30";
            x.open("GET", "https://soapi.lotteon.com/settle/v1/so/mediationSettleManagement/selectBgtSettleManagementList?" + qs);
            x.setRequestHeader("authorization", "Bearer " + tok);
            x.setRequestHeader("x-timezone", "GMT+09:00");
            x.setRequestHeader("accept", "application/json");
            x.withCredentials = true;
            x.timeout = 30000;   // ★기본값 0(무한) — 한 번 물리면 회차가 통째로 멈춘다
            x.onload = function () { res({ s: x.status, t: x.responseText }); };
            x.onerror = function () { res({ s: 0, t: "neterr" }); };
            x.ontimeout = function () { res({ s: 0, t: "timeout" }); };
            x.send();
          });
        }
        var agg = {}, page = 1, total = null, lines = 0;
        while (page <= 400) {
          if (Date.now() - _t0 > _budget) {
            return resolve({ ok: false, trNo: trNo,
              error: "정산 수집이 " + Math.round(_budget / 1000) + "초를 넘김(" + page + "쪽까지) — 롯데온 응답 지연" });
          }
          var r = await get(page);
          if (r.s !== 200) return resolve({ ok: false, error: "HTTP " + r.s + (r.t === "timeout" ? "(30초 무응답)" : "") + " @page" + page, trNo: trNo });
          var j = JSON.parse(r.t);
          var d = (j && j.data) ? j.data : j;
          var list = (d && d.mediationSettleList && d.mediationSettleList.dataList) || (d && d.dataList) || [];
          if (total === null) total = (d && d.mediationSettleList && d.mediationSettleList.totalCount) || (d && d.totalCount) || null;
          for (var k = 0; k < list.length; k++) {
            var it = list[k], od = ("" + (it.odNo || "")).trim();
            if (!od) continue;                 // ★요약행(빈 odNo) 제외
            var seq = "" + (it.odSeq || "1"), key = od + "|" + seq;
            if (!agg[key]) agg[key] = { odNo: od, odSeq: seq, pymtTgtAmt: 0, slChNo: it.slChNo || null, trNo: it.trNo || trNo };
            agg[key].pymtTgtAmt += Math.round(parseFloat(it.pymtTgtAmt || 0));   // procSeq +X/-X 순액
            lines++;
          }
          if (list.length < 30) break;
          page++;
        }
        resolve({ ok: true, rows: Object.keys(agg).map(function (k) { return agg[k]; }), total: total, lines: lines, trNo: trNo });
      } catch (e) { resolve({ ok: false, error: String(e) }); }
    })();
  });
}

// ── [2026-07-23] 롯데온 주문 크롤(통합주문조회) — 정산 크롤과 같은 세션·같은 패턴 ──
async function handleLotteonOrdersCrawl(payload, base) {
  const since = (payload.since || "").replace(/-/g, "") || _ymdOffset(-14);
  const until = (payload.until || "").replace(/-/g, "") || _ymdOffset(0);
  const trNo = payload.trNo || "";
  let tab = (await chrome.tabs.query({ url: "https://store.lotteon.com/*" }))[0];
  let opened = false;
  if (!tab) {
    tab = await chrome.tabs.create({ url: "https://store.lotteon.com/cm/main/index_SO.wsp", active: false });
    opened = true;
    try { await waitTabComplete(tab.id, 25000); } catch (_) {}
  }
  let res;
  try {
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: "MAIN",
      func: lotteonOrdersCrawlInPage, args: [since, until, trNo],
    });
    res = (out && out[0] && out[0].result) || { ok: false, error: "실행 결과 없음" };
  } finally {
    if (opened) { try { await chrome.tabs.remove(tab.id); } catch (_) {} }
  }
  if (!res.ok) return res;
  // 서버 push 는 호출 페이지(mou-m, 인증 쿠키 보유)가 한다 — 정산 크롤과 동일 규약.
  return { ok: true, rows: res.rows, collected: res.rows.length, total: res.total, trNo: res.trNo };
}
// MAIN world 주입 — store.lotteon.com origin·세션쿠키에서 실행. 외부 스코프 참조 금지.
//  엔드포인트·필드 = 2026-07-23 라이브 실측(통합주문조회 「조회」 버튼이 부르는 그 API).
function lotteonOrdersCrawlInPage(sinceYMD, untilYMD, trNoArg, budgetMs) {
  return new Promise(function (resolve) {
    (async function () {
      var _t0 = Date.now(), _budget = budgetMs || 240000;
      try {
        var tok = null, hex = /[0-9a-f]{56}/;
        for (var i = 0; i < sessionStorage.length; i++) {
          var v = "" + (sessionStorage.getItem(sessionStorage.key(i)) || "");
          var m = v.match(hex); if (m) { tok = m[0]; break; }
        }
        if (!tok) return resolve({ ok: false, error: "세션 토큰 없음 — 판매자센터 로그인 후 재시도" });
        var trNo = trNoArg || "";
        if (!trNo) {
          try { var mm = (document.body.innerText || "").match(/LO\d{8,}/); if (mm) trNo = mm[0]; } catch (e) {}
        }
        if (!trNo) return resolve({ ok: false, error: "trNo(판매자ID) 자동감지 실패" });
        function post(page) {
          return new Promise(function (res) {
            var body = {
              chDtlNo: "", chNo: "", chkEcpnNo: "", chkOdNo: "", ctrtTypCd: "", dlvTyp: "",
              dlvTypDtl: "", dvRsvDvsCd: "", dvRtrvDvsCd: "", ecpnNo: "", excpProcDvs: "",
              fprdDvYn: "", infwMdiaCd: "", infwRte: "", lrtrNo: "", mvMosAccpStatCd: "",
              noVal: "", odMbDvsCd: "ODID", odMbDvsDtl: "", odNo: "", odPrgsStatCd: "",
              odSlTypCd: "", odTypCd: "", pageNo: page, pdDpStdCd: "", pdNo: "", pdOdTypCd: "",
              pdTypCd: "", pdTypDtlCd: "", prdDvsCd: "OD", prdStrtDt: sinceYMD, prdEndDt: untilYMD,
              purCfrmDvsCd: "", rowsPerPage: "100", selNo: "", stdCatId: "", thdyPdYn: "",
              trGrpCd: "", trNo: trNo
            };
            var x = new XMLHttpRequest();
            x.open("POST", "https://soapi.lotteon.com/soapi/v1/order/orderInquiry/getOrderList");
            x.setRequestHeader("authorization", "Bearer " + tok);
            x.setRequestHeader("content-type", "application/json");
            x.setRequestHeader("x-timezone", "GMT+09:00");
            x.setRequestHeader("accept", "application/json");
            x.withCredentials = true;
            x.timeout = 30000;   // ★정산 쪽과 같은 이유 — 무한 대기 금지
            x.onload = function () { res({ s: x.status, t: x.responseText }); };
            x.onerror = function () { res({ s: 0, t: "neterr" }); };
            x.ontimeout = function () { res({ s: 0, t: "timeout" }); };
            x.send(JSON.stringify(body));
          });
        }
        var rows = [], page = 1, total = null;
        while (page <= 200) {
          if (Date.now() - _t0 > _budget) {
            return resolve({ ok: false, trNo: trNo,
              error: "주문 수집이 " + Math.round(_budget / 1000) + "초를 넘김(" + page + "쪽까지) — 롯데온 응답 지연" });
          }
          var r = await post(page);
          if (r.s !== 200) return resolve({ ok: false, error: "HTTP " + r.s + (r.t === "timeout" ? "(30초 무응답)" : "") + " @page" + page, trNo: trNo });
          var j = JSON.parse(r.t);
          var list = (j && j.data) || [];
          if (total === null) total = (j && j.dataCount) || null;
          for (var k = 0; k < list.length; k++) {
            var it = list[k];
            var od = ("" + (it.odNo || "")).trim();
            if (!od) continue;
            rows.push({
              od_no: od,
              od_seq: "" + (it.odSeq || "1"),
              proc_seq: "" + (it.procSeq || "1"),   // ★취소 라인 구분(1=원주문·2=취소)
              status: "" + (it.odPrgsStepCdText || it.shtOdStatNm || ""),
              status_code: "" + (it.odPrgsStepCd || ""),
              od_typ: "" + (it.odTypCdText || ""),
              claimed_at: "" + (it.clmCmptDttm || ""),
              ch_no: "" + (it.chNo || ""),
              ordered_at: "" + (it.odAccpDttm || it.odCmptDttm || ""),
              product_name: "" + (it.pdNm || it.spdNm || ""),
              option1: "" + (it.sitmNm || ""),
              qty: "" + (it.odQty || ""),
              unit_price: "" + (it.slPrc || ""),
              paid_amount: "" + (it.odAmt || ""),
              discount: "" + (it.dcAmt || ""),
              ship_fee: "" + (it.aplyDvCst || ""),
              buyer: "" + (it.odNm || ""),
              recipient: "" + (it.dvpCustNm || ""),
              phone: "" + (it.dvpMphnNo || ""),
              buyer_phone: "" + (it.mphnNo || ""),
              zipcode: "" + (it.dvpZipNo || ""),
              address: "" + (it.dplcAddr || ""),
              tr_no: "" + (it.trNo || trNo)
            });
          }
          if (list.length < 100) break;
          page++;
        }
        resolve({ ok: true, rows: rows, total: total, trNo: trNo });
      } catch (e) { resolve({ ok: false, error: String(e) }); }
    })();
  });
}

// ── [2026-07-16] 롯데온 방식A 자동 로그인 ──
//   저장 자격증명(login_id/password)으로 판매자센터 로그인폼을 자동입력·제출한다.
//   본인인증(새 기기·가끔)이 뜨면 needs_verify=true 로 멈춰 사용자가 직접 처리하게 한다.
const _LO_LOGIN_URL = "https://store.lotteon.com/cm/main/login_SO.wsp";
const _LO_HOME_URL = "https://store.lotteon.com/cm/main/index_SO.wsp";
let _loTabId = null;   // 전용 백그라운드 탭(전체 자동 순회 내내 재사용 — 사용자 다른 탭 안 건드림)
function _sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

// ★탭이 닫히면 즉시 잊는다 — 안 그러면 죽은 탭 번호로 계속 호출해
//   'No tab with id' 오류가 확장 「오류」 목록에 쌓인다(2026-07-17 사용자 화면 실제 발생).
chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === _loTabId) _loTabId = null;
  if (tabId === _serviceTabId) { _serviceTabId = null; _serviceTabOwned = false; }
});

// 전용 탭 확보(없거나 닫혔으면 생성). active:false 백그라운드.
// ★[2026-08-06] 이 탭을 **재우기 금지**로 못 박는다(autoDiscardable=false).
//   크롬 메모리 세이버가 이 백그라운드 탭을 재우면(discard) executeScript 가 **영구 대기**한다
//   — 서비스 탭엔 2026-06-22 에 같은 이유로 이미 핀을 박아 뒀는데(_pinTab), 정작 롯데온
//   전용 탭엔 없었다. 그래서 회차가 한 계정에서 통째로 멈추고(→30분 강제 중단),
//   재워졌다 깨어난 계정은 로그인 세션을 잃어 「로그아웃 실패·로그인 실패」로 떨어졌다
//   (2026-08-06 실측: 자동 회차마다 실패 2~3계정인데 같은 계정을 손으로 돌리면 정상 —
//    손으로 돌릴 땐 회차가 짧고 브라우저를 쓰는 중이라 탭이 재워지지 않는다).
//   이미 재워진 탭은 reload 로 깨워서 쓴다(롯데온 세션 쿠키는 남아 있어 로그인은 유지된다).
async function _loGetDedicatedTab() {
  if (_loTabId != null) {
    try {
      let t = await chrome.tabs.get(_loTabId);
      if (t) {
        _pinTab(_loTabId);                       // 핀은 매번 다시 박는다(탭 교체·크롬 재시작 대비)
        if (t.discarded) {
          try { await chrome.tabs.reload(_loTabId); await waitTabComplete(_loTabId, 25000); } catch (_) {}
          try { t = await chrome.tabs.get(_loTabId); } catch (_) {}
        }
        return t;
      }
    } catch (_) { _loTabId = null; }
  }
  const t = await chrome.tabs.create({ url: _LO_LOGIN_URL, active: false });
  _loTabId = t.id;
  _pinTab(t.id);
  try { await waitTabComplete(t.id, 25000); } catch (_) {}
  return t;
}
// 잠든 탭을 깨운다 — 주입 직전에 부른다(주입이 영구 대기하는 유일한 원인).
async function _loWakeTab(tabId) {
  try {
    const t = await chrome.tabs.get(tabId);
    if (!t) return false;
    if (!t.discarded) return true;
    await chrome.tabs.reload(tabId);
    await waitTabComplete(tabId, 25000);
    return true;
  } catch (_) { return false; }
}

// SW 백업 로그아웃 — chrome.cookies 로 lotteon 쿠키 제거(document.cookie 로 못 지우는 httpOnly 대비).
async function clearLotteonCookiesGlobal() {
  let n = 0;
  try {
    const list = await chrome.cookies.getAll({ domain: "lotteon.com" });
    for (const c of list) {
      const host = c.domain.replace(/^\./, "");
      for (const proto of ["https://", "http://"]) {
        try { await chrome.cookies.remove({ url: proto + host + (c.path || "/"), name: c.name }); n++; } catch (_) {}
      }
    }
  } catch (_) {}
  return n;
}

// ── [2026-07-16] 롯데온 계정 1건 완전 자동 — 전용 탭서 로그아웃→로그인→정산수집 ──
async function handleLotteonAccountCollect(payload) {
  const loginId = payload.login_id || payload.loginId || "";
  const password = payload.password || "";
  if (!loginId || !password) return { ok: false, error: "자격증명 없음(login_id/password 필요)" };
  const sinceYMD = (payload.since || "").replace(/-/g, "") || _ymdOffset(-60);
  const untilYMD = (payload.until || "").replace(/-/g, "") || _ymdOffset(0);
  const loginOnly = !!payload.login_only;   // 「🔑 로그인 테스트」 — 수집 없이 로그인만 확인

  // ★계정당 예산(240s) — 페이지 상한(300s) 안쪽에서 스스로 끝내고 '어느 단계'였는지 보고한다.
  //   예산이 없으면 대기가 누적돼 페이지가 먼저 죽고, 원인이 '확장 응답 시간초과' 한 줄로 뭉개져
  //   자격증명 문제인지 속도 문제인지 구분이 안 된다(2026-07-17 실측 — 이 때문에 오진했다).
  const deadline = Date.now() + 240000;
  const left = () => deadline - Date.now();
  const cap = (ms) => Math.max(1000, Math.min(ms, left()));
  let step = "탭 준비";
  const over = () => ({ ok: false, timeout: true, step: step, error: "시간초과 — '" + step + "' 단계에서 4분 초과" });

  const tab = await _loGetDedicatedTab();
  // 1) ★공식 로그아웃(신뢰기기 유지 → 재로그인 2단계 안 뜸) — 실검증 확정 레시피.
  //   쿠키클리어 로그아웃은 신뢰기기까지 지워 2단계 재발 → 폐기. 대신 홈으로 가서 로그인 상태면
  //   WebSquare 로그아웃 버튼 핸들러를 컴포넌트.trigger('onclick')로 발화 + 확인 모달 클릭.
  step = "이전 계정 로그아웃";
  try { await chrome.tabs.update(tab.id, { url: _LO_HOME_URL }); await waitTabComplete(tab.id, cap(25000)); } catch (_) {}
  await _sleep(1000);
  if (left() <= 0) return over();
  let st = await _loInject(tab.id, lotteonCheckStateInPage, []);
  if (st && st.loggedIn) {
    // 로그아웃은 페이지를 이동시켜 프레임을 잃을 수 있다(정상) — 에러 무시.
    try { await _loInject(tab.id, lotteonOfficialLogoutInPage, []); } catch (_) {}
    // ★'로그아웃 될 때까지' 확인한다 — waitTabComplete 로 기다리면 안 된다.
    //   그 시점 탭은 이미 status=complete(홈이 떠 있는 상태)라 0초에 반환하고, 실질 대기가
    //   sleep 1.5초뿐이 된다. 롯데온 로그아웃(확인 모달→네비게이션)이 그보다 늦으면 로그인된
    //   채로 다음 단계에 가서 '이전 계정 로그아웃 실패(세션 유지)'가 난다(2026-07-17 라이브 실측
    //   — 계정1 성공 직후 계정2에서 재현). 최대 ~13초 폴링 + 중간 1회 재발화.
    for (let i = 0; i < 14; i++) {
      await _sleep(900);
      if (left() <= 0) return over();
      let s2 = null;
      try { s2 = await _loInject(tab.id, lotteonCheckStateInPage, [], { tries: 1 }); } catch (_) { continue; }
      if (s2 && !s2.loggedIn) break;                       // 로그아웃 확인됨
      if (i === 6) {                                        // 확인 모달을 놓친 경우 한 번 더 발화
        try { await _loInject(tab.id, lotteonOfficialLogoutInPage, []); } catch (_) {}
      }
    }
  }
  // 2) 로그인 페이지 확보 후 상태 확인
  step = "로그인 페이지 열기";
  if (left() <= 0) return over();
  try { await chrome.tabs.update(tab.id, { url: _LO_LOGIN_URL }); await waitTabComplete(tab.id, cap(25000)); } catch (_) {}
  await _sleep(900);
  st = await _loInject(tab.id, lotteonCheckStateInPage, []);
  if (st && st.loggedIn) return { ok: false, step: step, error: "이전 계정 로그아웃 실패(세션 유지)", trNo: st.trNo };
  if (!st || !st.hasForm) return { ok: false, step: step, error: "로그인 폼을 찾지 못함(페이지 구조 변경?)" };
  // 3) 폼 자동입력 + 제출
  step = "로그인";
  const fr = await _loInject(tab.id, lotteonFillLoginInPage, [loginId, password]);
  if (!fr || !fr.submitted) return { ok: false, step: step, error: (fr && fr.error) || "로그인 제출 실패" };
  try { await waitTabComplete(tab.id, cap(25000)); } catch (_) {}
  // ★로그인 완료를 폴링(WebSquare 비동기 로그인 — 단일 체크는 너무 이르다. 실검증: 로그인은
  //   성공하는데 1.8초 체크가 폼을 봐 '실패' 오인). 최대 ~20초 대기.
  //   tries:1 — 루프가 곧 다시 물어보므로 여기서 재시도하면 대기만 16배로 불어난다.
  let logged = null;
  for (let i = 0; i < 16; i++) {
    await _sleep(1200);
    if (left() <= 0) return over();
    try { st = await _loInject(tab.id, lotteonCheckStateInPage, [], { tries: 1 }); } catch (_) { continue; }
    if (st && st.needsVerify) return { ok: false, needs_verify: true, step: step, error: "본인인증 필요(새 기기·가끔) — 직접 인증 후 재시도" };
    if (st && st.loggedIn) { logged = st; break; }
  }
  if (!logged) return { ok: false, step: step, error: "로그인 실패 — 아이디·비밀번호를 확인하세요(20초 안에 로그인 안 됨)" };
  if (loginOnly) return { ok: true, login_only: true, collected: 0, rows: [], trNo: logged.trNo || "" };
  // 4) 같은 탭서 정산 수집(검출된 trNo 전달 — 헤더 렌더 지연 대비)
  step = "정산 수집";
  if (left() <= 0) return over();
  // ★[2026-08-06] 여기부터 예산이 새고 있었다 — 수집 주입엔 상한이 없어, 앞 단계에서
  //   240초를 재 놓고도 이 한 줄이 몇 분이고 매달렸다(회차가 30분 감시에 걸린 진짜 자리).
  //   남은 예산의 2/3 를 정산에, 나머지를 주문에 준다(주문은 부가 수집이라 뒤에 선다).
  const _settleBudget = Math.max(20000, Math.round(left() * 0.66));
  const res = await _loInject(tab.id, lotteonSettleCrawlInPage,
    [sinceYMD, untilYMD, logged.trNo || "", _settleBudget], { tries: 1, timeoutMs: _settleBudget + 20000 });
  if (!res || !res.ok) return { ok: false, step: step, error: (res && res.error) || "정산 수집 실패", trNo: logged.trNo };
  // 5) 같은 로그인 세션에서 주문(통합주문조회)도 수집 — OpenAPI 가 못 주는 취소 라인·
  //    취소건 구매자·철회 취소 신호의 유일 원천(2026-07-23 실측). ★SO API 는 로그인한
  //    그 계정 주문만 주므로 계정 순회인 이 자리가 유일한 전 계정 커버 지점이다.
  //    주문 수집 실패는 정산 결과를 죽이지 않는다(부가 — orderRows 만 빈 채로 반환).
  let ores = null;
  try {
    const _ordBudget = Math.max(15000, left() - 10000);   // 남은 예산 전부(정리 여유 10초만 남김)
    ores = await _loInject(tab.id, lotteonOrdersCrawlInPage,
      [sinceYMD, untilYMD, logged.trNo || "", _ordBudget], { tries: 1, timeoutMs: _ordBudget + 20000 });
  } catch (_) { ores = null; }
  const orderRows = (ores && ores.ok && ores.rows) ? ores.rows : [];
  return { ok: true, rows: res.rows, collected: res.rows.length, lines: res.lines, total: res.total,
           trNo: res.trNo || logged.trNo,
           orderRows: orderRows, orderCollected: orderRows.length,
           orderError: (ores && !ores.ok) ? (ores.error || "주문 수집 실패") : "" };
}

// MAIN world — ★공식 로그아웃(신뢰기기 유지). WebSquare 로그아웃버튼 핸들러를 컴포넌트.trigger로
//   발화 → "로그아웃 하시겠습니까?" 확인 모달의 「확인」 클릭 → 공식 로그아웃(login_SO.wsp).
//   실검증(2026-07-17): 이 방식은 세션만 끊고 2단계 신뢰기기 쿠키는 유지 → 재로그인 2단계 안 뜸.
function lotteonOfficialLogoutInPage() {
  return new Promise(function (resolve) {
    (async function () {
      try {
        window.confirm = function () { return true; };
        window.alert = function () {};
        if (document.getElementById("mf_loginUserId")) return resolve({ ok: true, already: true });
        var comp = window.mf_btnLogout;
        if (!comp || typeof comp.trigger !== "function") return resolve({ ok: false, error: "로그아웃 컴포넌트 없음" });
        try { comp.trigger("onclick"); } catch (e) { try { comp.trigger("click"); } catch (e2) {} }
        for (var i = 0; i < 12; i++) {
          await new Promise(function (r) { setTimeout(r, 500); });
          if (document.getElementById("mf_loginUserId") || /login_SO/.test(location.href)) return resolve({ ok: true });
          var cands = Array.prototype.slice.call(document.querySelectorAll("a,button,input"));
          for (var j = 0; j < cands.length; j++) {
            var t = (cands[j].textContent || cands[j].value || "").trim();
            if (t === "확인" && cands[j].offsetParent !== null) { cands[j].click(); break; }
          }
        }
        resolve({ ok: true });
      } catch (e) { resolve({ ok: false, error: String(e) }); }
    })();
  });
}

// MAIN world — 이 문서에서 접근 가능한 쿠키 전부 만료(EC_BO_AUTH_CODE 등 세션쿠키 = 비 httpOnly, 실검증).
function lotteonClearCookiesInPage() {
  try {
    var names = document.cookie.split(";").map(function (c) { return c.trim().split("=")[0]; }).filter(Boolean);
    var doms = ["", ".lotteon.com", "store.lotteon.com", ".store.lotteon.com"];
    names.forEach(function (n) {
      doms.forEach(function (d) {
        document.cookie = n + "=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/" + (d ? ("; domain=" + d) : "");
      });
    });
    return { cleared: names.length };
  } catch (e) { return { cleared: 0, error: String(e) }; }
}

async function _loEnsureTab(url) {
  let tab = (await chrome.tabs.query({ url: "https://store.lotteon.com/*" }))[0];
  if (!tab) {
    tab = await chrome.tabs.create({ url: url, active: false });
    try { await waitTabComplete(tab.id, 25000); } catch (_) {}
  }
  return tab;
}
// ★[2026-08-06] 주입 1회 하드 타임아웃 — 없으면 **영구 대기**가 가능했다.
//   잠든(discard) 탭·먹통 페이지에 executeScript 를 걸면 크롬은 영영 답을 안 준다.
//   그 한 줄이 회차 전체를 붙잡아 30분 감시가 유일한 탈출구였다(=회차 통째 손실).
//   상태 확인·폼 입력은 즉답이라 45초면 충분하고, 오래 걸리는 수집 주입은 부르는 쪽이
//   timeoutMs 로 남은 예산을 실어 준다.
const LO_INJECT_TIMEOUT_MS = 45000;
async function _loInject(tabId, fn, args, opts) {
  // ★네비게이션 중 프레임 제거("Frame with ID 0 was removed") 등 일시오류는 잠깐 뒤 재시도.
  //   공식 로그아웃·로그인 제출이 페이지를 이동시켜 executeScript 가 프레임을 잃는 레이스 대응.
  // ★이미 반복 중인 폴 루프에서는 tries:1 로 부를 것 — 루프가 곧 다시 묻는데 여기서도 재시도하면
  //   대기가 곱해져 계정 예산을 통째로 먹는다(2026-07-17 '확장 응답 시간초과'의 실제 원인).
  const tries = (opts && opts.tries) || 4;
  // 하한은 「0·음수로 즉시 포기」만 막는 안전핀 — 요청한 상한을 크게 부풀리면
  // 부르는 쪽이 잰 예산이 조용히 무시된다(상한을 둔 의미가 없어진다).
  const ms = Math.max(1000, (opts && opts.timeoutMs) || LO_INJECT_TIMEOUT_MS);
  let lastErr = null;
  for (let attempt = 0; attempt < tries; attempt++) {
    try {
      await _loWakeTab(tabId);      // 잠들었으면 깨우고 들어간다(영구 대기의 유일한 원인)
      const res = await withTimeout(chrome.scripting.executeScript({
        target: { tabId: tabId }, world: "MAIN", func: fn, args: args || [],
      }), ms);
      // withTimeout 은 거절을 던지지 않고 __error 로 바꿔 준다 — 아래 재시도 판정이
      // 예전처럼 예외로 흐르게 도로 던진다(동작 보존).
      if (res && res.__timeout) throw new Error("주입 응답 없음(" + Math.round(ms / 1000) + "초) — 탭이 잠들었거나 먹통");
      if (res && res.__error) throw new Error(res.__error);
      return (res && res[0] && res[0].result) || null;
    } catch (e) {
      lastErr = e;
      // ★대기를 짧게 — 15초×4 는 계정당 240초 상한을 넘겨 '확장 응답 시간초과'를 유발했다.
      if (/Frame|removed|No frame|cannot be scripted|being unloaded|No tab with id|주입 응답 없음/i.test(String(e))) {
        // 먹통(무응답)일 때만 새로 그린다 — 프레임 교체는 정상 네비게이션이라
        // 여기서 reload 하면 진행 중인 로그인 이동을 되레 끊는다.
        if (/주입 응답 없음/.test(String(e))) { try { await chrome.tabs.reload(tabId); } catch (_) {} }
        try { await waitTabComplete(tabId, 4000); } catch (_) {}
        await _sleep(500);
        continue;
      }
      throw e;
    }
  }
  throw lastErr;
}

async function handleLotteonAutoLogin(payload) {
  const loginId = payload.login_id || payload.loginId || "";
  const password = payload.password || "";
  if (!loginId || !password) return { ok: false, error: "자격증명 없음(login_id/password 필요)" };
  const tab = await _loEnsureTab(_LO_LOGIN_URL);
  // 1) ★항상 로그인 페이지로 새로 이동 후 판정 — 스테일 DOM·백그라운드 로그인탭 오판 방지.
  //    세션이 살아있으면 롯데온이 login→index 로 리다이렉트하므로 checkState 가 loggedIn 을 잡는다.
  try { await chrome.tabs.update(tab.id, { url: _LO_LOGIN_URL }); } catch (_) {}   // 탭이 사라졌을 수 있음
  try { await waitTabComplete(tab.id, 25000); } catch (_) {}
  await new Promise((r) => setTimeout(r, 900));
  let st = await _loInject(tab.id, lotteonCheckStateInPage, []);
  if (st && st.loggedIn) return { ok: true, already: true, trNo: st.trNo || null };
  if (!st || !st.hasForm) return { ok: false, error: "로그인 폼을 찾지 못함(페이지 구조 변경?)" };
  // 2) 폼 자동입력 + 제출
  const fr = await _loInject(tab.id, lotteonFillLoginInPage, [loginId, password]);
  if (!fr || !fr.submitted) return { ok: false, error: (fr && fr.error) || "로그인 제출 실패(버튼 못 찾음)" };
  // 4) 제출 후 네비게이션 대기 → 상태 재확인
  try { await waitTabComplete(tab.id, 25000); } catch (_) {}
  await new Promise((r) => setTimeout(r, 1500));   // WebSquare 렌더 여유
  st = await _loInject(tab.id, lotteonCheckStateInPage, []);
  if (st && st.needsVerify) return { ok: false, needs_verify: true, error: "본인인증 필요(새 기기·가끔) — 직접 인증 후 재시도" };
  if (st && st.loggedIn) return { ok: true, trNo: st.trNo || null };
  if (st && st.hasForm) return { ok: false, error: "로그인 실패(아이디/비번 확인) — 폼 그대로" };
  return { ok: false, error: "로그인 결과 불명(상태 미확정)" };
}

async function handleLotteonLogout() {
  // ★확실한 로그아웃 = 롯데온 세션 쿠키 클리어(판매자센터 로그아웃 버튼은 WebSquare 내부이벤트라
  //   DOM 조작으로 안 터진다). 쿠키 기반 세션이라 쿠키 제거 → 다음 요청 미인증 → 로그아웃.
  let cleared = 0;
  try {
    const domains = ["lotteon.com", ".lotteon.com", "store.lotteon.com", "soapi.lotteon.com"];
    const seen = new Set();
    for (const d of domains) {
      let list = [];
      try { list = await chrome.cookies.getAll({ domain: d }); } catch (_) {}
      for (const c of list) {
        const host = c.domain.replace(/^\./, "");
        const url = (c.secure ? "https://" : "http://") + host + (c.path || "/");
        const key = url + "|" + c.name;
        if (seen.has(key)) continue;
        seen.add(key);
        try { await chrome.cookies.remove({ url: url, name: c.name }); cleared++; } catch (_) {}
      }
    }
  } catch (e) { return { ok: false, error: "쿠키 클리어 실패: " + String(e) }; }
  // 열린 탭이 있으면 로그인 페이지로 이동(세션 무효 반영)
  const tab = (await chrome.tabs.query({ url: "https://store.lotteon.com/*" }))[0];
  if (tab) {
    try { await chrome.tabs.update(tab.id, { url: _LO_LOGIN_URL }); await waitTabComplete(tab.id, 20000); } catch (_) {}
    await new Promise((res) => setTimeout(res, 800));
    const st = await _loInject(tab.id, lotteonCheckStateInPage, []);
    return { ok: true, cleared: cleared, loggedOut: !!(st && !st.loggedIn) };
  }
  return { ok: true, cleared: cleared, loggedOut: true };
}

// MAIN world — 로그인 상태 판정. 외부 스코프 참조 금지.
function lotteonCheckStateInPage() {
  try {
    // ★로그인 후 안내 팝업 자동 처리 — 자동로그인이 여기서 막히지 않게.
    //   "비밀번호 필수 변경(2일 남음)" 팝업=「취소」, 공지 팝업=「창닫기/오늘 하루 보지 않기」.
    try {
      var pbody = (document.body && document.body.innerText) || "";
      var clickByText = function (labels) {
        var cs = Array.prototype.slice.call(document.querySelectorAll("a,button,input"));
        for (var ci = 0; ci < cs.length; ci++) {
          var t = (cs[ci].textContent || cs[ci].value || "").trim();
          if (labels.indexOf(t) >= 0 && cs[ci].offsetParent !== null) { try { cs[ci].click(); } catch (e) {} return true; }
        }
        return false;
      };
      if (/비밀번호 필수 변경|비밀번호를 변경하시겠습니까|비밀번호 변경 안내|변경일이 .* 남았습니다/.test(pbody)) {
        clickByText(["취소", "다음에", "나중에 변경", "나중에"]);
      }
      if (/중요 공지사항|모두 확인하셨나요/.test(pbody)) {
        clickByText(["창닫기", "오늘 하루 보지 않기", "닫기"]);
      }
    } catch (e) {}
    var trEl = document.getElementById("mf_sellerShop_trNo");
    var trNo = trEl ? (trEl.textContent || "").trim() : "";
    var idI = document.getElementById("mf_loginUserId");
    var pwI = document.getElementById("mf_sct_passwd");
    var hasForm = !!(idI && pwI && idI.offsetParent !== null && pwI.offsetParent !== null);
    // 세션 토큰(56 hex) 존재 여부
    var hasTok = false, hex = /[0-9a-f]{56}/;
    for (var i = 0; i < sessionStorage.length; i++) {
      var v = "" + (sessionStorage.getItem(sessionStorage.key(i)) || "");
      if (hex.test(v)) { hasTok = true; break; }
    }
    var body = (document.body && document.body.innerText) || "";
    // ★2단계 인증(SMS 보안코드) 화면 감지 — 실측 문구 "2단계 인증"·"보안코드"·"인증번호".
    //   자동로그인이 여기서 막히면 needs_verify 로 깔끔히 멈춰 사용자가 직접 인증하게 한다.
    var needsVerify = /2단계 인증|보안코드|본인인증|인증번호|휴대폰 인증|휴대전화 인증|이중 인증|OTP/.test(body) && !hasForm;
    var onLoginPage = /login_SO\.wsp/.test(location.href);
    // 로그인 판정: 판매자코드 노출 or 세션토큰 있고 로그인폼/로그인페이지 아님
    var loggedIn = (!!trNo || hasTok) && !hasForm && !onLoginPage;
    return { loggedIn: loggedIn, hasForm: hasForm, needsVerify: needsVerify, trNo: trNo, url: location.href };
  } catch (e) { return { loggedIn: false, hasForm: false, needsVerify: false, error: String(e) }; }
}

// MAIN world — 로그인 폼 자동입력 + 제출.
function lotteonFillLoginInPage(loginId, password) {
  try {
    var idI = document.getElementById("mf_loginUserId");
    var pwI = document.getElementById("mf_sct_passwd");
    if (!idI || !pwI) return { submitted: false, error: "입력칸 없음" };
    function setVal(el, val) {
      var proto = Object.getPrototypeOf(el);
      var desc = Object.getOwnPropertyDescriptor(proto, "value");
      if (desc && desc.set) desc.set.call(el, val); else el.value = val;
      ["input", "change", "keyup", "blur"].forEach(function (t) {
        el.dispatchEvent(new Event(t, { bubbles: true }));
      });
    }
    idI.focus(); setVal(idI, loginId);
    pwI.focus(); setVal(pwI, password);
    // 로그인 버튼 찾기 — id/onclick/텍스트로. '아이디 찾기'·'비밀번호' 제외.
    var btn = document.getElementById("mf_btn_login") || document.getElementById("btn_login");
    if (!btn) {
      var cands = Array.prototype.slice.call(document.querySelectorAll("a,button,input[type=submit],[onclick]"));
      for (var i = 0; i < cands.length; i++) {
        var t = (cands[i].textContent || cands[i].value || "").trim();
        if (t === "로그인" && cands[i].offsetParent !== null) { btn = cands[i]; break; }
      }
    }
    if (!btn) return { submitted: false, error: "로그인 버튼 못 찾음" };
    btn.click();
    return { submitted: true };
  } catch (e) { return { submitted: false, error: String(e) }; }
}


// ── [스파이크 2026-07-07] 무신사 창없는 재고·가격 probe (서비스워커 직접 fetch) ──
//   목적: musinsaExtractor(탭 컨텍스트)와 동일한 API를 SW에서 호출해 200 되는지 실측.
//   엔진 미배선 — probe.musinsa 메시지로 수동 호출만. 폴백 금지: 실패는 http 코드로 그대로 표면화.
async function probeMusinsaWindowless(goodsId) {
  const t0 = Date.now();
  const base = "https://goods-detail.musinsa.com/api2/goods/" + goodsId;
  const out = { ok: false, goodsId: goodsId, http_options: null, http_inv: null,
                http_price: null, stock_map: null, salePrice: null, error: null };
  function finish() { out.elapsed_ms = Date.now() - t0; return out; }
  try {
    const or = await fetch(base + "/options", { credentials: "include", headers: { Accept: "application/json" } });
    out.http_options = or.status;
    if (!or.ok) { out.error = "options http " + or.status; return finish(); }
    const oj = await or.json();
    const basic = (oj.data || {}).basic || [];
    const valueNos = [];
    basic.forEach((g) => (g.optionValues || g.values || []).forEach((v) => { if (v.no != null) valueNos.push(v.no); }));

    const ir = await fetch(base + "/options/v2/prioritized-inventories", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ optionValueNos: valueNos }),
    });
    out.http_inv = ir.status;
    if (ir.ok) {
      const ij = await ir.json();
      const arr = (ij && ij.data) || [];
      const m = {};
      arr.forEach((x) => { m[x.productVariantId] = x; });
      out.stock_map = m;
    }

    const pr = await fetch(base, { credentials: "include", headers: { Accept: "application/json" } });
    out.http_price = pr.status;
    if (pr.ok) {
      const pj = await pr.json();
      out.salePrice = (((pj.data || {}).goodsPrice) || {}).salePrice != null
        ? pj.data.goodsPrice.salePrice : null;
    }

    out.ok = (out.http_options === 200 && out.http_inv === 200 && out.stock_map != null);
    return finish();
  } catch (e) {
    out.error = String(e && e.message ? e.message : e);
    return finish();
  }
}

// ── 소싱처별 추출 레시피 (페이지 컨텍스트에서 실행될 함수) ──
const EXTRACTORS = { musinsa: musinsaExtractor, lotteon: lotteonExtractor };

async function handleCrawl(payload) {
  const sources = payload.sources || [];
  const results = [];
  for (const s of sources) {
    const base = { source_key: s.source_key, url: s.url };
    try {
      results.push({ ...base, ...(await crawlOne(s)) });
    } catch (e) {
      results.push({ ...base, ok: false, error: String(e && e.message ? e.message : e) });
    }
  }
  return { ok: true, count: results.length, results };
}

async function crawlOne(s) {
  const extractor = EXTRACTORS[s.source_key];
  if (!extractor) return { ok: false, error: "레시피 없음(미구현 소싱처): " + s.source_key };
  // 보이는 새 창으로 열기(focused:false → 사용자 작업 방해 최소화하되 화면엔 보임).
  const win = await chrome.windows.create({ url: s.url, focused: false });
  const tab = win && win.tabs && win.tabs[0];
  if (!tab) { try { await chrome.windows.remove(win.id); } catch (_) {} return { ok: false, error: "창 탭 없음" }; }
  try {
    await waitTabComplete(tab.id, 25000);
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: "ISOLATED", func: extractor,
    });
    return (out && out[0] && out[0].result) || { ok: false, error: "추출 결과 없음" };
  } finally {
    try { await chrome.windows.remove(win.id); } catch (_) {}
  }
}

// ── 비로그인 4개용: 보이는 창에서 렌더 HTML 수집(추출은 서버 /api/sources/parse) ──
async function handleGrabHtml(payload) {
  const url = payload.url;
  if (!url) return { ok: false, error: "url 없음" };
  const win = await chrome.windows.create({ url, focused: false });
  const tab = win && win.tabs && win.tabs[0];
  if (!tab) { try { await chrome.windows.remove(win.id); } catch (_) {} return { ok: false, error: "창 탭 없음" }; }
  try {
    await waitTabComplete(tab.id, 25000);
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: "ISOLATED",
      func: () => document.documentElement.outerHTML,
    });
    const html = out && out[0] && out[0].result;
    return html ? { ok: true, html } : { ok: false, error: "HTML 수집 실패" };
  } finally {
    try { await chrome.windows.remove(win.id); } catch (_) {}
  }
}

// ════════════════════════════════════════════
//  창 재사용 모델 (v0.4.1) — 소싱처 1곳당 창 1개, URL은 그 창에서 순차 이동
// ════════════════════════════════════════════

// openWin — 보이는 빈 창 1개 생성(focused:true, cascade 위치). 첫 탭 id 확보.
async function handleOpenWin(_payload) {
  const k = _winSeq++ % 6;
  const left = 60 + k * 70;
  const top  = 60 + k * 48;
  const win = await chrome.windows.create({
    url: "about:blank", focused: true, type: "normal",
    left, top, width: 1000, height: 760,
  });
  const tab = win && win.tabs && win.tabs[0];
  if (!win || !tab) {
    if (win && win.id != null) { try { await chrome.windows.remove(win.id); } catch (_) {} }
    return { ok: false, error: "창 생성 실패(탭 없음)" };
  }
  return { ok: true, winId: win.id, tabId: tab.id };
}

// ────────────────────────────────────────────────────────────
//  스스(스마트스토어/브랜드스토어) per-SKU 재고 — 로그인 브라우저 전용.
//  R&D(2026-06-14): inline __PRELOADED_STATE__ 엔 SKU별 재고가 없고(상품 합계만),
//  per-SKU 는 n/v2 옵션조합 API 가 준다. 그 API 는 비브라우저(curl/서버)에서 429 WAF →
//  로그인된 이 브라우저(동일출처+쿠키)에서만 200. 그래서 무신사 inventories 처럼
//  확장이 페이지 컨텍스트에서 직접 호출한다.
//  구조 무관 walker: 응답 어디든 (stockQuantity + optionName1/optionName) 를 가진
//  객체 배열을 찾아 "색상||사이즈"→수량 맵 생성. 실패 시 null(현행 유지=둔갑 안 함)+진단.
// ────────────────────────────────────────────────────────────
function naverSkuStockFetch() {
  return (async () => {
    try {
      const html = document.documentElement.outerHTML;
      const m = html.match(/window\.__PRELOADED_STATE__\s*=\s*([\s\S]+?)<\/script>/);
      if (!m) return { err: "no-state" };
      let raw = m[1].trim();
      if (raw.endsWith(";")) raw = raw.slice(0, -1);
      raw = raw.replace(/(?<![\w"])undefined(?![\w"])/g, "null");
      let state;
      try { state = JSON.parse(raw); } catch (e) { return { err: "state-parse" }; }
      // 공통 walker: 객체트리서 (stockQuantity + optionName1/optionName) 배열 찾아 색||사이즈→수량
      function walkFor(root) {
        const map = {}; let combos = 0;
        (function walk(o, d) {
          if (!o || d > 8) return;
          if (Array.isArray(o)) {
            for (const it of o) {
              if (it && typeof it === "object" && "stockQuantity" in it &&
                  (("optionName1" in it) || ("optionName" in it))) {
                const c = (it.optionName1 || "").toString().trim();
                const s = (it.optionName2 || it.optionName || "").toString().trim();
                const q = it.stockQuantity;
                const usable = it.usable !== false && it.sellable !== false && it.useYn !== "N";
                if (typeof q === "number") { map[c + "||" + s] = usable ? q : 0; combos++; }
              } else { walk(it, d + 1); }
            }
          } else if (typeof o === "object") { for (const k in o) walk(o[k], d + 1); }
        })(root, 0);
        return { map, combos };
      }
      // [2026-06-15 fix 스스] ① __PRELOADED_STATE__ 직접 훑기 — 드롭다운(품절임박/품절)을 그리는
      //   소스가 state 안에 있다. API(빈응답 다발) 안 거치고 여기서 잡으면 가장 견고.
      const st = walkFor(state);
      if (st.combos) return { map: st.map, combos: st.combos, via: "state" };
      // ② API 폴백 (state 에 옵션조합 없을 때)
      const A = (state.simpleProductForDetailPage && state.simpleProductForDetailPage.A) || {};
      const ch = A.channel || {};
      const cu = ch.channelUid;
      // [2026-06-15 fix] A.productNo(예 5817455588)를 쓰면 /n/v2/.../products/{productNo} 가
      //   HTTP 204(빈 응답) → resp.ok=true라 resp.json() throw → 조용히 999 폴백(silent fail).
      //   channelProductNo(=A.id, URL의 상품번호 5844147017)를 써야 200 + per-SKU 재고가 온다.
      const pno = A.channelProductNo || A.id;   // ⚠️ A.productNo 는 쓰지 말 것(204)
      if (!cu || !pno) return { err: "no-ids:stCombos0" };
      // [2026-06-22] n/v2 재고 API 는 간헐적으로 200+빈바디(empty-body)를 준다 — 재시도 없으면
      //   그 크롤만 sku_stock=null → 전 옵션 999('있음') 둔갑(좋은 재고 통째 소실). 유효 combos
      //   받으면 즉시 종료(정상 시 1회=영향 0), 못 받으면 0.6s·1.2s 백오프로 최대 3회.
      let _lastErr = "empty";
      for (let attempt = 0; attempt < 3; attempt++) {
        let resp, txt = "";
        try {
          resp = await fetch(`/n/v2/channels/${cu}/products/${pno}`, { credentials: "include", headers: { accept: "application/json" } });
          txt = await resp.text();
        } catch (e) { _lastErr = "fetch-exc:" + String(e).slice(0, 30); }
        if (txt && txt.length >= 2) {
          let j = null; try { j = JSON.parse(txt); } catch (e) { _lastErr = "api-parse:len" + txt.length; }
          if (j) {
            const ap = walkFor(j);
            if (ap.combos) return { map: ap.map, combos: ap.combos, via: "api" + (attempt ? "-r" + attempt : "") };
            _lastErr = "no-combos";
          }
        } else if (resp && !resp.ok) {
          _lastErr = "http-" + resp.status;
        } else {
          _lastErr = "empty-body:" + (txt ? txt.length : 0);
        }
        if (attempt < 2) await new Promise((r) => setTimeout(r, 600 * (attempt + 1)));
      }
      return { err: _lastErr };
    } catch (e) { return { err: String(e).slice(0, 90) }; }
  })();
}

// navGrab — 그 탭을 url 로 이동 → 로드 완료 + 안정화 대기 → outerHTML 반환. (창 안 닫음)
// ────────────────────────────────────────────────────────────
//  스스(스마트스토어/브랜드스토어) per-SKU 재고 — 로그인 브라우저 전용.
//  R&D(2026-06-14): inline __PRELOADED_STATE__ 엔 SKU별 재고가 없고(상품 합계만),
//  per-SKU 는 n/v2 옵션조합 API 가 준다. 그 API 는 비브라우저(curl/서버)에서 429 WAF →
//  로그인된 이 브라우저(동일출처+쿠키)에서만 200. 그래서 무신사 inventories 처럼
//  확장이 페이지 컨텍스트에서 직접 호출한다.
//  구조 무관 walker: 응답 어디든 (stockQuantity + optionName1/optionName) 를 가진
//  객체 배열을 찾아 "색상||사이즈"→수량 맵 생성. 실패 시 null(현행 유지=둔갑 안 함)+진단.
// ────────────────────────────────────────────────────────────
function naverSkuStockFetch() {
  return (async () => {
    try {
      const html = document.documentElement.outerHTML;
      const m = html.match(/window\.__PRELOADED_STATE__\s*=\s*([\s\S]+?)<\/script>/);
      if (!m) return { err: "no-state" };
      let raw = m[1].trim();
      if (raw.endsWith(";")) raw = raw.slice(0, -1);
      raw = raw.replace(/(?<![\w"])undefined(?![\w"])/g, "null");
      let state;
      try { state = JSON.parse(raw); } catch (e) { return { err: "state-parse" }; }
      // 공통 walker: 객체트리서 (stockQuantity + optionName1/optionName) 배열 찾아 색||사이즈→수량
      function walkFor(root) {
        const map = {}; let combos = 0;
        (function walk(o, d) {
          if (!o || d > 8) return;
          if (Array.isArray(o)) {
            for (const it of o) {
              if (it && typeof it === "object" && "stockQuantity" in it &&
                  (("optionName1" in it) || ("optionName" in it))) {
                const c = (it.optionName1 || "").toString().trim();
                const s = (it.optionName2 || it.optionName || "").toString().trim();
                const q = it.stockQuantity;
                const usable = it.usable !== false && it.sellable !== false && it.useYn !== "N";
                if (typeof q === "number") { map[c + "||" + s] = usable ? q : 0; combos++; }
              } else { walk(it, d + 1); }
            }
          } else if (typeof o === "object") { for (const k in o) walk(o[k], d + 1); }
        })(root, 0);
        return { map, combos };
      }
      // [2026-06-15 fix 스스] ① __PRELOADED_STATE__ 직접 훑기 — 드롭다운(품절임박/품절)을 그리는
      //   소스가 state 안에 있다. API(빈응답 다발) 안 거치고 여기서 잡으면 가장 견고.
      const st = walkFor(state);
      if (st.combos) return { map: st.map, combos: st.combos, via: "state" };
      // ② API 폴백 (state 에 옵션조합 없을 때)
      const A = (state.simpleProductForDetailPage && state.simpleProductForDetailPage.A) || {};
      const ch = A.channel || {};
      const cu = ch.channelUid;
      // [2026-06-15 fix] A.productNo(예 5817455588)를 쓰면 /n/v2/.../products/{productNo} 가
      //   HTTP 204(빈 응답) → resp.ok=true라 resp.json() throw → 조용히 999 폴백(silent fail).
      //   channelProductNo(=A.id, URL의 상품번호 5844147017)를 써야 200 + per-SKU 재고가 온다.
      const pno = A.channelProductNo || A.id;   // ⚠️ A.productNo 는 쓰지 말 것(204)
      if (!cu || !pno) return { err: "no-ids:stCombos0" };
      // [2026-06-22] n/v2 재고 API 는 간헐적으로 200+빈바디(empty-body)를 준다 — 재시도 없으면
      //   그 크롤만 sku_stock=null → 전 옵션 999('있음') 둔갑(좋은 재고 통째 소실). 유효 combos
      //   받으면 즉시 종료(정상 시 1회=영향 0), 못 받으면 0.6s·1.2s 백오프로 최대 3회.
      let _lastErr = "empty";
      for (let attempt = 0; attempt < 3; attempt++) {
        let resp, txt = "";
        try {
          resp = await fetch(`/n/v2/channels/${cu}/products/${pno}`, { credentials: "include", headers: { accept: "application/json" } });
          txt = await resp.text();
        } catch (e) { _lastErr = "fetch-exc:" + String(e).slice(0, 30); }
        if (txt && txt.length >= 2) {
          let j = null; try { j = JSON.parse(txt); } catch (e) { _lastErr = "api-parse:len" + txt.length; }
          if (j) {
            const ap = walkFor(j);
            if (ap.combos) return { map: ap.map, combos: ap.combos, via: "api" + (attempt ? "-r" + attempt : "") };
            _lastErr = "no-combos";
          }
        } else if (resp && !resp.ok) {
          _lastErr = "http-" + resp.status;
        } else {
          _lastErr = "empty-body:" + (txt ? txt.length : 0);
        }
        if (attempt < 2) await new Promise((r) => setTimeout(r, 600 * (attempt + 1)));
      }
      return { err: _lastErr };
    } catch (e) { return { err: String(e).slice(0, 90) }; }
  })();
}

async function handleNavGrab(payload) {
  const tabId = payload.tabId, url = payload.url;
  if (!url) return { ok: false, error: "url 없음" };
  // [2026-06-14] SSF: 옵션 재고(품절임박 N·품절)는 '한국 IP' raw HTML 의 JS문자열에만 존재.
  //   - AWS 서버 curl(도쿄 IP) = 품절임박 숫자 없는 버전
  //   - navGrab 렌더본 = JS문자열 optCd 소진 + 옵션리스트 lazy 렌더(콜드 창서 빈 결과)
  //   → 이 브라우저(한국)에서 raw HTML 을 직접 fetch 해 서버 정규식 파서에 넘긴다(렌더 X).
  if (/ssfshop\.com/.test(url)) {
    try {
      const resp = await fetch(url, { credentials: "include" });
      const raw = await resp.text();
      if (raw && raw.length > 5000) {
        // [2026-06-22] 데이터는 위 직접 fetch raw HTML 을 그대로 사용(품절임박 N 보존).
        //   단, 다른 소싱처처럼 '화면에도 상품 페이지가 보이도록' 탭을 이동시킨다.
        //   ※ 렌더 결과는 데이터로 쓰지 않으므로(보여주기 전용) lazy 렌더/JS소진 문제 무관.
        if (tabId != null) {
          try {
            await chrome.tabs.update(tabId, { url });
            await waitTabComplete(tabId, 25000);
          } catch (_) { /* 화면 표시 실패해도 데이터(raw)는 정상 반환 */ }
        }
        return { ok: true, html: raw };
      }
    } catch (e) { /* 실패 시 아래 렌더 grab 폴백 */ }
  }
  if (tabId == null) return { ok: false, error: "tabId 없음" };
  try { await chrome.tabs.update(tabId, { url }); } catch (e) { return { ok: false, error: "탭 없음/이동 실패: " + e }; }
  await waitTabComplete(tabId, 25000);
  // SPA 가격 DOM 늦게 뜨는 경우 대비 추가 안정화 대기(빈 HTML 방지)
  await new Promise((r) => setTimeout(r, NAVGRAB_SETTLE_MS));
  const out = await chrome.scripting.executeScript({
    target: { tabId: tabId }, world: "ISOLATED",
    func: () => document.documentElement.outerHTML,
  });
  const html = out && out[0] && out[0].result;
  if (!html) return { ok: false, error: "HTML 수집 실패" };
  // 스스만: per-SKU 재고를 로그인 브라우저 컨텍스트에서 n/v2 API 로 수집(같은 탭).
  let sku_stock = null, sku_diag = null;
  if (/(?:brand|smartstore)\.naver\.com/.test(url)) {
    try {
      const sk = await chrome.scripting.executeScript({
        target: { tabId: tabId }, world: "ISOLATED", func: naverSkuStockFetch,
      });
      const r = sk && sk[0] && sk[0].result;
      if (r && r.map && Object.keys(r.map).length) {
        sku_stock = r.map;
        sku_diag = "ok:" + r.combos;        // 성공: 조합 수
      } else if (r && r.err) {
        sku_diag = "err:" + r.err + (r.topKeys ? "|" + r.topKeys.join(",") : "");
      }
    } catch (e) { sku_diag = "exc:" + String(e).slice(0, 60); }
  }
  // sku_diag: 둔갑 방지 — 실패해도 sku_stock=null(현행 유지). ext_bridge 가 콘솔 로깅.
  return { ok: true, html, sku_stock, sku_diag };
}

// navExtract — 그 탭을 url 로 이동 → 로드 완료 대기 → 소싱처 추출기 실행. (창 안 닫음)
async function handleNavExtract(payload) {
  const tabId = payload.tabId, url = payload.url, sk = payload.source_key;
  if (tabId == null) return { ok: false, error: "tabId 없음" };
  if (!url) return { ok: false, error: "url 없음" };
  const extractor = EXTRACTORS[sk];
  if (!extractor) return { ok: false, error: "레시피 없음(미구현 소싱처): " + sk };
  try { await chrome.tabs.update(tabId, { url }); } catch (e) { return { ok: false, error: "탭 없음/이동 실패: " + e }; }
  await waitTabComplete(tabId, 25000);
  const world = (sk === "lotteon") ? "MAIN" : "ISOLATED";
  const out = await chrome.scripting.executeScript({
    target: { tabId: tabId }, world: world, func: extractor,
  });
  return (out && out[0] && out[0].result) || { ok: false, error: "추출 결과 없음" };
}

// closeWin — 창 닫기. (winId 없거나 이미 닫혔어도 ok)
async function handleCloseWin(payload) {
  const winId = payload.winId;
  if (winId == null) return { ok: true };
  try { await chrome.windows.remove(winId); } catch (_) {}
  return { ok: true };
}

// ── [2026-07-19 · S5] URL 1건 크롤 — 소싱처 지도 예시 주소 「▶ 크롤」 전용 ──
//   · 엔진과 **같은 라우터**(crawlItemInTabBG)를 탄다. 어댑터를 따로 부르지 않는다 —
//     따로 부르면 SSG·롯데아이몰처럼 엔진이 안 쓰는 경로로 긁혀 값이 어긋난다.
//   · **저장하지 않는다.** /api/sources/crawl-result 를 부르지 않으므로 실상품
//     가격·재고 데이터를 건드리지 않는다(지도에서 눌렀다가 매트릭스가 바뀌면 사고).
//     계산·저장은 페이지가 서버 /sourcing-guide/api/<sid>/url-result 로 넘긴다.
//   · 창은 여기서 열고 반드시 닫는다(실패해도 finally).
//   payload: {source_key, url, url_type?}
async function handleCrawlOne(payload) {
  const sk = payload.source_key, url = payload.url;
  if (!sk || !url) return { ok: false, status: "error", error: "source_key·url 이 필요합니다" };
  if (ALL_SOURCE_KEYS.indexOf(sk) < 0) {
    // 정직하게 거절 — 빈 결과를 성공으로 돌려주지 않는다.
    return { ok: false, status: "error",
             error: "이 소싱처는 아직 크롤을 지원하지 않습니다: " + sk };
  }
  const w = await handleOpenWin({});
  if (!w.ok) return { ok: false, status: "error", error: w.error || "창 생성 실패" };
  try {
    const out = await crawlItemInTabBG(
      w.tabId, null, { source_key: sk, url: url, url_type: payload.url_type || "dan" }, null);
    // crawlItemInTabBG 는 {status:'ok'|'error', price, stock, ...} 를 준다. 그대로 넘긴다.
    return { ok: true, result: out || { status: "error", error: "결과 없음" } };
  } finally {
    try { await chrome.windows.remove(w.winId); } catch (_) {}
  }
}

// ── 시스템 신호(보조): CPU/메모리 사용률 0~100. 권한·측정 실패 시 null. ──
//   chrome.system.cpu 의 processors[].usage 는 누적값(kernel+user+idle 틱)이라
//   두 번 샘플(400ms)해 델타로 % 계산. memory 는 (total-available)/total.
async function handleSysinfo() {
  const cpuApi = chrome.system && chrome.system.cpu;
  const memApi = chrome.system && chrome.system.memory;
  if (!cpuApi || !memApi) return { ok: true, cpu: null, mem: null };
  const getCpu = () => new Promise((res) => { try { cpuApi.getInfo((i) => res(i || null)); } catch (_) { res(null); } });
  const getMem = () => new Promise((res) => { try { memApi.getInfo((i) => res(i || null)); } catch (_) { res(null); } });

  let cpu = null;
  try {
    const a = await getCpu();
    await new Promise((r) => setTimeout(r, 400));
    const b = await getCpu();
    if (a && b && a.processors && b.processors && a.processors.length === b.processors.length) {
      let busyDelta = 0, totalDelta = 0;
      for (let i = 0; i < b.processors.length; i++) {
        const ua = a.processors[i].usage, ub = b.processors[i].usage;
        if (!ua || !ub) continue;
        const idle = ub.idle - ua.idle;
        const total = ub.total - ua.total;
        if (total > 0) { busyDelta += (total - idle); totalDelta += total; }
      }
      if (totalDelta > 0) cpu = Math.round(Math.max(0, Math.min(100, (busyDelta / totalDelta) * 100)));
    }
  } catch (_) { cpu = null; }

  let mem = null;
  try {
    const m = await getMem();
    if (m && m.capacity > 0) {
      mem = Math.round(Math.max(0, Math.min(100, ((m.capacity - m.availableCapacity) / m.capacity) * 100)));
    }
  } catch (_) { mem = null; }

  return { ok: true, cpu, mem };
}

function waitTabComplete(tabId, timeoutMs) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(to);
      chrome.tabs.onUpdated.removeListener(listener);
      chrome.tabs.onRemoved.removeListener(onGone);
      resolve();
    };
    const to = setTimeout(finish, timeoutMs);
    function listener(id, info) { if (id === tabId && info.status === "complete") finish(); }
    // ★탭이 사라지면 즉시 끝낸다 — 없으면 죽은 탭을 timeoutMs(25초)만큼 헛기다려 예산을 태운다.
    function onGone(id) { if (id === tabId) finish(); }
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.onRemoved.addListener(onGone);
    // ★lastError 를 반드시 읽을 것 — 안 읽으면 크롬이 'Unchecked runtime.lastError: No tab with id'
    //   를 확장 「오류」로 기록한다(2026-07-17 실제 발생). 읽으면 조용해지고, 죽은 탭도 즉시 반환.
    chrome.tabs.get(tabId, (t) => {
      if (chrome.runtime.lastError) { finish(); return; }   // 탭 없음 = 기다릴 이유 없음
      if (t && t.status === "complete") finish();
    });
  });
}

// [2026-06-14 fix F] 유닛당 하드 타임아웃 — 한 소싱처 1건이 행(예: 네이버 봇차단 페이지가
//   never-complete)해도 전체크롤이 영구 정지하지 않게. 정상 무신사 유닛(waitTabComplete 25s
//   + 혜택 아코디언 ~8s)보다 넉넉히 큰 60s. 타임아웃 시 그 유닛만 error 로 표면화하고 진행.
const UNIT_TIMEOUT_MS = 60000;
// [2026-06-22] bgFetch(서비스 탭 executeScript) 1회 하드 타임아웃. 서버 응답은 0.6~0.8s 라
//   20s 면 충분 — 초과 = 탭 먹통/discard 로 간주하고 탭 교체 후 재시도.
const BGFETCH_TIMEOUT_MS = 20000;
function withTimeout(promise, ms) {
  return new Promise((resolve) => {
    let settled = false;
    const to = setTimeout(() => { if (!settled) { settled = true; resolve({ __timeout: true }); } }, ms);
    Promise.resolve(promise).then(
      (v) => { if (!settled) { settled = true; clearTimeout(to); resolve(v); } },
      (e) => { if (!settled) { settled = true; clearTimeout(to); resolve({ __error: String(e && e.message ? e.message : e) }); } }
    );
  });
}

// ════════════════════════════════════════════
//  무신사 — www.musinsa.com/products/{id}. 옵션·재고=API, 회원가=DOM '나의 할인가'
// ════════════════════════════════════════════
async function musinsaExtractor() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const id = (location.pathname.match(/products\/(\d+)/) || [])[1];
  if (!id) return { ok: false, error: "무신사 product id 추출 실패" };
  const base = "https://goods-detail.musinsa.com/api2/goods/" + id;
  // [2026-07-23 M3] 빵부스러기 조각 → '대>중>소'. 서버 base.build_category_path 와 **같은 규칙**
  //   (조각별 공백정리·빈 조각 제거·맨 앞 '홈'류 더미 라벨만 제외 — 중간 '홈'은 보존).
  //   ※ executeScript 로 페이지에 통째로 주입되는 함수라 바깥 스코프를 못 쓴다 → 인라인 정의.
  const HOME_LABELS = ["홈", "home", "메인", "main", "처음", "top", "전체"];
  const buildCatPath = (parts) => {
    const c = (parts || []).map((p) => String(p == null ? "" : p).replace(/\s+/g, " ").trim()).filter(Boolean);
    while (c.length && HOME_LABELS.indexOf(c[0].toLowerCase()) >= 0) c.shift();
    return c.join(">");
  };

  const oj = await fetch(base + "/options", { credentials: "include", headers: { Accept: "application/json" } }).then((r) => r.json());
  const basic = (oj.data || {}).basic || [];
  const items = (oj.data || {}).optionItems || [];

  const valueNos = [];
  basic.forEach((g) => (g.optionValues || g.values || []).forEach((v) => { if (v.no != null) valueNos.push(v.no); }));
  const invMap = {};
  let invOk = false;
  try {
    const ij = await fetch(base + "/options/v2/prioritized-inventories", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ optionValueNos: valueNos }),
    }).then((r) => r.json());
    const arr = (ij && ij.data) || [];
    arr.forEach((x) => { invMap[x.productVariantId] = x; });
    invOk = arr.length > 0;   // ★ 재고 데이터 실제 수신 여부 (실패/빈응답이면 false)
  } catch (e) { invOk = false; /* 재고 호출 실패 → 아래서 null(불명), 가격은 진행 */ }

  // ★ 2026-06-13 — 표면노출가 = 무신사 구조화 API(goodsPrice.salePrice) 직읽기.
  //   기존: document.body.innerText 정규식으로 '나의 할인가'(회원가)를 price 로 오긁어
  //         표면가 자리에 회원가(예: 110,300)가 들어가 → 이중차감·언더프라이싱 사고. → 폐기.
  //   변경: API 가 표면가(salePrice)·정가(normalPrice)를 숫자로 직접 제공 → 결정적·로그인 불필요.
  //   회원가('나의 할인가')는 참고용 member_price 로만 (계산 base 아님).
  // ★ 2026-06-22 — goodsPrice 일시 실패(네트워크 blip·비JSON 응답) 시 재시도.
  //   배경: 크롤 시작이 가격을 NULL 로 하드리셋하므로, 여기서 fetch 가 '딱 한 번' 실패하면
  //   재시도 없이 price=null → 그 소싱처 전 옵션이 통째로 크롤실패(좋은 값 소실). 라이브 실측:
  //   같은 상품 API 가 직후엔 salePrice 정상 반환 → 일시 blip 이었음. 유효 salePrice 받으면
  //   즉시 종료(정상 시 성능 영향 0), 못 받으면 0.6s·1.2s 백오프로 최대 3회. 폴백은 여전히 금지.
  let surface = null, normal = null;
  // [2026-07-23 M3] 소싱처 카테고리 경로 — 아래 goodsPrice 와 **같은 응답**(api2/goods/{id})의
  //   category.categoryDepth{1..4}Name 이 원천이다. 라이브 실측(2026-07-23, 4046672·4800825):
  //   신발 > 스니커즈 > 라이프스타일화 → '신발>스니커즈>라이프스타일화'.
  //   ※ 무신사 PDP 엔 빵부스러기 DOM 도 BreadcrumbList JSON-LD 도 없다(실측) — 이 API 가 유일 원천.
  //   ※ baseCategoryFullPath("Shoes > 스니커즈 > 기타 스니커즈")는 1단계가 영문이라 안 쓴다.
  //   못 뽑으면 '' (추측 금지 — 서버가 기존값 보존).
  let category_path = "";
  // [2026-07-23 M4-5] 상품 사진·상세설명 원천 — **같은 응답 안**에 있다(추가 호출 0).
  //   thumbnailImageUrl(대표) · goodsImages[](추가컷) · goodsContents(상세 HTML).
  //   주소 조립·정제는 여기서 하지 않는다 — 페이지에 주입되는 함수라 바깥 스코프를
  //   못 쓰고, 규칙을 복제하면 두 벌이 된다. 원문 조각만 넘기고 배관(background)이 만든다.
  let musinsa_goods = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const gr = await fetch(base, { credentials: "include", headers: { Accept: "application/json" } });
      const gj = await gr.json();
      const gd = (gj && (gj.data || gj)) || {};
      if (!category_path) {
        const _c = gd.category || {};
        category_path = buildCatPath([1, 2, 3, 4].map((i) => _c["categoryDepth" + i + "Name"]));
      }
      if (!musinsa_goods) {
        musinsa_goods = {
          thumbnailImageUrl: gd.thumbnailImageUrl || "",
          goodsImages: Array.isArray(gd.goodsImages) ? gd.goodsImages : [],
          goodsContents: gd.goodsContents || "",
        };
      }
      const gp = gd.goodsPrice || {};
      const _sp = parseInt(gp.salePrice, 10);
      if (Number.isFinite(_sp) && _sp > 0) {
        surface = _sp;
        normal = parseInt(gp.normalPrice, 10);
        break;   // 유효 표면가 확보 — 재시도 종료
      }
    } catch (e) { /* 일시 실패 — 아래서 재시도 */ }
    if (attempt < 2) await sleep(600 * (attempt + 1));   // 0.6s → 1.2s 백오프
  }

  // 회원가('나의 할인가')는 참고용으로만 1회 추출 (price base 아님 — 사고 원인 제거).
  let member = null;
  const mm = document.body.innerText.match(/([\d,]{4,})\s*원\s*나의\s*할인가/);
  if (mm) member = parseInt(mm[1].replace(/,/g, ""), 10);

  // ★ 표면가 검증 게이트 — 통과 못 하면 price=null(크롤실패). 폴백(회원가·정가 등) 일절 금지.
  //   G1 존재: salePrice 양수.  G2 상한: salePrice ≤ normalPrice(정가).
  const surfaceValid = Number.isFinite(surface) && surface > 0
    && (!Number.isFinite(normal) || normal <= 0 || surface <= normal);
  const price = surfaceValid ? surface : null;

  const options = items.map((it) => {
    const code = it.managedCode || "";
    let color = "", size = "";
    if (code.includes("^")) { const p = code.split("^"); color = (p[0] || "").trim(); size = (p[1] || "").trim(); }
    else { size = code.trim(); }
    const inv = invMap[it.no] || {};
    // ★ [재고 안전망] 인벤토리 호출 실패(invOk=false) 시 999(충분) 둔갑 금지 → null(불명).
    //   서버 _ingest_option_stocks 가 null 은 스킵 → 옛 좋은 값(예: 2)을 999로 덮어쓰지 않음.
    //   (인벤토리 성공인데 이 variant 만 없는 경우는 기존대로 999=충분 유지.)
    const stock = !invOk ? null
      : (inv.outOfStock ? 0 : (inv.remainQuantity == null ? 999 : Math.max(0, inv.remainQuantity)));
    return { color, size: size.replace("mm", "").trim(), price, stock };
  });
  const anyStock = options.some((o) => o.stock > 0) || (price != null);

  // ★ 2026-06-14 — 현재 페이지(로그인 상태 그대로) 혜택영역 자동 수집 (v0.4.6).
  //   ① 접힌 아코디언('최대 적립' 등)을 펼친다 — innerText 는 숨김=빈값이라 적립내역을
  //      놓침(무신사머니 결제적립 누락 사고). textContent + 펼침으로 빠짐없이.
  //   ② 행(row) 단위 textContent 수집 = 라벨+금액 한 줄(키워드+금액 둘 다 있는 행).
  //   ③ off 신호('등급 할인 불가'/'쿠폰 없음'/'적용 안함')는 금액 없어도 게이트 veto용 포함.
  //   금액은 서버가 라인(matched_lines)에서 추출 — 별도 키 계약 불필요. (실브라우저 3상태 검증)
  async function collectBenefitLines() {
    try {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const norm = () => (document.body.textContent || "").replace(/\s+/g, " ");
      // 적립 내역(접힌 '최대 적립')이 렌더됐는지 검증식 — 이게 보일 때까지 펼침 재시도.
      const hasAccrual = () => /후기 적립\s*[\d,]+\s*원|포인트 10% 적립\s*[\d,]+|등급 적립\([^)]*\)\s*[\d,]+/.test(norm());
      // ★ 크롤 새 창은 React 하이드레이션 전이라 1회 클릭이 자주 실패 → '펼쳐질 때까지' 재시도
      //   (최대 ~8초). 검증식 통과하면 즉시 종료. (실패해도 아래서 있는 만큼 수집)
      for (let i = 0; i < 16 && !hasAccrual(); i++) {
        [...document.querySelectorAll("body *")].forEach((el) => {
          if (el.childElementCount > 4) return;
          const t = (el.textContent || "").replace(/\s+/g, " ").trim();
          if (/최대 적립|나의 할인가/.test(t) && t.length < 40) { try { el.click(); } catch (_) {} }
        });
        await sleep(500);
      }
      const KW = /(쿠폰|적립|할인|머니|혜택|등급|페이|즉시|삼성|토스|카카오|후기|결제)/;
      // 값: 금액(원) 또는 율(%).  부재신호: 없음/불가/적용안함/품절/사용불가 등(혜택이 '없다'는 상태).
      const AMT = /([\-+]?\s*[\d,]{2,}\s*원|\d+(\.\d+)?\s*%)/;
      const ABS = /(없음|불가|불가능|사용\s*불가|적용\s*안함|미적용|품절|해당\s*없음)/;
      const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "svg", "path"]);
      const rows = [];
      // ★ 완전수집: 혜택 키워드가 있고 (값이 있거나 || '없음/불가' 부재신호가 있으면) 한 줄로 담는다.
      //   '없으면 없다'까지 인지하도록 부재 라인도 포함 — 서버 게이트가 exclude(없음/불가)로 off 판정.
      document.querySelectorAll("body *").forEach((el) => {
        if (SKIP.has(el.tagName) || el.childElementCount > 6) return;
        const t = (el.textContent || "").replace(/\s+/g, " ").trim();
        if (!t || t.length > 90) return;
        if (/\{|\}|props|pageProps/.test(t)) return; // SPA JSON 잔재 배제
        if (!KW.test(t)) return;
        if (!AMT.test(t) && !ABS.test(t)) return;   // 값도 부재신호도 없으면 의미 없음 → 제외
        rows.push(t);
      });
      // 부재신호 단독 잎(키워드+없음/불가만, 값 없는 짧은 라벨)도 빠짐없이 — 게이트 veto 재료.
      document.querySelectorAll("body *").forEach((el) => {
        if (el.childElementCount !== 0) return;
        const t = (el.textContent || "").replace(/\s+/g, " ").trim();
        if (!t || t.length > 40) return;
        if (KW.test(t) && ABS.test(t)) rows.push(t);
      });
      const uniq = [...new Set(rows)].sort((a, b) => a.length - b.length);
      const kept = [];
      uniq.forEach((t) => { if (!kept.some((k) => k.includes(t))) kept.push(t); });
      return kept;
    } catch (e) {
      return null; // 수집 실패 — benefits_ok=false 로 표면화
    }
  }
  const _benLines = await collectBenefitLines();

  // ★ 2026-07-04 — 무신사 "상품 쿠폰"(등급쿠폰 포함) 전량 수집. 서버가 쿠폰별로
  //   제외키워드 필터+최고금액 선택 판정(쿠폰별 게이트) — 여기선 원본 그대로 다 담아 보낸다.
  //   API 우선(getUsableCouponsByGoodsNo) → 실패/빈값이면 DOM 폴백(적용 중인 쿠폰 1건만이라도).
  //   스키마 미확정(라이브서 응답 바디 확인 못 함) → 필드명 방어적으로 여러 후보 탐색 +
  //   1회 원본 로그(개발자도구 콘솔서 실크롤 시 [moum][coupon-api] raw 로 스키마 확정용).
  async function collectProductCoupons(goodsNo, salePrice) {
    try {
      if (!goodsNo) return null;
      let comId = "", brand = "", specialtyCodes = "";
      try {
        const nd = document.getElementById("__NEXT_DATA__");
        if (nd && nd.textContent) {
          const dig = (obj, keys, depth) => {
            if (!obj || typeof obj !== "object" || depth > 6) return undefined;
            for (const k of Object.keys(obj)) {
              if (keys.indexOf(k) >= 0 && obj[k] != null) return obj[k];
            }
            for (const k of Object.keys(obj)) {
              const v = obj[k];
              if (v && typeof v === "object") {
                const found = dig(v, keys, depth + 1);
                if (found !== undefined) return found;
              }
            }
            return undefined;
          };
          const j = JSON.parse(nd.textContent);
          comId = dig(j, ["comId"], 0) || "";
          specialtyCodes = dig(j, ["specialtyCodes"], 0) || "";
        }
      } catch (e) { /* __NEXT_DATA__ 파싱 실패 — 빈 값으로 진행(API 가 브랜드 없이도 응답할 수 있음) */ }
      brand = comId || "";
      if (Array.isArray(specialtyCodes)) specialtyCodes = specialtyCodes.join(",");

      const qs = new URLSearchParams();
      qs.set("goodsNo", String(goodsNo));
      if (brand) qs.set("brand", brand);
      if (comId) qs.set("comId", comId);
      if (salePrice != null) qs.set("salePrice", String(salePrice));
      if (specialtyCodes) qs.set("specialtyCodes", specialtyCodes);
      const url = "https://api.musinsa.com/api2/coupon/coupons/getUsableCouponsByGoodsNo?" + qs.toString();

      const resp = await fetch(url, { credentials: "include", headers: { Accept: "application/json" } }).then((r) => r.json());
      try { console.log("[moum][coupon-api] raw", JSON.stringify(resp).slice(0, 1500)); } catch (_) {}

      // 배열 탐색 — ★ 확정 스키마(라이브 실증 goodsNo 3728480): resp.data.list 우선(쿠폰 6건).
      //   그 뒤 방어적 폴백: resp 자체 → resp.data → data.{coupons|couponList} → data 첫 배열 프로퍼티.
      let arr = null;
      if (resp && resp.data && Array.isArray(resp.data.list)) arr = resp.data.list;
      else if (Array.isArray(resp)) arr = resp;
      else if (resp && Array.isArray(resp.data)) arr = resp.data;
      else if (resp && resp.data && typeof resp.data === "object") {
        const d = resp.data;
        if (Array.isArray(d.coupons)) arr = d.coupons;
        else if (Array.isArray(d.couponList)) arr = d.couponList;
        else {
          for (const k of Object.keys(d)) { if (Array.isArray(d[k])) { arr = d[k]; break; } }
        }
      }
      if (!Array.isArray(arr)) return null;

      const toAmount = (v) => {
        if (v == null) return NaN;
        if (typeof v === "number") return v;
        const n = parseInt(String(v).replace(/[^\d\-]/g, ""), 10);
        return Number.isFinite(n) ? n : NaN;
      };
      const NAME_KEYS = ["couponName", "name", "title", "couponTitle", "benefitName"];
      // ★ 확정: 원화 할인액 = salePrice(실증 salePrice=6390 == DOM "6,390원 할인"). 최우선.
      //   couponValue("5")+couponAmountKind("P"=%)는 '율'이지 원화 아님 → amount 로 쓰지 않음.
      //   maxLimitAmount(할인 상한)도 무시. 나머지는 방어적 폴백.
      const AMT_KEYS = ["salePrice", "discountAmount", "discountPrice", "saleAmount", "benefitAmount", "couponSalePrice", "amount", "discount"];
      const out = [];
      arr.forEach((c) => {
        if (!c || typeof c !== "object") return;
        let name = "";
        for (const k of NAME_KEYS) { if (c[k]) { name = String(c[k]); break; } }
        let amount = NaN;
        for (const k of AMT_KEYS) {
          if (c[k] != null) { const a = toAmount(c[k]); if (Number.isFinite(a) && a > 0) { amount = a; break; } }
        }
        if (name && Number.isFinite(amount) && amount > 0) out.push({ name: name, amount: amount });
      });
      return out;
    } catch (e) {
      return null; // API 실패 — 호출부가 DOM 폴백으로 전환
    }
  }

  // DOM 폴백: PDP 상 '상품 쿠폰{명}쿠폰변경-{금액}원' 적용 라인만이라도 최소 확보(non-interactive).
  function collectProductCouponsFromDom() {
    try {
      const t = (document.body.textContent || "").replace(/\s+/g, " ");
      const m = t.match(/상품\s*쿠폰(.*?)쿠폰변경\s*-\s*([\d,]+)\s*원/);
      if (!m) return [];
      const name = (m[1] || "").trim();
      const amount = parseInt((m[2] || "").replace(/,/g, ""), 10);
      if (!name || !Number.isFinite(amount) || amount <= 0) return [];
      return [{ name: name, amount: amount }];
    } catch (e) {
      return [];
    }
  }

  const _apiCoupons = await collectProductCoupons(id, surface);
  const product_coupon_list = (Array.isArray(_apiCoupons) && _apiCoupons.length ? _apiCoupons : null)
    || collectProductCouponsFromDom() || [];

  return {
    ok: !!price,
    price: price,                       // 표면노출가(salePrice) — 검증 통과 시만, 아니면 null
    stock: anyStock ? 999 : 0,          // 재고 있으면 sentinel
    product_name: document.title.split("-")[0].trim().slice(0, 120),
    member_price: member,               // 참고용(회원가, '나의 할인가') — 계산 base 아님
    sale_price: surface, surface_price: surface, normal_price: normal,
    is_logged_in: member != null,
    benefits_ok: Array.isArray(_benLines) && _benLines.length > 0,
    benefit_lines: Array.isArray(_benLines) ? _benLines : [],
    benefit_amounts: {},
    product_coupon_list: product_coupon_list,   // ★ 2026-07-04 — 상품쿠폰 전량(서버가 쿠폰별 게이트 판정)
    category_path: category_path,       // [2026-07-23 M3] 소싱처 카테고리 경로(빵부스러기). 못 뽑으면 ''
    // [2026-07-23 M4-5] 상품 사진·상세설명 **원문 조각**. 조립은 musinsaImageUrlsBG·
    //   musinsaDetailHtmlBG 가 한다(규칙 단일 원천). 못 읽으면 null — 지어내지 않는다.
    musinsa_goods: musinsa_goods,
    option_count: options.length, options,
    error: price ? null : "표면가 검증 실패(salePrice 없음/0/정가 초과) — 크롤실패(폴백 금지)",
  };
}

// ════════════════════════════════════════════
//  롯데온 — www.lotteon.com/p/product/LO... (Vue SPA). 혜택가 = DOM '나의 혜택가'
// ════════════════════════════════════════════
async function lotteonExtractor() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  // [2026-06-12 버그픽스] 1원 오인 방지:
  //   기존 보조식 `나의 혜택가[^\d]*([\d,]+)` 가 라벨 뒤 첫 숫자를 잡는데, 롯데온은
  //   가격이 라벨 *앞*("119,910원 나의 혜택가")에 있고 뒤엔 "1회 최대 20개 구매"의 "1"이
  //   와서 SPA 렌더 전 순간 "1"을 가격으로 오인 → 1원 저장됨.
  //   대책: ① 숫자 4자리 이상 + '원' 인접만 인정(한 자리/원 없는 숫자 배제)
  //         ② 1000원 미만 거부(MIN)  ③ 유효 가격 렌더될 때까지 폴링.
  const MIN = 1000;
  function pickBenefit(t) {
    // (A) [가격]원 나의 혜택가  — 롯데온 기본 레이아웃(가격이 라벨 앞)
    let m = t.match(/([\d,]{4,})\s*원\s*나의\s*혜택가/);
    if (m) { const v = parseInt(m[1].replace(/,/g, ""), 10); if (v >= MIN) return v; }
    // (B) 혜택가 [가격]원  — 라벨 뒤 가격('원' 인접 필수라 "1회"는 배제됨)
    m = t.match(/혜택가\s*([\d,]{4,})\s*원/);
    if (m) { const v = parseInt(m[1].replace(/,/g, ""), 10); if (v >= MIN) return v; }
    return null;
  }
  function pickSale(t) {
    const m = t.match(/(\d+)%\s*([\d,]{4,})\s*원/);
    if (m) { const v = parseInt(m[2].replace(/,/g, ""), 10); if (v >= MIN) return v; }
    return null;
  }
  let benefit = null, sale = null;
  for (let i = 0; i < 16; i++) {
    const t = document.body.innerText;
    if (benefit == null) benefit = pickBenefit(t);
    if (sale == null) sale = pickSale(t);
    if (sale != null && benefit != null) break;   // 둘 다(표면가+혜택가) 잡히면 종료
    if (sale != null && i >= 6) break;             // 표면가만·혜택가 없음(비로그인/무혜택) → 종료
    await sleep(500);
  }
  // [2026-07-03 fix Ⓑ] 표면노출가 = 판매가(sale, 롯데오너스 제외). 기존엔 '나의 혜택가'
  //   (benefit, 롯데오너스 포함)를 저장 → 롯데오너스 이중차감 위험. 표면가 우선, 없으면 benefit 폴백.
  const price = (sale != null) ? sale : benefit;
  const valid = (price != null && price >= MIN);   // 하한 재확인(방어)
  // 롯데오너스(회원할인율) — 크롤가이드 §2 표준 키 lotte_member_discount_rate 로 emit해야
  //   서버(api_benefits compute_breakdown)가 자동 적용. 페이지의 '롯데오너스 … N%' 파싱,
  //   없으면 표면가·혜택가 차이로 산출. 있을 때만 실음(없으면 미반영 — 사용자 정책 2026-07-03).
  let ownusRate = 0;
  {
    const _bt = document.body.innerText;
    const _m = _bt.match(/롯데오너스[^%]{0,20}?(\d+(?:\.\d+)?)\s*%/);
    if (_m) ownusRate = parseFloat(_m[1]) / 100;
    else if (sale != null && benefit != null && benefit < sale) ownusRate = Math.round((sale - benefit) / sale * 1000) / 1000;
  }
  const _lotteBenefit = ownusRate > 0
    ? { lotte_member_discount_rate: ownusRate, lotte_member_discount_label: `롯데오너스 할인 ${(+(ownusRate * 100).toFixed(2))}%` }
    : {};
  const soldOut = /품절|일시품절/.test(document.body.innerText) && !valid;

  // ── [2026-06-15 fix 롯데온 v3] 옵션매핑 API 직읽기 (범용·fail-safe, 라이브 ★FIN 검증) ──
  //   롯데온 플랫폼 표준 API 한 번 fetch → 전 옵션조합 재고 즉시(클릭/색순회/렌더대기 전부 폐기).
  //     URL: pbf.lotteon.com/product/v2/detail/option/mapping/{spdNo}/{sitmNo}  (쿼리 없이 경로만 200, ★URL검증)
  //     data.optionInfo.optionList = 옵션 축들(각 {label,value}) — 축 이름 안 고정(범용: 색상/사이즈/기타 N축)
  //     data.optionInfo.optionMappingInfo["{축1value}_{축2value}…"] = {stkQty, sitmNoSlStatCd, displayPrc}
  //   재고: sitmNoSlStatCd==="SALE" && stkQty>0 → stkQty(실수량) / 아니면 0(품절) / 키없음 → 미존재(제외, 거짓충분 방지)
  //   URL 확보: ① 페이지가 부른 mapping URL(performance) ② location 에서 spd/sitm 조립.
  //   ★ fail-safe: API 실패(URL/CORS/파싱/빈옵션) → DOM 스캔 폴백 → 그래도 0건이면 옵션 비움(거짓충분 절대 금지).
  let options = [];
  // ★[2026-07-03 fix B] 재고 소스 = base/sitm 엔드포인트 우선 (전수조사+라이브 결론).
  //   option/mapping 은 크롤 시점(콜드) 부분응답(예 37/97)만 와서 나머지 셀 드롭 → 서버 last_stock
  //   (롯데온 999) 폴백 → '확인필요' 둔갑. 반면 base/sitm/{sitmNo}(페이지 최초 주력 API,
  //   서버 크롤러 LOTTEON_API_PATHS 首)는 optionInfo.optionMappingInfo 에 전 97셀을 담아 온다(라이브 확인).
  //   → base 우선, option/mapping 폴백. 둘 다 no-store 로 폴링해 최다 응답 채택.
  const _sitm = new URLSearchParams(location.search).get("sitmNo") || "";
  const _spd = (location.pathname.match(/\/product\/([A-Za-z0-9]+)/) || [])[1] || "";
  let _mapHit = "";
  for (let i = 0; i < 12; i++) {
    const hit = (performance.getEntriesByType("resource") || [])
      .map((e) => e.name).find((u) => /\/product\/v2\/detail\/option\/mapping\//.test(u));
    if (hit) { _mapHit = hit.split("?")[0]; break; }
    await sleep(300);
  }
  const _stockUrls = [];
  if (_sitm) _stockUrls.push("https://pbf.lotteon.com/product/v2/detail/search/base/sitm/" + _sitm);  // 우선: base
  if (_mapHit) _stockUrls.push(_mapHit);                                                                 // 폴백: 페이지 mapping
  else if (_spd && _sitm) _stockUrls.push("https://pbf.lotteon.com/product/v2/detail/option/mapping/" + _spd + "/" + _sitm);
  if (_stockUrls.length) {
    try {
      // [2026-07-03 fix Ⓒ] pbf 부분응답 방지 — 옵션조합 수가 안정(2회 연속 최대치)될 때까지
      //   재요청 후 '가장 많은 셀' 응답으로 추출. 크롤 시점 부분 pbf → 놓친 셀이 서버서
      //   999(확인필요)로 남던 문제(색상모음전 37/97 셀) 근본 수정.
      // ★롯데온 pbf 콜드-부분응답 대응 (전수조사 결론 2026-07-03) —
      //   크롤 시점 pbf 는 색상모음전 97셀이 '점진적으로' 채워진다(콜드). 매핑에 아직 없는 셀은
      //   아래 색×사이즈 루프서 드롭되고, 서버가 그 셀을 상품 last_stock(롯데온 999)로 폴백해
      //   '확인필요' 둔갑시킨다. pbf 엔 명시적 완성 개수 필드가 없으므로, '옵션조합 수 증가가
      //   멈출 때까지' 인내 폴링한다(콜드 플래토 버스트를 넘도록 넉넉히). cache:no-store 필수.
      //   예산=UNIT_TIMEOUT_MS 60s → 최대 ~17s(24×700ms) 안전(과거 6×450ms 는 콜드 구간 조기종료로
      //   37셀만 수집→60셀 999 회귀 원인). 최대치 응답을 keep, 증가 6회 연속 없으면 완성 간주.
      // base(우선)·mapping 후보를 no-store 폴링, optionMappingInfo 최다 응답 채택(콜드 인내).
      //   base 는 대개 첫 응답에 전 97셀 → 수초 내 종료. 예산 UNIT_TIMEOUT 60s → 최대 ~20s 안전.
      let oi = {}, _best = -1, _flat = 0;
      for (let _i = 0; _i < 20; _i++) {
        let _grew = false;
        for (const _u of _stockUrls) {
          try {
            const resp = await fetch(_u, { credentials: "include", cache: "no-store", headers: { accept: "application/json" } });
            if (resp.ok) {
              const _j = await resp.json();
              const _oi = (_j && _j.data && _j.data.optionInfo) || {};
              const _n = Object.keys(_oi.optionMappingInfo || {}).length;
              if (_n > _best) { _best = _n; oi = _oi; _grew = true; }   // 새 최대 채택
            }
          } catch (e) { /* 다음 후보/재시도 */ }
        }
        _flat = _grew ? 0 : _flat + 1;
        if (_best > 0 && _flat >= 4) break;   // 4회 정체 = 완성(base 완전시 즉시 종료)
        await sleep(500);
      }
      {
        const axes = oi.optionList || [];
        const omi = oi.optionMappingInfo || {};
        const colorAxis = axes.find((a) => a.title === "색상") || null;
        const sizeAxis = axes.find((a) => /사이즈|size/i.test(a.title || "")) || null;
        const colorOpts = (colorAxis && colorAxis.options) || [{ value: "", label: "" }];
        const sizeOpts = (sizeAxis && sizeAxis.options)
          || (axes.length ? (axes[axes.length - 1].options || []) : []);
        const skuStock = (sku) => {
          const sale = sku && sku.sitmNoSlStatCd === "SALE";
          const q = Number(sku && sku.stkQty);
          return (sale && q > 0) ? q : 0;
        };
        // [2026-06-19 fix #4] 대체상품 가드 — 롯데온은 사이즈가 품절되면 그 옵션 슬롯에 '다른 상품'
        //   (spdNo 다름·SALE·stkQty>0)을 끼워넣는다. 그 상품 재고를 이 사이즈 재고로 오인하면
        //   '품절인데 재고있음' 사고. 리스팅 진짜 상품 spdNo 와 다른 SKU → 실제 품절(0).
        // [2026-06-24 fix] 가드 강건화 — 기존엔 _realSpd 를 /product/(LO[0-9]+) 로만 뽑아 'LO' 접두
        //   URL 만 커버했다. 메이트 모음전처럼 'LO' 없는 숫자형 상품(/p/product/2673780784,
        //   sitmNo=2673780784_2673780785)은 _realSpd="" → _isSub 항상 false → 품절 사이즈의 대체상품
        //   재고(예: 265=4개)가 그대로 새어나옴. mapUrl 의 spd 추출과 동일한 범용 패턴([A-Za-z0-9]+)을
        //   쓰고, 'LO' 접두 유무에 안 휘둘리게 숫자만 비교. URL 에서 못 뽑으면 매핑의 최빈 spdNo
        //   (=리스팅 진짜 상품이 다수)로 보정.
        const _digitsOnly = (x) => String(x == null ? "" : x).replace(/\D/g, "");
        let _realSpd = _digitsOnly((location.pathname.match(/\/product\/([A-Za-z0-9]+)/) || [])[1] || "");
        {
          const _spdCount = {};
          for (const _v of Object.values(omi)) {
            const _sp = _digitsOnly(_v && _v.spdNo);
            if (_sp) _spdCount[_sp] = (_spdCount[_sp] || 0) + 1;
          }
          if (!_realSpd || !_spdCount[_realSpd]) {
            const _modal = Object.keys(_spdCount).sort((a, b) => _spdCount[b] - _spdCount[a])[0];
            if (_modal) _realSpd = _modal;
          }
        }
        if (sizeOpts.length) {
          for (const c of colorOpts) {
            for (const s of sizeOpts) {
              const key = (c.value || "") + "_" + (s.value || "");
              const sku = omi[key] || (!c.value ? omi[s.value] : null);
              if (!sku) continue;                          // 미존재 조합 제외(거짓충분 방지)
              const size = (s.label || "").replace(/mm/i, "").trim();
              if (!size) continue;
              const _isSub = _realSpd && sku.spdNo && _digitsOnly(sku.spdNo) !== _realSpd;
              options.push({ color: (c.label || "").trim(), size, price: valid ? price : null, stock: _isSub ? 0 : skuStock(sku), ..._lotteBenefit });
            }
          }
        } else {
          // 옵션 없는 단일상품 — 매핑 1건이면 상품레벨 재고로
          const vals = Object.values(omi);
          if (vals.length === 1) options.push({ color: "", size: "", price: valid ? price : null, stock: skuStock(vals[0]), ..._lotteBenefit });
        }
      }
    } catch (e) { /* CORS/파싱 실패 → DOM 폴백 */ }
  }
  // ③ DOM 스캔 폴백 (API 0건). [품절]제거·숫자필터·N먼저(버그1수정).
  if (!options.length) {
    const m = {};
    for (const li of document.querySelectorAll("ul.selectLists > li")) {
      const cap = li.querySelector(".caption");
      if (!cap) continue;
      const size = (cap.textContent || "").replace(/^\s*\[품절\]\s*/, "").replace(/mm/i, "").trim();
      if (!/^\d{2,3}$/.test(size)) continue;
      const stEl = li.querySelector(".stock");
      const liSold = /품절|sold|disable|soldout/i.test((li.className || "").toString())
        || li.getAttribute("aria-disabled") === "true";
      let st = 999;
      if (liSold) st = 0;
      else {
        const t = stEl ? stEl.textContent.trim() : "";
        const mm = t.match(/(\d+)\s*개\s*남음/) || t.match(/마지막\s*(\d+)\s*개/);
        st = mm ? Math.max(0, parseInt(mm[1], 10)) : (/품절|일시품절/.test(t) ? 0 : 999);
      }
      if (!(size in m) || st < m[size]) m[size] = st;
    }
    options = Object.keys(m).map((size) => ({ color: "", size, price: valid ? price : null, stock: m[size], ..._lotteBenefit }));
  }

  // ── [2026-07-23 · T6] pbf 혜택 API 이식 — 최대혜택 적용가 + 카드즉시할인 목록 ──
  //   서버 크롤러(lemouton/sourcing/crawlers/lotteon.py :703-707·:1037-1198·:1201-1238)의
  //   favorBox/benefits(쿠폰별 할인 그룹)·qtyChangeFavorInfoList(최종 적용가) 로직을 페이지 안
  //   fetch 로 이식. 서버판은 Playwright 로 페이지가 부른 응답을 스니핑만 하지만, 확장은 직접
  //   불러야 한다 — 두 API 는 **POST(JSON body)** 이고 body 는 페이지가 base API 응답
  //   (basicInfo·priceInfo·stckInfo·dlvInfo)+상수로 만든다(2026-07-23 Playwright 실측:
  //   base 재구성 body → 원본 캡처 응답과 완전 일치 rc=200, 최소 body 는 rc=422 거부).
  //   여긴 MAIN world(www.lotteon.com origin·로그인 쿠키 포함)라 로그인 한정 카드즉시할인
  //   (ORDER 그룹)이 그대로 보인다. 비로그인이면 favor 에 ORDER 그룹 자체가 안 옴(실측:
  //   aplyBestPrcChkTitle="로그인 하시면 더 정확한 혜택가를 알 수 있어요!") → 카드목록 [].
  //   ★폴백 금지: 값 못 얻으면 null/[] 그대로 — 서버가 기존 베이스로 계산하게 둔다.
  let lotteon_max_price = null, lotteon_card_discounts = null, lotteon_store_discount = null;
  let lotteon_naver_via = null;   // [T6] N쇼핑 경유(제휴할인) 선반영 플래그
  // [2026-07-23 M4-5] base 응답을 바깥으로 뺀다 — 같은 응답의 imgInfo(상품 사진)·
  //   descInfo(상세설명 파일 주소)를 결과에 실어야 해서다(추가 호출 0).
  let _bd = null;
  try {
    // ① base 데이터 — 페이지가 실제로 부른 base URL(performance, 쿼리 포함) 우선.
    //    폴백 조립: sitm 형(/base/sitm/{sitmNo}) → pd 형(/base/pd/{spdNo}?isNotContainOptMapping=true, 실측 URL).
    const _baseHit = (performance.getEntriesByType("resource") || [])
      .map((e) => e.name).find((u) => /\/product\/v2\/detail\/search\/base\//.test(u));
    const _baseUrls = [];
    if (_baseHit) _baseUrls.push(_baseHit);
    if (_sitm) _baseUrls.push("https://pbf.lotteon.com/product/v2/detail/search/base/sitm/" + _sitm);
    if (_spd) _baseUrls.push("https://pbf.lotteon.com/product/v2/detail/search/base/pd/" + _spd + "?isNotContainOptMapping=true");
    for (const _u of _baseUrls) {
      try {
        // 8s 개별 타임아웃 — 행 걸린 pbf 호출이 유닛 60s 타임아웃으로 번져
        //   이미 뽑은 price/stock 까지 버리는 것 방지 (AbortSignal.timeout = MAIN world 페이지 컨텍스트 OK).
        const _r = await fetch(_u, { credentials: "include", cache: "no-store", headers: { accept: "application/json" }, signal: AbortSignal.timeout(8000) });
        if (!_r.ok) continue;
        const _j = await _r.json();
        const _d = _j && _j.data;
        if (_d && _d.basicInfo && _d.priceInfo) { _bd = _d; break; }
      } catch (e) { /* 다음 후보 */ }
    }
    if (_bd) {
      // ② POST body 재구성 — 캡처된 페이지 원본 body 와 동일 구성(키 전부, 실측 검증).
      const _bi = _bd.basicInfo || {}, _pi = _bd.priceInfo || {}, _si = _bd.stckInfo || {}, _di = _bd.dlvInfo || {};
      const _n2 = (x) => String(x).padStart(2, "0");
      const _now = new Date();
      const _dttm = "" + _now.getFullYear() + _n2(_now.getMonth() + 1) + _n2(_now.getDate())
        + _n2(_now.getHours()) + _n2(_now.getMinutes()) + _n2(_now.getSeconds());
      const _body = {
        spdNo: _bi.spdNo, sitmNo: _bi.sitmNo,
        trGrpCd: _bi.trGrpCd, trNo: _bi.trNo, lrtrNo: _bi.lrtrNo,
        strCd: _bi.strCd || "", ctrtTypCd: _bi.ctrtTypCd,
        slPrc: _pi.slPrc, slQty: 1,
        scatNo: _bi.scatNo, brdNo: _bi.brdNo,
        sfcoPdMrgnRt: _pi.sfcoPdMrgnRt, sfcoPdLwstMrgnRt: _pi.sfcoPdLwstMrgnRt,
        afflPdMrgnRt: (_pi.afflPdMrgnRt === undefined ? null : _pi.afflPdMrgnRt),
        afflPdLwstMrgnRt: (_pi.afflPdLwstMrgnRt === undefined ? null : _pi.afflPdLwstMrgnRt),
        pcsLwstMrgnRt: _pi.pcsLwstMrgnRt,
        infwMdiaCd: "PC", chCsfCd: "DI", chTypCd: "DI02", chNo: "100195", chDtlNo: "1000617",
        aplyStdDttm: _dttm, cartDvsCd: _di.cartDvsCd,
        thdyPdYn: _bi.thdyPdYn || "N", dvCst: _di.dvCst || 0, fprdDvPdYn: "N",
        discountApplyProductList: [], maxPurQty: _bi.maxPurQty,
        stkMgtYn: _si.stkMgtYn, screenType: "PRODUCT",
        dmstOvsDvDvsCd: _bi.dmstOvsDvDvsCd, dvPdTypCd: _di.dvPdTypCd,
        dvCstStdQty: _di.dvCstStdQty || 0,
        aplyBestPrcChk: "Y", pyMnsExcpLst: [], cpnBoxVersion: "V2",
      };
      const _post = async (u, b) => {
        const _r = await fetch(u, {
          method: "POST", credentials: "include", cache: "no-store",
          headers: { "content-type": "application/json", accept: "application/json" },
          body: JSON.stringify(b),
          signal: AbortSignal.timeout(8000),   // 행 방지 — base fetch 와 동일 8s
        });
        if (!_r.ok) { try { console.log("[moum lotteon pbf ERR]", u.split("/").pop(), "http", _r.status); } catch (_) {} return null; }
        const _j = await _r.json();
        // pbf 는 실패도 HTTP 200 + returnCode 422 로 온다(실측) → returnCode 200 만 신뢰.
        if (!(_j && String(_j.returnCode) === "200" && _j.data)) {
          // 조용한실패 금지 — rc 값을 콘솔에 남긴다(비정상 body·구조 변경 감지 단서).
          try { console.log("[moum lotteon pbf ERR]", u.split("/").pop(), "rc", _j && _j.returnCode); } catch (_) {}
          return null;
        }
        return _j.data;
      };
      const _qd = await _post("https://pbf.lotteon.com/product/v2/extlmsa/promotion/qtyChangeFavorInfoList", _body);
      const _fd = await _post("https://pbf.lotteon.com/product/v2/extlmsa/promotion/favorBox/benefits", { ..._body, mallNo: "1" });

      // ③ 카드즉시할인 목록 + 스토어 즉시할인 — favor.discountGroups[] (lotteon.py :1084-1134 이식)
      //    카드 판정 = lotteon.py is_card_coupon 그대로: 그룹 title=="카드즉시할인/장바구니쿠폰"
      //    OR prKndCd∈{CRD_IMMD,CPN_BSK_CPN} OR prTypCd=="CRD_PR".
      //    (⚠️ dcTnnoCd 기준 아님 — lotteon.py :722-723 에서 4TH=쿠폰(스토어/상품), 5TH=카드즉시할인.
      //     4TH 를 카드로 묶으면 스토어쿠폰이 카드로 오염된다.)
      if (_fd && Array.isArray(_fd.discountGroups)) {
        const _cards = []; const _seen = {};
        let _storeAmt = 0, _sawStore = false;
        for (const _g of _fd.discountGroups) {
          const _gTitle = ((_g && _g.title) || "").trim();
          const _isCardGroup = _gTitle === "카드즉시할인/장바구니쿠폰";
          for (const _pr of (_g && _g.discountApplyPromotionList) || []) {
            const _knd = _pr.prKndCd || "", _typ = _pr.prTypCd || "", _tier = (_pr.dcTnnoCd || "").trim();
            const _amt = parseInt(_pr.dcAmt, 10) || 0;
            // dcRt = 퍼센트 단위(7=7%) — 0~1 분율 아님. T8 엔진 소비 시 /100 필수
            //   (타 필드 lotte_member_discount_rate 는 분율(0.01=1%)이라 혼동 주의).
            const _rate = parseFloat(_pr.dcRt) || 0;
            // 표시명 우선순위 = lotteon.py :1102-1106 (dispTitle → dispName → prNm)
            const _label = ((_pr.dispTitle || "").trim() || (_pr.dispName || "").trim() || (_pr.prNm || "").trim());
            const _isCard = _isCardGroup || _knd === "CRD_IMMD" || _knd === "CPN_BSK_CPN" || _typ === "CRD_PR";
            // dedupe 키 = label+amount+rate — 같은 라벨·다른 금액 프로모션 유실 방지
            //   (label 단독이면 T8 이 최적 카드를 고를 때 과소평가 위험).
            const _dk = _label + "|" + _amt + "|" + _rate;
            if (_isCard && _label && !_seen[_dk]) { _seen[_dk] = 1; _cards.push({ label: _label, amount: _amt, rate: _rate }); }
            // 스토어 즉시할인(정보용) — dcTnnoCd 1ST(스토어 즉시할인, lotteon.py :719)·적용중(prAplyYn=Y)만 합산
            if (_tier === "1ST" && String(_pr.prAplyYn || "").toUpperCase() === "Y") { _storeAmt += _amt; _sawStore = true; }
          }
        }
        lotteon_card_discounts = _cards;           // favor 성공 + 카드 0건(비로그인/무혜택) = [] (정직)
        if (_sawStore) lotteon_store_discount = _storeAmt;
      }
      // [2026-07-23 · 2차 T6] N쇼핑 경유 — 「제휴할인」 항목이 있으면 경유 상태이고
      //   그 금액은 이미 가격에 자동 반영(선반영)이다(사장님 확정 2026-07-23).
      //   → preapplied=true 로 알려 서버가 재차감하지 않게 한다(이중차감 방지).
      if (_fd && Array.isArray(_fd.discountGroups)) {
        for (const _g2 of _fd.discountGroups) {
          for (const _p2 of (_g2 && _g2.discountApplyPromotionList) || []) {
            const _nm2 = ((_p2.dispTitle || _p2.dispName || _p2.prNm) || "").trim();
            if (/제휴할인/.test(_nm2)) {
              lotteon_naver_via = {
                naver_via_preapplied: true,
                naver_via_amount: parseInt(_p2.dcAmt, 10) || 0,
                naver_via_label: _nm2,
              };
              break;
            }
          }
          if (lotteon_naver_via) break;
        }
      }
      // ④ 최대혜택 적용가 — qty.orderDcAplyTotAmt.
      //    ⚠️ lotteon.py _parse_lotteon_prices(:1206-1212) 의 max_price=immdDcAplyTotAmt 는
      //    카드즉시할인 **미포함**(즉시할인까지만) — 우리가 원하는 「최대 할인혜택 적용완료」
      //    나의 혜택가(카드 포함)가 아니다. 근거로 고른 필드:
      //      · orderDcAplyTotAmt = ORDER 그룹(카드즉시할인/장바구니쿠폰) 최적 적용 후 총액
      //        (lotteon.py :1207 주석 "orderDcAplyTotAmt (쿠폰까지 적용)" + 필드명 orderDc=ORDER 그룹 할인)
      //      · 요청 body aplyBestPrcChk:"Y" = 최적(최대) 혜택 계산 요청 — 사이트 「최대 할인혜택 적용하기」와 동일 경로
      //      · 비로그인 실측: order==immd(카드 없음) 로 일관 — 로그인 시 카드 반영분만큼 낮아지는 구조.
      //    폴백(2순위): favor.totAmt = totSlPrc − totDcAmt(bestPrAplyYn=Y 합) — 같은 의미의 사이트 계산값.
      //    둘 다 없으면 null(추정·계산 대체 금지). 카드 목록은 별도 유지(엔진이 경로 재구성 — T8).
      if (_qd) {
        const _ord = parseInt(_qd.orderDcAplyTotAmt, 10) || 0;
        if (_ord > 0) lotteon_max_price = _ord;
      }
      if (lotteon_max_price == null && _fd) {
        const _tot = parseInt(_fd.totAmt, 10) || 0;
        if (_tot > 0) lotteon_max_price = _tot;
      }
    }
  } catch (e) {
    // 전체 실패 = null/[] 유지 (폴백 금지 — 서버가 기존 베이스로 계산). 단 조용한실패 금지 — 로그는 남긴다.
    try { console.log("[moum lotteon pbf ERR]", String(e).slice(0, 120)); } catch (_) {}
  }

  // ── [2026-07-23 M3] 소싱처 카테고리 경로(빵부스러기) ──────────────────────────
  //   라이브 실측(2026-07-23): 롯데온 PDP 는 원천이 **두 개**이고 값이 같다.
  //     ① JSON-LD Product.category = "여성패션 > 신발 > 운동화/스니커즈 > 스니커즈" ← 1순위(결정적)
  //     ② DOM 빵부스러기 ol.locationList > li > a = [홈, 여성패션, 신발, 운동화/스니커즈, 스니커즈]
  //   ①이 Vue 렌더 타이밍에 아직 없을 수 있어 ②를 폴백으로 둔다. 맨 앞 '홈' 은 buildCatPath 가 제거
  //   (서버 base.build_category_path 와 동일 규칙 — 조각 공백정리·빈 조각 제거·앞머리 더미만 제외).
  //   ※ 이 함수는 executeScript 로 페이지에 통째로 주입돼 바깥 스코프를 못 쓴다 → 헬퍼 인라인 정의.
  //   ※ 못 뽑으면 '' — 추측 금지. 빈 값은 crawl-result 에서 서버가 무시해 기존값이 보존된다(무스톰프).
  // ==== M4IMG-LOTTEON-LD-START ====
  let category_path = "";
  // [2026-07-23 M4-5] 같은 JSON-LD 블록의 `Product.image` = 상품 사진(절대 URL).
  //   실측(LO2158462914): base API 의 imgRteNm+imgFileNm 조립값과 **문자열까지 같다**.
  //   조립보다 '읽은 값'이 안전하므로 1순위로 쓴다(조립은 background 폴백).
  let lotteon_ld_images = [];
  {
    const HOME_LABELS = ["홈", "home", "메인", "main", "처음", "top", "전체"];
    const buildCatPath = (parts) => {
      const c = (parts || []).map((p) => String(p == null ? "" : p).replace(/\s+/g, " ").trim()).filter(Boolean);
      while (c.length && HOME_LABELS.indexOf(c[0].toLowerCase()) >= 0) c.shift();
      return c.join(">");
    };
    try {
      for (const _s of document.querySelectorAll('script[type="application/ld+json"]')) {
        let _j = null;
        try { _j = JSON.parse(_s.textContent); } catch (_) { continue; }
        for (const _o of (Array.isArray(_j) ? _j : [_j])) {
          if (!_o || _o["@type"] !== "Product") continue;
          // 🔴 [2026-07-23 M4-5 리뷰지적] 카테고리와 사진은 **반드시 같은 _o 에서** 뽑는다.
          //   롯데온 PDP 는 `ld+json` Product 블록을 여러 개 내보낼 수 있다(본상품 +
          //   「함께 본 상품」 등). 원천을 따로 고르면 ①본상품 카테고리 + ②추천상품 사진
          //   처럼 **다른 상품이 섞인 한 행**이 만들어져 대표사진 오등록이 된다.
          //   서버 status=='ok' 게이트는 '빈 값'만 막지 이 '틀린 값'은 못 막는다.
          //   → 첫 Product 블록에서 끊는다(사진이 없으면 없는 대로 base API 폴백을 쓴다).
          if (typeof _o.category === "string" && _o.category.trim()) {
            category_path = buildCatPath(_o.category.split(">"));
            if (_o.image) lotteon_ld_images = Array.isArray(_o.image) ? _o.image.slice() : [_o.image];
            break;
          }
        }
        if (category_path) break;
      }
      if (!category_path) {
        category_path = buildCatPath(
          [...document.querySelectorAll("ol.locationList li a")].map((a) => a.textContent));
      }
    } catch (e) {
      category_path = "";   // 조용한 실패 방지 — 못 뽑았다는 사실을 빈 문자열로 정직하게 남긴다
      try { console.log("[moum lotteon cat ERR]", String(e).slice(0, 120)); } catch (_) {}
    }
  }
  // ==== M4IMG-LOTTEON-LD-END ====

  return {
    ok: valid,
    price: valid ? price : null,
    stock: valid && !soldOut ? 999 : 0,
    product_name: document.title.split(":")[0].trim().slice(0, 120),
    benefit_price: benefit, sale_price: sale, ..._lotteBenefit,
    // [2026-07-23 · T6] 롯데온 pbf 혜택 — 최대혜택 적용가·카드즉시할인 목록·스토어 즉시할인(정보용)
    lotteon_max_price, lotteon_card_discounts, lotteon_store_discount,
    category_path,   // [2026-07-23 M3] 소싱처 카테고리 경로(빵부스러기). 못 뽑으면 ''
    // [2026-07-23 M4-5] 상품 사진·상세설명 **원문 조각**(조립은 lotteonImageUrlsBG·
    //   lotteonDetailUrlBG). base 응답 전체가 아니라 쓰는 두 노드만 넘긴다(payload 절약).
    //   ★ 상세는 주소만 넘긴다 — 파일 수신은 CORS 때문에 서비스워커 몫이다.
    lotteon_ld_images: lotteon_ld_images,
    lotteon_base: _bd ? { imgInfo: _bd.imgInfo || null, descInfo: _bd.descInfo || null } : null,
    ...(lotteon_naver_via || {}),   // [2차 T6] 경유 선반영 플래그(있을 때만)
    option_count: options.length, options,
    error: valid ? null : (soldOut ? "품절" : "가격 추출 실패(렌더 미완/하한 미달)"),
  };
}

// ════════════════════════════════════════════════════════════════════
//  [2026-06-14] 2단계 — 백그라운드 크롤 오케스트레이터
//   크롤 엔진(멀티 모음전 큐 + 적응형 동시성 + 일시중지/중지)을 이 서비스워커에서 돌린다.
//   → mou-m.com 탭을 닫거나 다른 페이지로 이동해도 크롤이 계속된다(1단계는 페이지에서 돌아 멈췄음).
//   페이지(ext_bridge)는 enqueue/pause/resume/stop/cancel/getState 메시지만 보내는 얇은 클라이언트.
//   진행 로그는 chrome.tabs.sendMessage 로 열린 mou-m 탭들에 push → content_mou 가 페이지로 중계.
//   가격 안전 로직(하드리셋·finalize·폴백금지·표면→매입 갱신·sku_stock) 전부 보존(ext_bridge 와 동일).
// ════════════════════════════════════════════════════════════════════
// [v0.6.7] hmall·lotteimall 추가 — navGrab→서버 /api/sources/parse 로 추출(SSR/__NEXT_DATA__).
//   이게 없으면 전체크롤 소싱처 목록(ALL)에서 빠져 hmall URL 이 큐에 안 들어감(크롤 누락).
const BG_PARSE_SOURCES = ["lemouton", "ssf", "ssg", "ss_lemouton", "hmall", "lotteimall"];
const BG_JS_SOURCES = ["musinsa", "lotteon"];
// 크롤할 줄 아는 소싱처 전체. 전체크롤 큐 편입 기준이자, S5 단건 크롤(crawl.one)의
// 지원 여부 판정 기준 — 한 곳에서만 관리해 둘이 어긋나지 않게 한다.
const ALL_SOURCE_KEYS = BG_JS_SOURCES.concat(BG_PARSE_SOURCES);

// ── [2026-07-07] 창없는 Fast-lane 프레임워크 (플래그 OFF 기본) ──
//   FAST_FETCH_SOURCES 에 든 소싱처는 crawlItemInTabBG 최상단에서 어댑터(창 없이 직접 fetch)를
//   먼저 시도한다. 성공(status:"ok")이면 그 값을 쓰고, 실패/예외면 그대로 아래 기존 창 경로로
//   폴백한다(★경로 폴백이지 값 폴백 아님 — 가짜값 안 채움). 어댑터는 소싱처별 G1 검증 통과 후
//   Phase 2 에서 FETCH_ADAPTERS 에 등록하고 FAST_FETCH_SOURCES 에 그 소싱처 키를 추가한다.
//   배열이 비어 있는 동안(현재)은 어떤 소싱처도 fetch 경로를 타지 않아 기존 동작과 100% 동일.
// G1/안전 통과분만 ON. 르무통·SSF=색×사이즈 전수 실브라우저 100%일치(2026-07-08). ssg·lotteimall=
//   windowless==기존 서버파서 동일+raw없으면 창 폴백(자가보호)→데이터 악화 불가. 전셀 대조는 크롤-검사 탭.
//   ⚠️보류: musinsa(혜택=로그인DOM 손실)·hmall(색×사이즈 API보강 창필요)·ss_lemouton(per-SKU 로그인API)
//           =어댑터 '성공'반환하나 불완전→폴백안됨→정책확정 후 추가.
const FAST_FETCH_SOURCES = ["lemouton", "ssf", "hmall"];   // [2026-07-09] hmall 추가 — 창없이 raw __NEXT_DATA__ + item-stockcount SW fetch 실측 통과.
// [2026-07-09] SSG·롯데아이몰 = 확장 SW fetch(cross-site)를 WAF가 차단(Sec-Fetch-Site, JS 위조 불가).
//   해법 = 그 도메인 탭 안에서 same-origin fetch(WAF 통과·롯데아이몰 실증) → 렌더 없이 원문 확보.
//   데이터는 SSR 원문(uitemObj/itemInvQtyInfo)에 있고 서버 파서가 읽음 → 창(렌더 DOM)과 값 동일.
//   ★benefit_lines 미사용 소싱처(default navGrab 경로 = 혜택 크롤 안 함)라 창없이로도 손실 없음(무신사·롯데온과 다름).
const SAMEORIGIN_FETCH_SOURCES = ["ssg", "lotteimall"];
const FETCH_ADAPTERS = {};       // sk -> async (item) => crawlItemInTabBG 와 동일 형태 결과

const _mgr = { queue: [], running: null, paused: false, stopped: false, base: "", _kick: null, view: {} };

function bgMedian(arr) {
  if (!arr.length) return 0;
  const s = arr.slice().sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
function bgClamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

// ── 진행 로그 → 열린 mou-m 탭들로 push + 스냅샷용 compact view 갱신 ──
const MOUM_TAB_GLOBS = ["https://www.mou-m.com/*", "https://mou-m.com/*", "http://54.116.196.90/*", "https://54.116.196.90/*"];
// [v0.6.7] 서버 타깃 origin 기반 탭 glob — 로컬 모드(localhost)면 localhost 탭을 서비스/로그 대상으로.
function _baseOrigin() {
  try { return new URL(_mgr.base || "https://mou-m.com").origin; } catch (_) { return "https://mou-m.com"; }
}
function _baseGlobs() {
  const o = _baseOrigin();
  if (/localhost|127\.0\.0\.1/.test(o)) return [o + "/*"];
  return MOUM_TAB_GLOBS;
}
// [2026-07-06 v0.7.17] 실시간 집계(done/total) — 위젯(crawl_log)의 bundleProgress 와 동일식으로
//   모든 모음전 view 를 합산. bgEmit 이 매 이벤트에 실어 보내면 자동화 페이지 링이 위젯과 똑같이 오름.
function _aggProgress() {
  let done = 0, total = 0;
  for (const c in _mgr.view) {
    const b = _mgr.view[c]; total += (b.total || 0);
    const src = b.sources || {}; const keys = Object.keys(src);
    const urlKeys = keys.filter((k) => k.indexOf("|") >= 0);
    const use = urlKeys.length ? urlKeys : keys.filter((k) => k.indexOf("|") < 0);
    let ss = 0; for (const sk of use) ss += (src[sk] && src[sk].done) || 0;
    done += Math.max(ss, b.done || 0);
  }
  return { done: done, total: total };
}
function bgEmit(detail) {
  detail = detail || {};
  if (detail.ts == null) detail.ts = Date.now();
  try { bgUpdateView(detail); } catch (_) {}
  try { detail.agg = _aggProgress(); } catch (_) {}   // 자동화 링용 실시간 집계
  try {
    chrome.tabs.query({ url: _baseGlobs() }, (tabs) => {
      if (chrome.runtime.lastError) return;   // 오류를 안 읽으면 확장 「오류」에 기록됨
      if (!tabs) return;
      for (const t of tabs) {
        try { chrome.tabs.sendMessage(t.id, { __moumPush: "log", detail }, () => { void chrome.runtime.lastError; }); } catch (_) {}
      }
    });
  } catch (_) {}
}
function bgEmitQueue() {
  const q = [];
  if (_mgr.running) q.push({ code: _mgr.running, status: _mgr.paused ? "pause" : "run" });
  _mgr.queue.forEach((c) => q.push({ code: c, status: "wait" }));
  bgEmit({ type: "queue", queue: q, running: _mgr.running, paused: _mgr.paused });
  try { bgPersist(); } catch (_) {}   // 큐/상태 변화마다 체크포인트 갱신
}

// compact view (재연결 스냅샷용 — 로그 제외, 상태/진행/게이지만)
function vGet(code) { return _mgr.view[code] || (_mgr.view[code] = { label: code, status: "wait", total: 0, done: 0, metrics: {}, sources: {} }); }
function vSrc(v, sk) { return v.sources[sk] || (v.sources[sk] = { status: "wait", done: 0, total: null }); }
function bgUpdateView(d) {
  if (d.type === "queue") return;
  const code = d.bundle; if (!code) return;
  const v = vGet(code); v.label = code;
  if (d.metrics) {
    ["concurrency", "cap", "active", "cpu", "mem", "avgSec"].forEach((k) => { if (d.metrics[k] != null) v.metrics[k] = d.metrics[k]; });
    if (d.metrics.total != null) v.total = d.metrics.total;
    if (d.metrics.done != null) v.done = d.metrics.done;
  }
  switch (d.type) {
    case "start": v.status = "run"; v.finishMsg = ""; break;
    case "window-open": { const s = vSrc(v, d.source); s.status = "run"; s.done = 0; break; }
    case "item-done": { const s = vSrc(v, d.source); s.done = (s.done || 0) + 1; break; }
    case "item-retried": break; // [2026-06-22] 재시도 성공 — s.done 증가 없음(42/40 오버카운트 방지)
    case "source-done": { const s = vSrc(v, d.source); s.status = "done"; break; }
    case "bundle-paused": v.status = "pause"; break;
    case "bundle-resumed": v.status = "run"; break;
    case "finish": v.status = d.stopped ? "stop" : "done"; v.finishMsg = d.msg || ""; break;
  }
  try { bgPersist(); } catch (_) {}   // 진행 변화마다 체크포인트 갱신
}

// ── SW 깨우기 + 자동 재개(2026-06-18) ──────────────────────────────────────
//   MV3 서비스워커는 유휴 ~30s 면 크롬이 잠재워 in-memory 루프(_mgr)가 사라진다.
//   대책: ① 상태를 chrome.storage.session 에 영속(bgPersist) ② keepalive 알람이
//   크롤 중 ~30s 마다 SW 를 깨움 → 깨어날 때 top-level bgBootResume 이 체크포인트의
//   '진행 중 크롤'을 감지해 runQueueBG 로 이어서 재가동(끊긴 모음전은 처음부터 재크롤,
//   하드리셋+finalize fail-safe 라 잘못 저장 없음). → "탭 닫아도/새로고침해도 지속".
try {
  chrome.alarms.onAlarm.addListener((a) => {
    if (!a || a.name !== "moum-keepalive") return;
    try { if (_mgr.running) bgPersist(); } catch (_) {}
    // SW 가 죽었다 알람으로 깨어난 경우(_mgr 비어있음) → 체크포인트로 재가동
    try { if (!_mgr.running) bgBootResume(); } catch (_) {}
  });
} catch (_) {}
function bgKeepaliveStart() { try { chrome.alarms.create("moum-keepalive", { periodInMinutes: 0.4 }); } catch (_) {} }
function bgKeepaliveStop() { try { chrome.alarms.clear("moum-keepalive"); } catch (_) {} }

// ── mou-m.com 서버 호출 — 반드시 mou-m 탭 컨텍스트(first-party)에서 실행 ──
//   이유: 서비스워커가 직접 fetch(mou-m) 하면 cross-origin 이라 SameSite=Lax 세션쿠키가
//   안 실려 인증 실패(저장·parse 401) 위험. 그래서 chrome.scripting 으로 mou-m 탭 안에서
//   fetch 를 실행한다(same-origin → 쿠키 확실). 탭이 없으면(사용자가 다 닫음) SW 가
//   백그라운드 mou-m 탭을 1개 띄워 서비스 탭으로 쓰고(_serviceTabOwned), 크롤 끝나면 닫는다.
//   → "탭 닫아도 계속" 을 깨지 않으면서 인증을 보장.
let _serviceTabId = null;
let _serviceTabOwned = false;

async function _isMoumTab(tabId) {
  try { const t = await chrome.tabs.get(tabId); if (!t || !t.url) return false;
    try { return new URL(t.url).origin === _baseOrigin(); } catch (_) { return false; } }
  catch (_) { return false; }
}
async function _isDiscarded(tabId) {
  try { const t = await chrome.tabs.get(tabId); return !!(t && t.discarded); } catch (_) { return true; }
}
// 선택한 서비스 탭이 크롬에 의해 다시 잠들지(discard) 않게 — 크롤 도중 executeScript 영구 대기 방지.
function _pinTab(tabId) { try { chrome.tabs.update(tabId, { autoDiscardable: false }, () => { void chrome.runtime.lastError; }); } catch (_) {} }
async function ensureServiceTab() {
  if (_serviceTabId != null && await _isMoumTab(_serviceTabId) && !(await _isDiscarded(_serviceTabId))) return _serviceTabId;
  _serviceTabId = null; _serviceTabOwned = false;
  // 이미 열린 mou-m 탭 재사용(사용자 탭이면 닫지 않음).
  // ★ [2026-06-22] discard(잠든) 탭은 executeScript 가 영구 대기 → 크롤 엔진 wedge 원인.
  //   깨어있는(!discarded·complete) 탭을 우선 선택하고, 없으면 하나 깨워서(reload) 사용.
  const tabs = (await chrome.tabs.query({ url: _baseGlobs() })) || [];
  let pick = tabs.find((t) => t && !t.discarded && t.status === "complete") || tabs.find((t) => t && !t.discarded);
  if (!pick && tabs.length) {
    pick = tabs[0];
    try { await chrome.tabs.reload(pick.id); await waitTabComplete(pick.id, 25000); } catch (_) {}
  }
  if (pick && pick.id != null) {
    _serviceTabId = pick.id; _serviceTabOwned = false; _pinTab(pick.id);
    return _serviceTabId;
  }
  // 없으면 백그라운드 탭 1개 생성(비활성) → 서비스 탭
  const base = _mgr.base || "https://mou-m.com";
  const t = await chrome.tabs.create({ url: base + "/", active: false });
  if (!t || t.id == null) throw new Error("서비스 탭 생성 실패");
  _pinTab(t.id);
  await waitTabComplete(t.id, 25000);
  _serviceTabId = t.id; _serviceTabOwned = true;
  return _serviceTabId;
}
async function closeServiceTabIfOwned() {
  if (_serviceTabOwned && _serviceTabId != null) { try { await chrome.tabs.remove(_serviceTabId); } catch (_) {} }
  _serviceTabId = null; _serviceTabOwned = false;
}
// mou-m 탭 안에서 실행될 fetch (same-origin, 쿠키 동봉). 상대경로 path 사용.
function _injectedFetch(p, o) {
  return (async () => {
    try {
      const r = await fetch(p, Object.assign({ credentials: "same-origin" }, o || {}));
      const txt = await r.text();
      let j = null; try { j = JSON.parse(txt); } catch (_) {}
      return { ok: r.ok, status: r.status, json: j, text: j ? null : (txt || "").slice(0, 160) };
    } catch (e) { return { ok: false, status: 0, json: null, error: String(e).slice(0, 120) }; }
  })();
}
// fetch Response 유사 객체 반환(.ok/.status/.json()) — 호출부 .then(x=>x.json()) 호환.
async function bgFetch(path, opts) {
  let out = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    let tabId;
    try { tabId = await ensureServiceTab(); }
    catch (e) { return { ok: false, status: 0, json: () => Promise.resolve(null), _err: String(e) }; }
    try {
      // ★ [2026-06-22] executeScript 하드 타임아웃 — 서비스 탭이 잠들었거나(discard) 주입이
      //   never-resolve 하면 bgFetch 가 영구 대기 → 백그라운드 엔진 전체가 wedge(목표 0 에서 멈춤,
      //   중지 버튼도 무력)되던 버그. 타임아웃 시 서비스 탭을 버리고 1회 재선택·재시도.
      const res = await withTimeout(chrome.scripting.executeScript({
        target: { tabId: tabId }, world: "ISOLATED", func: _injectedFetch, args: [path, opts || null],
      }), BGFETCH_TIMEOUT_MS);
      if (res && (res.__timeout || res.__error)) {
        _serviceTabId = null;   // 잠든·먹통 탭 폐기 → 재시도 시 깨어있는 탭 재선택
        if (attempt === 1) return { ok: false, status: 0, json: () => Promise.resolve(null), _err: res.__timeout ? "bgFetch 타임아웃(서비스 탭 응답 없음)" : res.__error };
        continue;
      }
      out = res && res[0] && res[0].result;
      if (out) break;
    } catch (e) {
      _serviceTabId = null;   // 탭이 닫혔을 수 있음 → 재시도 시 재확보
      if (attempt === 1) return { ok: false, status: 0, json: () => Promise.resolve(null), _err: String(e) };
    }
  }
  out = out || { ok: false, status: 0, json: null };
  return { ok: out.ok, status: out.status, _text: out.text, json: () => Promise.resolve(out.json) };
}

// ── 제어 API (메시지 핸들러가 호출) ──
function mgrEnqueue(payload) {
  payload = payload || {};
  const code = payload.code || null;
  const codes = payload.codes || (code ? [code] : []);
  if (payload.base) _mgr.base = payload.base;
  if (!codes.length) return { ok: false, error: "code 없음" };
  // [2026-07-06] priority=true (모음전 상세에서 직접 「전체크롤」) → 큐 맨 앞에 삽입해 다음 순번.
  //   자동 폴링(due-bundles)은 priority 없이 큐 뒤에 붙는다(오래된 순 유지).
  const prio = !!payload.priority;
  const fresh = [];
  for (const c of codes) {
    if (!c || c === _mgr.running || _mgr.queue.indexOf(c) >= 0) continue;
    fresh.push(c);
  }
  if (prio) _mgr.queue.unshift(...fresh);   // 앞에 삽입(순서 유지)
  else      _mgr.queue.push(...fresh);      // 뒤에 붙임
  bgEmitQueue();
  if (!_mgr.running) runQueueBG();
  return { ok: true, queued: fresh.length, position: prio ? 1 : _mgr.queue.length };
}
function mgrPause() {
  if (!_mgr.running) return { ok: false, error: "진행 중 아님" };
  if (_mgr.paused) return { ok: true, already: true };
  _mgr.paused = true;
  bgEmit({ type: "bundle-paused", bundle: _mgr.running, level: "warn", msg: "일시중지 — 창 닫는 중 (재개하면 이어서 크롤)" });
  bgEmitQueue();
  return { ok: true };
}
function mgrResume() {
  if (!_mgr.running) return { ok: false, error: "진행 중 아님" };
  if (!_mgr.paused) return { ok: true, already: true };
  _mgr.paused = false;
  bgEmit({ type: "bundle-resumed", bundle: _mgr.running, level: "", msg: "재개 — 이어서 크롤" });
  bgEmitQueue();
  if (_mgr._kick) { try { _mgr._kick(); } catch (_) {} }
  return { ok: true };
}
function mgrStop() {
  if (!_mgr.running && !_mgr.queue.length) return { ok: false, error: "진행 중 아님" };
  _mgr.stopped = true; _mgr.paused = false; _mgr.queue = [];
  bgEmit({ type: "bundle-stopping", bundle: _mgr.running, level: "warn", msg: "중지 — 창 닫고 종료 (긁은 것까지 저장)" });
  if (_mgr._kick) { try { _mgr._kick(); } catch (_) {} }
  bgEmitQueue();
  return { ok: true };
}
function mgrCancel(code) {
  const i = _mgr.queue.indexOf(code);
  if (i >= 0) { _mgr.queue.splice(i, 1); bgEmitQueue(); return { ok: true }; }
  return { ok: false, error: "대기열에 없음" };
}
function mgrSnapshot() {
  return { ok: true, running: _mgr.running, paused: _mgr.paused, stopped: _mgr.stopped,
           queue: _mgr.queue.slice(), view: _mgr.view, base: _mgr.base };
}

// ── 큐 러너 — 모음전을 하나씩 꺼내 순차 크롤. 중지 시 큐 비움. ──
async function runQueueBG() {
  bgKeepaliveStart();
  let crawled = 0;
  try {
    while (_mgr.queue.length) {
      if (_mgr.stopped) break;
      const code = _mgr.queue.shift();
      _mgr.running = code; _mgr.paused = false;
      bgEmitQueue();
      try { await crawlBundleAllBG(code); crawled++; } catch (e) { console.warn("[moum] bundle err", code, e); }
      if (_mgr.stopped) break;
    }
  } finally {
    const wasStopped = _mgr.stopped;
    _mgr.queue = []; _mgr.running = null; _mgr.paused = false; _mgr.stopped = false; _mgr._kick = null;
    bgEmitQueue();
    bgKeepaliveStop();
    try { bgClearPersist(); } catch (_) {}   // 크롤 종료 — 체크포인트 제거(불필요 재가동 방지)
    // [2026-07-06 v0.7.17] 한 패스(전체 URL 1회) 완료 → 서버에 통보(오늘 바퀴 +1).
    //   중지·미크롤이면 안 보냄. 서비스탭 닫기 전에(bgFetch 가 탭 필요).
    if (crawled > 0 && !wasStopped) {
      try { await bgFetch("/api/crawl/pass-done", { method: "POST" }); } catch (_) {}
    }
    await closeServiceTabIfOwned();   // SW 가 띄운 백그라운드 mou-m 탭 정리
  }
}

// ── [2026-07-04] 자동화 워커: 서버 /api/crawl/due-bundles 폴링 → 기존 크롤 큐로 위임 ──
//   검증된 크롤 로직(crawlBundleAllBG·동시성·재시도·로그인세션)을 그대로 재사용한다.
//   서버 enabled 게이트가 이중 안전 — 실행/정지 끄면 빈 목록이 와서 아무것도 안 함.
// [2026-07-05 v0.7.15] MV3 서비스워커는 ~30초 유휴 시 언로드돼 setInterval 이 죽는다
//   → 자동 폴링이 한 번 돌고 멈추던 근본원인(라이브 실증). chrome.alarms 로 전환(잠들어도
//   Chrome 이 SW 를 깨워 폴). moum-keepalive 와 동일한 검증된 방식. (알람 최소주기 1분)
const MOUM_POLL_ALARM = "moum-auto-poll";
async function moumAutoPollOnce() {
  try {
    const r = await bgFetch("/api/crawl/due-bundles").then((x) => x.json());
    if (r && r.enabled && Array.isArray(r.codes) && r.codes.length) {
      mgrEnqueue({ codes: r.codes, base: _mgr.base });   // 기존 큐/동시성/재시도 재사용
    }
  } catch (e) { console.warn("[moum-auto-poll]", e && e.message ? e.message : e); }
  // [2026-08-06 검색필터] 같은 알람에 얹는다 — 알람을 하나 더 만들면 서로 카운트다운을
  //   리셋시키는 사고(0.7.69 주석)의 표면이 넓어진다.
  await moumListingPollOnce();
  await moumLoneUrlPollOnce();
}

// ── [2026-08-07] 구성에 안 걸린 **낱개 주소** 크롤 ──────────────────────────
//   🔴 이게 없어서 검색필터가 넣은 주소 30개가 크롤 4바퀴 도는 동안 하나도 안 긁혔다.
//     위 due-bundles 는 **모음전 코드**만 준다 — 낱개 주소는 어느 구성에도 안 걸려
//     그 목록에 영영 안 들어가고, 에러도 안 난다(조용한 누락).
//   ★ 크롤·저장은 기존 것을 그대로 쓴다 — `crawlItemInTabBG`(8소싱처 라우터) +
//     `/api/sources/crawl-result`(저장). 여기서 새로 만드는 건 「누구를 긁을지」뿐.
const _LONE_MAX_PER_TICK = 5;   // 한 번에 이만큼만 — 알람은 1분마다 다시 온다

let _loneBusy = false;
async function moumLoneUrlPollOnce() {
  if (_loneBusy) return;               // 겹치면 창이 쌓인다
  let due = null;
  try {
    due = await bgFetch("/api/crawl/due-urls").then((x) => x.json());
  } catch (e) { return; }
  if (!due || !due.enabled) return;    // 실행/정지 스위치를 여기서도 지킨다
  const items = (due.items || []).slice(0, _LONE_MAX_PER_TICK);
  if (!items.length) return;

  _loneBusy = true;
  let win = null;
  try {
    win = await handleOpenWin({});
    if (!win.ok) return;
    for (const it of items) {
      try {
        const out = await crawlItemInTabBG(
          win.tabId, null,
          { source_key: it.site, url: it.url, url_type: "dan" }, null);
        // 🔴 결과를 **저장까지** 한다. handleCrawlOne(진단용)은 일부러 저장을 안 하는데,
        //   여기서 그걸 그대로 쓰면 긁어놓고 버리는 꼴이 된다.
        // 🔴 저장은 반드시 `saveItemsBG`(=toItemBG 매핑)를 거친다. 직접 조립하면
        //   혜택·카테고리경로·사진·상세가 통째로 빠진다 — toItemBG 주석이
        //   「이 줄이 빠지면 수집해도 조용히 유실된다」고 못박은 그 자리다.
        if (out && out.status === "ok") {
          const saved = await saveItemsBG([Object.assign({}, out, {
            source_key: it.site, url: it.url,
          })]);
          if (!saved || saved.ok === false) {
            console.warn("[moum-lone] 저장 실패", it.url, saved && saved.error);
          }
        }
      } catch (e) {
        console.warn("[moum-lone]", it.url, e && e.message ? e.message : e);
      }
    }
  } finally {
    if (win && win.winId != null) {
      try { await chrome.windows.remove(win.winId); } catch (_) {}
    }
    _loneBusy = false;
  }
}

// ── [2026-08-06] 검색필터: 리스팅 URL 을 훑어 상품 주소를 캔다 ──────────────
//   대량등록의 입구. 서버는 「어느 주소를 훑을지」만 알려주고(/api/crawl/due-listings)
//   페이지를 여는 일은 여기(로컬 PC)가 한다 — 크롤=로컬 원칙.
//   결과는 /api/crawl/listing-result 로 돌려보낸다.
const _LISTING_PAGE_TIMEOUT_MS = 45000;   // 한 장 여는 데 이만큼 넘으면 포기(무한대기 금지)
const _LISTING_SETTLE_MS = 2500;          // 로드 완료 뒤 목록이 그려질 틈

// 페이지 안에서 실행 — 상품의 **번호만** 긁는다.
//   ★ 규칙(선택자·속성·정규식)은 **서버가 준다**(`/api/crawl/due-listings`).
//     [2026-08-08] 예전엔 여기 `a[href*="/products/"]` 가 박혀 있었다 — 무신사 전용.
//     그래서 서버에 SSF·롯데온 규칙을 넣어도 확장은 무신사 링크만 찾아 **에러 없이
//     0건**이었다. 규칙을 아는 곳이 둘이면 소싱처를 붙일 때마다 확장까지 고쳐야 하고,
//     그때마다 사장님께 「확장 다시 불러오기」를 부탁하게 된다.
//   ★ 요소마다 `속성이름="값"` 꼴 문자열을 만들어 거기에 정규식을 건다. 그래야
//     링크에서 뽑는 곳(무신사·SSF·롯데온)과 **속성에서 뽑는 곳(H몰 `data-slitm-cd`)**이
//     같은 정규식 한 벌로 끝난다. H몰 상품 카드는 `<a href>` 가 아니다(실측).
//   ★ 번호만 보내고 주소 조립은 서버가 한다 — 추적 꼬리표(?srsltid=)가 붙은 채
//     저장되면 같은 상품이 두 벌로 갈린다.
//   ★ [2026-08-08] **「더 있다」를 알아보고 말한다.**
//     처음엔 「무한 스크롤이라 내리면 더 나온다」고 보고 스크롤을 넣었는데 **틀렸다** —
//     롯데온 48→48 · 롯데아이몰 24→24 · 현대H몰 40→40, 화면을 끝까지 내려도
//     (H몰은 안쪽 스크롤 상자까지) 개수가 그대로였다. 셋 다 **단추로 넘기는** 방식이다.
//   🔴 그래서 지금 하는 일은 하나 — 「다음」 단추가 살아 있으면 우리가 첫 장만
//     가져온 것이므로 `capped: true` 로 말한다. 조용히 두면 사장님이
//     「이 검색엔 48개뿐」이라고 믿는다. 단추를 눌러 여러 장을 걷는 건 다음 걸음.
//   ★ 훑기 전에 한 번만 바닥까지 내린다 — 지연 로딩 이미지·단추가 그제야 붙는 곳이 있다.
async function _listingCollectIds(sel, attr, reSrc, moreSel, emptyText, clickPages, nextUrlRe, htmlScan) {
  const seen = new Set();
  // 🔴 받은 글 안의 주소는 JSON 으로 감싸여 있어 `\/` · `&` 로 escape 돼 있다.
  //   풀지 않으면 그 주소로 부를 수 없다.
  // 🔴🔴 여기 있던 식이 **정규식이 아니었다** — `/\\\\//g` 는 JS 가 세 번째 `/` 에서
  //   정규식을 닫아 버려 뒤의 `/g` 가 **정의 안 된 변수 g 로 나누기**가 되고
  //   ReferenceError 를 던졌다. 그게 바깥 `catch (e) {}` 에 삼켜져 다음 쪽 주소가
  //   늘 null 이었다 → 무신사가 첫 쪽 47개만 걷고 「끝남」이라 답했다(2026-08-12 라이브).
  //   ★ 이 함수는 페이지에 **통째로 주입**되므로 바깥 함수를 부를 수 없다 — 안에 둔다.
  function _unescapeJsonUrl(s) {
    return String(s).replace(/\\u0026/g, '&').replace(/\\\//g, '/');
  }
  let re;
  try { re = new RegExp(reSrc); } catch (e) { return { ids: [], capped: false }; }

  try { window.scrollTo(0, document.body.scrollHeight); } catch (e) {}
  await new Promise((r) => setTimeout(r, 900));

  // 🔴🔴 소싱처 대부분이 **결과가 0건이어도 추천 상품을 화면에 깐다.**
  //   그대로 두면 오타 한 번에 엉뚱한 상품 수십 건이 크롤 대기에 들어가 초안까지 된다
  //   (실측: 롯데온 25 · 롯데아이몰 25 · 현대H몰 12 — 전부 「없습니다」 화면에서).
  if (emptyText) {
    try {
      if ((document.body.innerText || '').indexOf(emptyText) >= 0) {
        return { ids: [], capped: false };
      }
    } catch (e) {}
  }

  // 🔴 H몰은 **화면이 아니라 받은 글**에서 읽는다 — 서버가 보낸 쪽과 화면이
  //   그리는 쪽이 다르다(page=3 을 열면 화면은 1쪽 36개, 받은 글은 3쪽 36개, 겹침 0).
  //   화면만 보면 6쪽을 열어도 늘 같은 36개다(2026-08-08 라이브에서 드러남).
  const sweep = () => {
    if (htmlScan) {
      let mm; const rg = new RegExp(reSrc, 'g');
      const h = document.documentElement.innerHTML;
      while ((mm = rg.exec(h)) !== null) { if (mm[1]) seen.add(mm[1]); }
      return;
    }
    document.querySelectorAll(sel).forEach((el) => {
      const v = el.getAttribute(attr);
      if (v == null) return;
      const m = (attr + '="' + String(v) + '"').match(re);
      if (m && m[1]) seen.add(m[1]);
    });
  };
  sweep();
  let capped = false;

  // ★ 응답이 **스스로 다음 쪽 주소를 주는 곳**은 그 주소를 따라간다(무신사).
  //   🔴 주소를 우리가 조립하면 안 된다 — `hmacId` 서명이 붙어 있어 `page=2` 로
  //     손수 바꿔 부르면 403 「잘못된 접근입니다」가 온다(실측).
  //   실측: 무신사 나이키 41쪽 2,412개(쪽당 60개). `page=` 는 서버가 무시한다.
  if (nextUrlRe) {
    let re2; try { re2 = new RegExp(nextUrlRe); } catch (e) { re2 = null; }
    let url = null;
    try {
      const m0 = document.documentElement.innerHTML.match(re2);
      if (m0 && m0[1]) url = _unescapeJsonUrl(m0[1]);
    } catch (e) {}
    const want = Math.max(1, Number(clickPages) || 1);
    // 🔴 「여러 쪽을 시켰는데 다음 쪽 주소를 못 찾았다」는 **끝난 것이 아니다.**
    //   조용히 두면 첫 쪽 47개를 걷고 「끝남·더 없음」이라 답한다 — 사장님은
    //   「이 검색엔 47개뿐」이라고 믿는다(2026-08-12 라이브에서 실제로 그랬다).
    if (want > 1 && !url) capped = true;
    for (let i = 1; i < want && url; i++) {
      try {
        const rr = await fetch(url, { credentials: 'include' });
        if (!rr.ok) { capped = true; break; }      // 못 받은 것도 「다 못 봤다」
        const txt = await rr.text();
        // 상품번호는 같은 규칙으로 뽑는다(규칙 한 벌 원칙).
        let n = 0, mm; const rg = new RegExp(reSrc, 'g');
        while ((mm = rg.exec(txt)) !== null) { if (mm[1]) { seen.add(mm[1]); n++; } }
        const m2 = txt.match(re2);
        url = (m2 && m2[1]) ? _unescapeJsonUrl(m2[1]) : null;
        // 🔴 **한 개도 없는 쪽이 나왔으면 끝난 것이다.** 여기서 그냥 빠져나오면
        //   `url` 이 남아 있어 아래에서 「더 있음」이 켜진다 — 다 걷었는데도
        //   「아직 더 있다」는 거짓말이다(2026-08-13 라이브 무신사: 21쪽에서 끝나
        //   22쪽이 0개인데 「더 있음」이 켜져 있었다. 무신사는 마지막 쪽 뒤에도
        //   nextPageUrl 을 계속 준다).
        //   ★ 「덜 걷고 끝났다 하기」와 「다 걷고 더 있다 하기」는 **둘 다 거짓말**이다.
        if (!n) { url = null; break; }               // 안 늘면 그만 (헛돌기 방지)
        await new Promise((r) => setTimeout(r, 700));
      } catch (e) { capped = true; break; }
    }
    if (url) capped = true;                         // 아직 다음 쪽이 남아 있다
    return { ids: Array.from(seen), capped: capped };
  }

  // ★ 단추로 넘기는 곳은 **「다음」을 눌러 가며** 걷는다(롯데온·롯데아이몰).
  //   주소로도 스크롤로도 못 넘기는 곳이라 이 길이 유일하다.
  //   🔴 몇 번 누를지는 **서버가 준다**(사장님이 적은 「몇 쪽부터~까지」 그대로).
  //     여기서 임의로 늘리면 사장님이 안 시킨 만큼 소싱처를 두들긴다(차단 위험).
  const rounds = Math.max(0, (Number(clickPages) || 1) - 1);
  const nextBtn = () => { try { return document.querySelector(moreSel); } catch (e) { return null; } };
  for (let i = 0; i < rounds; i++) {
    const b = moreSel ? nextBtn() : null;
    if (!b) break;                       // 마지막 장 — 단추가 사라진다
    const before = seen.size;
    try { b.click(); } catch (e) { break; }
    await new Promise((r) => setTimeout(r, 2500));   // 새 장이 그려질 틈
    sweep();
    // 🔴 눌렀는데 안 늘면 넘어가지 않은 것이다 — 계속 누르면 같은 장을 헛돈다.
    if (seen.size === before) break;
  }

  // 「더 있다」 — 선택자를 모르는 소싱처는 false 다(추측해서 켜지 않는다).
  //   ★ 마지막 장까지 갔으면 단추가 사라져 자연히 false 가 된다.
  if (moreSel) {
    try { capped = !!nextBtn(); } catch (e) {}
  }
  return { ids: Array.from(seen), capped: capped };
}

// ── 「다음」 단추로 넘기는 곳 전용 — **한 걸음씩 짧게** ──────────────────
//   🔴🔴 왜 나눴나 (2026-08-13)
//   예전엔 「눌렀다 훑었다」를 **한 번의 긴 주입 안에서** 다 했다. 그래서
//     ① 시한을 넘기면 **그때까지 걷은 것이 통째로 사라졌다**(라이브 롯데온·아이몰:
//        60쪽을 시켰더니 「훑는 중 시간 초과」 + 새로 걷은 것 0개)
//     ② 「다음」이 **진짜 페이지 이동**이면 주입된 코드가 함께 죽어 영영 안 돌아왔다
//   → 이제 **한 걸음마다 따로 주입**한다. 배경(서비스워커)이 결과를 들고 있으므로
//     페이지가 갈아 끼워지든 통째로 이동하든 **걷은 것은 남는다.**
function _listingSweepInPage(sel, attr, reSrc, htmlScan, emptyText) {
  const out = [];
  try {
    if (emptyText && (document.body.innerText || '').indexOf(emptyText) >= 0) {
      return { empty: true, ids: [] };
    }
  } catch (e) {}
  try {
    if (htmlScan) {
      const rg = new RegExp(reSrc, 'g');
      const h = document.documentElement.innerHTML;
      let mm; while ((mm = rg.exec(h)) !== null) { if (mm[1]) out.push(mm[1]); }
    } else {
      const re = new RegExp(reSrc);
      document.querySelectorAll(sel).forEach((el) => {
        const v = el.getAttribute(attr);
        if (v == null) return;
        const m = (attr + '="' + String(v) + '"').match(re);
        if (m && m[1]) out.push(m[1]);
      });
    }
  } catch (e) {}
  return { empty: false, ids: out };
}

function _listingClickNextInPage(moreSel) {
  try {
    const b = document.querySelector(moreSel);
    if (!b) return { clicked: false, hasNext: false };
    b.click();
    return { clicked: true, hasNext: true };
  } catch (e) { return { clicked: false, hasNext: false }; }
}

function _listingHasNextInPage(moreSel) {
  try { return !!document.querySelector(moreSel); } catch (e) { return false; }
}

//: 「다음」을 누른 뒤 **화면이 실제로 바뀔 때까지** 지켜본다.
//   🔴 고정 시간으로 기다리면 두 가지가 다 나쁘다 — 짧으면 같은 쪽을 읽고
//     「안 늘었다」며 멈추고(라이브 아이몰이 그랬다), 길면 쪽마다 그만큼 느려진다.
//   ★ 첫 상품번호가 바뀌면 다시 그려진 것이다. 안 바뀌면 시한까지 지켜본다.
async function _listingWaitPageChanged(tabId, rule, maxMs) {
  const first = async () => {
    try {
      const r = await chrome.scripting.executeScript({
        target: { tabId }, func: _listingSweepInPage,
        args: [rule.sel, rule.attr, rule.id_re, rule.html_scan || null, null],
      });
      const got = (r && r[0] && r[0].result) || null;
      return (got && got.ids && got.ids.length) ? got.ids[0] : null;
    } catch (e) { return null; }
  };
  const before = await first();
  const t0 = Date.now();
  while (Date.now() - t0 < maxMs) {
    await new Promise((r) => setTimeout(r, 500));
    const now = await first();
    if (now && now !== before) return true;          // 다시 그려졌다
  }
  return false;                                       // 안 바뀜 — 부르는 쪽이 판단
}

async function _listingWalkByClicks(tabId, rule, budgetMs) {
  const want = Math.max(1, Number(rule.click_pages) || 1);
  const seen = new Set();
  let capped = false, empty = false;
  const deadline = Date.now() + budgetMs;
  const exec = async (fn, args) => {
    const r = await chrome.scripting.executeScript({ target: { tabId }, func: fn, args: args });
    return (r && r[0] && r[0].result) || null;
  };

  // 🔴 **이어서 걷기** — 걷기 전에 정해진 횟수만큼 눌러 건너뛴다.
  //   「다음」 단추로만 넘어가는 곳은 늘 1쪽에서 시작해야 해서 이 방법뿐이다.
  //   ★ 건너뛸 때는 **훑지 않는다** — 훑는 값이 없으니 훨씬 빠르다.
  //   ★ 시한에 걸리면 걷지도 못하고 나오지만, 그때도 「더 있음」이라 말한다
  //     (조용히 「끝남」이 되면 사장님이 그 뒤 상품을 영영 못 본다).
  const skip = Math.max(0, Number(rule.click_skip) || 0);
  for (let k = 0; k < skip; k++) {
    if (Date.now() > deadline) { capped = true; break; }
    const c = await exec(_listingClickNextInPage, [rule.more_sel]);
    if (!c || !c.clicked) break;            // 단추가 사라짐 = 더 갈 곳이 없다
    await _notionWaitTab(tabId, 20000);
    // 건너뛸 때도 **바뀔 때까지** 지켜본다 — 안 바뀐 채 다음을 누르면
    // 같은 자리를 헛돌며 「건너뛰었다」고 착각한다.
    await _listingWaitPageChanged(tabId, rule, 9000);
  }
  if (capped) return { ids: [], capped: true };

  for (let i = 0; i < want; i++) {
    const got = await exec(_listingSweepInPage,
      [rule.sel, rule.attr, rule.id_re, rule.html_scan || null, rule.empty_text || null]);
    if (got && got.empty) { empty = true; break; }
    const before = seen.size;
    (got && got.ids ? got.ids : []).forEach((x) => seen.add(x));
    // 🔴 개수 상한에 걸려 자른 것도 「다 못 봤다」다.
    if (rule.max_items && seen.size >= rule.max_items) { capped = true; break; }
    // 🔴 눌렀는데 안 늘면 넘어가지 않은 것이다 — 같은 장을 헛돌지 않는다.
    if (i > 0 && seen.size === before) break;
    if (i === want - 1) break;                       // 시킨 만큼 다 봤다
    // 🔴 **시한이 다가오면 걷은 것을 들고 나온다.** 통째로 버리지 않는다.
    if (Date.now() > deadline) { capped = true; break; }
    const c = await exec(_listingClickNextInPage, [rule.more_sel]);
    if (!c || !c.clicked) break;                     // 단추가 사라짐 = 마지막 장
    // 화면만 갈아 끼우는 곳과 진짜 이동하는 곳을 **둘 다** 견딘다.
    await _notionWaitTab(tabId, 20000);
    // 🔴🔴 **고정 시간으로 기다리면 안 된다.** 1.2초를 기다렸더니 롯데아이몰이
    //   아직 다시 그리기 전이라 같은 쪽을 읽고 「안 늘었다」며 첫 쪽에서 멈췄다
    //   (2026-08-13 라이브: 60쪽을 시켰는데 새로 걷은 것 0개).
    //   손으로 잴 때 3.5초를 기다린 것이 우연히 넉넉했을 뿐이다.
    // ★ **바뀔 때까지 지켜본다** — 화면이 바뀌면 바로 넘어가고(빠르다),
    //   느린 소싱처도 놓치지 않는다(정확하다). 둘 다 얻는다.
    await _listingWaitPageChanged(tabId, rule, 9000);
  }
  // 아직 「다음」이 살아 있으면 더 있는 것이다.
  if (!empty && !capped) {
    try { if (await exec(_listingHasNextInPage, [rule.more_sel])) capped = true; } catch (e) {}
  }
  return { ids: Array.from(seen), capped: capped };
}

async function _listingScanOnePage(url, rule) {
  const tab = await chrome.tabs.create({ url: url, active: false });
  if (!tab || tab.id == null) throw new Error("탭 생성 실패");
  const tabId = tab.id;
  // ★ 재우기 금지 — 크롬 메모리 세이버가 백그라운드 탭을 재우면 executeScript 가
  //   영영 안 돌아온다(0.7.75 에서 정산이 이걸로 죽었다). 같은 함정을 한 곳만 막으면
  //   남은 곳이 터진다.
  _pinTab(tabId);
  try {
    const ok = await _notionWaitTab(tabId, _LISTING_PAGE_TIMEOUT_MS);
    if (!ok) throw new Error("페이지 로드 시간 초과");
    await new Promise((r) => setTimeout(r, _LISTING_SETTLE_MS));
    // 🔴 주입에 **따로 시한**을 둔다. 페이지 로드 시한(위)은 주입이 도는 동안을
    //   안 덮는다 — 여기가 무한대기가 되면 필터 하나가 폴링을 통째로 잡는다.
    // 🔴🔴 **건너뛸 쪽도 예산에 넣는다.** 이어서 걷기가 깊어질수록 건너뛸 횟수가
    //   늘어난다(121쪽부터면 120번). 예산이 걷는 몫만 세면 **건너뛰다 시한이 끝나
    //   한 건도 못 걷고**, 그러면 「새로 걷은 것 0」이라 자동 이어걷기가 멈춘다 —
    //   앞으로 나아가지 못하고 그 자리에서 굳는다(2026-08-13 아이몰에서 예상됨).
    // ★ 건너뛰기는 훑지 않아 걷기보다 빠르므로 쪽당 3초로 잡는다.
    const _skipN = Math.max(0, Number(rule.click_skip) || 0);
    const budget = 20000
      + Math.max(0, (Number(rule.click_pages) || 1) - 1) * 6000
      + _skipN * 3000;
    let got = null;
    if (rule.more_sel) {
      // 「다음」 단추로 넘기는 곳 — **한 걸음씩 따로 주입**한다(위 주석 참조).
      //   배경이 결과를 들고 있어 시한이 와도 걷은 것을 잃지 않는다.
      got = await _listingWalkByClicks(tabId, rule, budget);
    } else {
      const out = await Promise.race([
        chrome.scripting.executeScript({
          target: { tabId }, func: _listingCollectIds,
          args: [rule.sel, rule.attr, rule.id_re, rule.more_sel || null,
                 rule.empty_text || null, Number(rule.click_pages) || 1,
                 rule.next_url_re || null, rule.html_scan || null],
        }),
        new Promise((_r, rej) => setTimeout(
          () => rej(new Error("훑는 중 시간 초과")), budget)),
      ]);
      got = (out && out[0] && out[0].result) || null;
    }
    if (got && (!got.ids || !got.ids.length)) {
      // 🔴 0건이면 **무엇을 봤는지**를 같이 돌려준다. 그냥 0이라고만 하면
      //   「그 검색엔 상품이 없다」와 「규칙이 안 맞는다」가 구분이 안 된다.
      try {
        const probe = await chrome.scripting.executeScript({
          target: { tabId }, args: [rule.sel, rule.id_re],
          func: (s, idRe) => {
            // 🔴 「링크는 있는데 우리 선택자엔 0개」까지 알아도 **고칠 수가 없다** —
            //   그 화면의 링크가 어떤 모양인지를 모르기 때문이다. SSG 는 브라우저
            //   도구로 열 수 없어(정책 차단) 내 눈으로 못 본다 → 확장이 대신 본다.
            //   ★ 링크 주소를 통째로 보내지 않는다. **경로 모양만** 센다
            //     (숫자는 `#` 로 뭉갠다) — 어느 모양이 상품인지 고르기엔 충분하다.
            const cnt = {};
            document.querySelectorAll('a[href]').forEach((a) => {
              let p;
              try { p = new URL(a.getAttribute('href'), location.href).pathname; }
              catch (e) { return; }
              p = p.replace(/\d+/g, '#');
              cnt[p] = (cnt[p] || 0) + 1;
            });
            const top = Object.keys(cnt).sort((x, y) => cnt[y] - cnt[x]).slice(0, 5)
              .map((k) => k + '×' + cnt[k]);
            // 🔴 **「받은 글에는 있나」를 같이 답한다.** 화면에 없다고 안 온 것이 아니다 —
            //   현대H몰이 그랬다(화면 1쪽 / 받은 글 3쪽, 겹침 0). 이 숫자가 크면
            //   답은 `html_scan` 이고, 이것도 0이면 그 화면엔 정말 상품이 없는 것이다.
            //   ★ 이 한 줄이 없어서 H몰 때 「진짜 마우스 휠」을 며칠 쫓았다.
            let inHtml = -1;
            try {
              const h = document.documentElement.innerHTML;
              const rg = new RegExp(idRe, 'g');
              const seen2 = new Set();
              let mm; while ((mm = rg.exec(h)) !== null) { if (mm[1]) seen2.add(mm[1]); }
              inHtml = seen2.size;
            } catch (e) {}
            return { 링크수: document.querySelectorAll('a[href]').length,
                     선택자수: (() => { try { return document.querySelectorAll(s).length; } catch (e) { return -1; } })(),
                     제목: (document.title || '').slice(0, 40),
                     받은글: inHtml,
                     링크모양: top.join(' , ') };
          },
        });
        const d = probe && probe[0] && probe[0].result;
        if (d) got.diag = '0건(' + d.제목 + ' · 링크 ' + d.링크수
          + ' · 선택자 ' + d.선택자수
          + ' · 받은글 ' + d.받은글
          + (d.링크모양 ? ' · 많은 모양 ' + d.링크모양 : '') + ')';
      } catch (e) {}
    }
    return got || { ids: [], capped: false };
  } finally {
    try { await chrome.tabs.remove(tabId); } catch (_) {}
  }
}

let _listingBusy = false;
let _listingBusyAt = 0;
//: 훑기가 아무리 길어도 이 시간을 넘기면 **걸린 것**으로 본다.
//   60쪽×6초 + 건너뛰기까지 넉넉히 담고도 남는 값이다.
const _LISTING_BUSY_MAX_MS = 30 * 60 * 1000;   // 30분

async function moumListingPollOnce() {
  // 🔴🔴 **잠금이 영영 안 풀리면 훑기가 통째로 멈춘다.**
  //   라이브에서 실제로 겪었다(2026-08-13): 새 필터를 걸어도 「한 번도 실행되지
  //   않음」인 채로 수십 분이 지났다. 확장은 살아서 다른 청에는 답하는데 훑기만
  //   안 돌았다 — 어딘가에서 죽은 회차가 `_listingBusy` 를 쥔 채였다.
  //   (`finally` 가 있어도 그 사이 SW 가 죽었다 되살아나는 등 빠져나가는 길이 있다.)
  // ★ 「한 번에 하나」는 지키되, **너무 오래 쥐고 있으면 놓아 준다.**
  //   정산 회차가 같은 함정에 빠져 30분 감시를 단 것과 같은 처방이다(0.7.72).
  if (_listingBusy && (Date.now() - _listingBusyAt) > _LISTING_BUSY_MAX_MS) {
    console.warn('[moum-listing] 훑기 잠금이 30분을 넘겨 풀어 줍니다(걸린 회차로 봄)');
    _listingBusy = false;
  }
  if (_listingBusy) return;              // 한 번에 하나만 — 겹치면 탭이 쌓인다
  let due = null;
  try {
    due = await bgFetch("/api/crawl/due-listings").then((x) => x.json());
  } catch (e) { return; }
  const jobs = (due && Array.isArray(due.listings)) ? due.listings : [];
  if (!jobs.length) return;

  _listingBusy = true;
  _listingBusyAt = Date.now();          // 언제부터 쥐고 있나 — 걸림 판정의 근거
  // 🔴 심장박동 — MV3 SW 는 30초 조용하면 크롬이 죽인다. 단추를 눌러 가며 여러 장을
  //   걷는 동안(20쪽이면 1분 반) SW 가 죽으면 훑기가 **기록도 없이 증발**한다.
  //   정산 회차가 2026-08-04 에 이걸로 죽었던 것과 같은 함정이다(0.7.73).
  const _lka = setInterval(() => {
    try { chrome.storage.local.get("__moum_ka", () => { void chrome.runtime.lastError; }); } catch (_) {}
  }, 20000);
  try {
    for (const job of jobs) {
      const ids = new Set();
      let err = job.error || "";
      const _diag = [];   // 0건일 때 「무엇을 봤는지」 — 조용한 0건 금지
      // 🔴 두 번 다 실패한 쪽의 주소. 서버가 이걸 알아야 **다시 걸 수 있다.**
      //   없으면 그 쪽 상품이 통째로 빠진 채 「끝남」이 된다(H몰 16% 실측).
      const _missed = [];
      // 🔴 규칙이 안 왔으면 **훑지 않는다.** 예전 규칙으로 대신 훑으면 엉뚱한 번호를
      //   긁어 놓고 「수집됨」이라 말하게 된다 — 0건보다 나쁘다.
      const rule = (job.sel && job.attr && job.id_re)
        ? { sel: job.sel, attr: job.attr, id_re: job.id_re,
            more_sel: job.more_sel, empty_text: job.empty_text,
            click_pages: job.click_pages, next_url_re: job.next_url_re,
            click_skip: job.click_skip,   // 이어서 걷기 — 걷기 전에 눌러 건너뛸 횟수
            max_items: job.max_items, html_scan: job.html_scan } : null;
      let capped = false;   // 「더 있는데 멈췄다」 — 실패와 다른 사실
      if (!rule && !err) {
        err = "서버가 훑기 규칙을 안 줬습니다(서버가 예전 판일 수 있습니다)";
      }
      // ★ 확장 판 번호를 늘 실어 보낸다 — 「화면만 새로고침」해서 본체가 옛 판인
      //   경우를 서버가 알아볼 수 있어야 한다(2026-08-08 실제로 그걸로 헤맸다).
      const _ver = MOUM_EXT_VERSION;
      // 🔴 **마지막 쪽에서도 새 상품이 나왔으면 「끝난 것」이 아니다.**
      //   사장님이 적은 만큼만 열고 멈춘 것뿐인데 「더 있음」이 꺼져 있으면
      //   걷은 수가 전부로 읽힌다(2026-08-12 라이브 H몰: 60쪽 2,159개를 걷고
      //   「끝남」이라 답했는데 그 검색엔 16,413개가 있다).
      let _newOnLastPage = 0;
      for (const pageUrl of (rule ? (job.page_urls || []) : [])) {
        try {
          const res = await _listingScanOnePage(pageUrl, rule);
          if (res.capped) capped = true;
          if (res.diag) _diag.push(res.diag);
          _newOnLastPage = 0;
          for (const id of res.ids) {
            if (!ids.has(id)) _newOnLastPage++;
            ids.add(id);
            // 🔴 개수 상한에 걸려 자른 것도 「다 못 봤다」다 — 조용히 자르지 않는다.
            if (job.max_items && ids.size >= job.max_items) { capped = true; break; }
          }
        } catch (e) {
          // 🔴🔴 **한 번 더 열어 본다.** 탭이 열리다 죽는 것(「페이지 로드 시간 초과」·
          //   「No tab with id」)은 크롬이 바쁠 때 나는 **일시적인 실패**다.
          //   그냥 넘기면 그 쪽 상품이 통째로 빠지는데, 지금 구조는 **어느 쪽을
          //   못 걸었는지 기억하지 않아** 다시 걸을 방법이 없다.
          //   라이브 실측(2026-08-13): 현대H몰 463쪽 중 16%(2,748개)가 이렇게 비었다.
          let _retried = false;
          try {
            await new Promise((r) => setTimeout(r, 2500));   // 크롬이 숨 돌릴 틈
            const res2 = await _listingScanOnePage(pageUrl, rule);
            if (res2.capped) capped = true;
            if (res2.diag) _diag.push(res2.diag);
            _newOnLastPage = 0;
            for (const id of res2.ids) {
              if (!ids.has(id)) _newOnLastPage++;
              ids.add(id);
              if (job.max_items && ids.size >= job.max_items) { capped = true; break; }
            }
            _retried = true;
          } catch (e2) {
            // 두 번 다 실패 — 이제야 「못 봤다」다.
            err = (err ? err + " / " : "")
                + (e && e.message ? e.message : String(e)) + '(2회 실패)';
            // 🔴 어느 쪽을 못 걸었는지 **번호를 남긴다.** 이게 없으면 다시 걸 수 없다.
            _missed.push(pageUrl);
          }
          // 🔴🔴 실패한 장은 **다 못 본 것**이다. 여태 여기서 capped 를 안 켜서
          //   「훑는 중 시간 초과」인데도 화면엔 「끝남」으로 떴다 — 사장님은
          //   「이 검색엔 289개뿐」이라고 믿는다(2026-08-12 라이브 롯데온·아이몰).
          //   사유를 적는 것과 「다 못 봤다」고 말하는 것은 **다른 일**이다.
          if (!_retried) capped = true;
        }
        // 남은 페이지를 안 열고 끝내는 것도 「다 못 봤다」다.
        if (job.max_items && ids.size >= job.max_items) { capped = true; break; }
      }
      // 🔴 마지막 쪽까지 새 상품이 나오는 중이었다 → 아직 끝이 아니다.
      //   ★ 여러 쪽을 연 경우에만 본다. 한 쪽짜리(단추로 넘기는 곳 등)는
      //     그 안에서 이미 자기 방식으로 「더 있음」을 판정한다.
      if ((job.page_urls || []).length > 1 && _newOnLastPage > 0) capped = true;
      // ★ **번호만 보낸다.** 주소 조립은 서버(listing_discover)가 한다 — 소싱처마다
      //   주소 모양이 다른데 여기서 조립하면 규칙을 아는 곳이 두 곳이 되고,
      //   다음 소싱처를 붙일 때 확장도 같이 고쳐야 한다(재로드 부탁이 또 생긴다).
      try {
        await bgFetch("/api/crawl/listing-result", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filter_id: job.filter_id, ids: Array.from(ids),
                                 capped: capped, ext_version: _ver,
                                 diag: _diag.length ? _diag.join(' / ') : undefined,
                                 // 두 번 다 실패한 쪽 — 서버가 다시 걸 수 있게.
                                 missed: _missed.length ? _missed : undefined,
                                 error: err || undefined }),
        });
      } catch (e) { console.warn("[moum-listing] 결과 전송 실패", e); }
    }
  } finally { clearInterval(_lka); _listingBusy = false; }
}

function moumAutoPollStart() {
  moumAutoPollOnce();   // 즉시 1회
  try { chrome.alarms.create(MOUM_POLL_ALARM, { periodInMinutes: 1 }); } catch (_) {}
}
function moumAutoPollStop() {
  try { chrome.alarms.clear(MOUM_POLL_ALARM); } catch (_) {}
}
// 알람 발화 → 폴 1회 (SW 가 잠들었다 깨어난 경우에도 실행)
try {
  chrome.alarms.onAlarm.addListener((a) => { if (a && a.name === MOUM_POLL_ALARM) moumAutoPollOnce(); });
} catch (_) {}

// [2026-08-04] 폰 리모컨 — 크롤 폴링을 항상 켜 둔다.
//   예전엔 PC 자동화 화면의 실행 버튼만 이 알람을 만들었다. 그래서 크롤이 멈춰 있으면
//   확장이 서버를 아예 안 불러 ①폰에서 시작시킬 수 없고 ②서버가 PC 생존을 알 수 없었다.
//   ★크롤 동작 자체는 안 바뀐다 — 서버 enabled 게이트가 이중 안전(꺼져 있으면 빈 목록).
//   ⚠️ 다만 부수효과가 하나 있다(주석이 거짓말하면 안 되니 적어 둔다): 폴링은
//     bgFetch → ensureServiceTab 을 타는데, 열린 mou-m 탭이 하나도 없으면 백그라운드
//     탭을 하나 만든다(위 ensureServiceTab 끝). 그런데 closeServiceTabIfOwned 는
//     runQueueBG·정산·노션 경로에만 있고 **자동 폴링 경로엔 없다** → 그 탭이 상주한다.
//     예전엔 화면에서 실행을 눌러야 알람이 생겨 그 시점엔 이미 mou-m 탭이 있었다.
//     크롤 PC 는 세션이 살아 있는 편이 이득이라(로그인 유지) 그대로 둔다 — 노션 캡처
//     알람도 같은 방식이다. 탭 1개가 문제가 되면 그때 폴링 전용 fetch 경로를 판다.
//   ★alarms.create 는 같은 이름이 있으면 취소·대체한다. MV3 SW 는 다른 알람·메시지로도
//     수시로 깨는데, 깰 때마다 이 줄이 다시 돌면 카운트다운이 매번 리셋돼 영영 안 터질
//     수 있다(내가 넣은 알람이 내 손에 굶어 죽는 꼴). → 없을 때만 만든다.
try {
  chrome.alarms.get(MOUM_POLL_ALARM, (a) => {
    if (!a) { try { chrome.alarms.create(MOUM_POLL_ALARM, { periodInMinutes: 1 }); } catch (_) {} }
  });
} catch (_) {}
// 크롬을 켜자마자(또는 확장을 새로 로드하자마자) 딱 1회 — 알람 첫 발화까지 최대 60초 동안
//   폰에 '⚪ PC 꺼져 있음'이 뜨는 공백을 없앤다.
//   ★최상위에서 그냥 부르면 안 된다 — MV3 SW 는 ~30초 유휴에 언로드되고 다른 알람·메시지로
//     다시 깨는데, 그때마다 최상위가 재실행돼 폴링 주기가 통제 불능이 된다. 시작 시점 한정.
try {
  chrome.runtime.onStartup.addListener(() => moumAutoPollOnce());
  chrome.runtime.onInstalled.addListener(() => moumAutoPollOnce());
} catch (_) {}

// ══════════════════════════════════════════════════════════════════════════
//  [2026-07-17] 정산 「자동 반복」을 확장으로 이관 — 탭을 닫아도 돈다
//   예전엔 스케줄·순회가 전부 크롤-로그인 페이지 안에 있어 그 탭을 닫으면 멈췄다. 여기로
//   옮기면 자동화(소싱처) 폴링과 같은 구조가 된다 — chrome.alarms 가 SW 를 깨우고, 서버
//   호출이 필요하면 bgFetch 가 mou-m 탭을 재사용하거나 없으면 임시로 하나 띄웠다 닫는다.
//   ★크롤=로컬 원칙 유지(서버 크롤 아님 — 이 PC 브라우저 세션으로 수집).
//   ★스케줄 진실 원천은 여기 한 곳. 페이지는 토글·표시만 하고 자기 타이머를 안 돌린다
//    (둘 다 돌면 같은 회차가 두 번 = 중복 크롤).
//   ★설정은 storage.local — 크롬을 껐다 켜도 남는다. (크롤 체크포인트가 쓰는 storage.session
//    과 다르다. 저건 '중단된 크롤 이어하기'라 재부팅 후 재개가 오히려 위험해서 세션 한정.)
// ══════════════════════════════════════════════════════════════════════════
const MOUM_SETTLE_ALARM = "moum-settle-auto";
const _SETTLE_KEY = "moum_settle_auto";
// ★[2026-08-02] 회차 창을 2단으로 — 「창 밖으로 나간 뒤 확정된 정산」을 영영 못 보던 것.
//   예전엔 settleRunOnce 가 since/until 없이 불러 handleLotteonAccountCollect 기본값
//   (최근 60일)만 훑었다. 롯데온 정산은 구매확정 뒤에 확정되는데, 확정이 그 60일을
//   지나서 오면 그 주문은 다시 볼 기회가 없어 0/공란으로 고착한다.
//   라이브 실측(2026-08-02, 저장분 2026-03~07): 롯데온 주문 1,806건 중 실정산 891(49%)·
//   추정 305·없음 610. 결손 915건을 크롤 유무로 가르면 **크롤없음 874건**(크롤0원 38 ·
//   크롤양수 3) — 원인은 크롤 버그가 아니라 「창이 안 닿았다」 하나였다.
//   크롤 저장분 월별 양수도 4월 0 · 5월 0 · 6월 1 · 7월 227 로 최근만 살아 있었다.
//   → 매 회차는 얕게(SHALLOW), 하루 한 번은 깊게(DEEP). 자동만 켜두면 과거도 저절로 메워진다.
const _SETTLE_SHALLOW_DAYS = 60;    // 매 회차 — 가볍게(계정 7개 직렬이라 회차가 길면 안 됨)
const _SETTLE_DEEP_DAYS = 180;      // 하루 1회 — 뒤늦게 확정된 옛 정산 회수
const _SETTLE_DEEP_EVERY_MS = 24 * 60 * 60 * 1000;
const _SETTLE_DEFAULT = { on: false, min: 60, nextAt: 0, base: "", last: null, deepAt: 0, hist: [], startPfx: "" };
let _settleRunning = false;
let _settleRunAt = 0;    // 도는 회차의 시작 시각 — 아래 감시가 「몇 분째 붙잡혀 있나」를 잰다
let _settleGen = 0;      // 강제 중단 세대표 — 감시가 끊은 옛 회차가 계속 나아가지 못하게
// ★[2026-08-04] 한 회차 상한 — 정상 회차는 7계정 직렬 ~14분. 이걸 넘겨 붙잡혀 있으면
//   「걸렸다」로 보고 내려놓는다. 이 감시가 없으면 걸린 회차(롯데온 페이지 무한 대기 등)가
//   _settleRunning 을 영영 쥔 채 SW 를 붙들어, 틱이 매번 busy 로 빠져 회차를 1~2시간씩
//   걸렀다(2026-08-04 실측: 17:10 다음 회차가 19:56).
//   ★[2026-08-06] 30 → 40분. 감시가 「회차를 끝내는 정상 수단」이 되어 있었다(하루 4회 발동,
//   실측 2026-08-06). 감시가 끊으면 계정별 기록이 안 남아 어디서 막혔는지도 모른다.
//   이제 회차 스스로 25분(_SETTLE_RUN_BUDGET_MS) 안에 끝맺고 정직한 기록을 남기므로,
//   감시는 그마저도 안 될 때만 도는 **진짜 최후 안전장치**로 물러난다.
const _SETTLE_STUCK_MS = 40 * 60 * 1000;
// 회차 스스로의 예산 — 이 시간을 넘기면 남은 계정을 「순서가 못 옴」으로 정직히 기록하고 끝낸다.
//   (감시에 끊기면 기록이 통째로 없다 = 어느 계정이 왜 빠졌는지 영영 모른다.)
const _SETTLE_RUN_BUDGET_MS = 25 * 60 * 1000;

// 오늘부터 days 일 전까지의 YYYYMMDD 창. handleLotteonAccountCollect 가 받는 형식.
function _settleWindow(days) {
  const d = new Date(); d.setDate(d.getDate() - days);
  const p = (n) => (n < 10 ? "0" : "") + n;
  const ymd = (x) => "" + x.getFullYear() + p(x.getMonth() + 1) + p(x.getDate());
  return { since: ymd(d), until: ymd(new Date()) };
}

function settleLoad() {
  return new Promise((res) => {
    try {
      chrome.storage.local.get(_SETTLE_KEY, (o) => {
        void chrome.runtime.lastError;
        res(Object.assign({}, _SETTLE_DEFAULT, (o && o[_SETTLE_KEY]) || {}));
      });
    } catch (_) { res(Object.assign({}, _SETTLE_DEFAULT)); }
  });
}
function settleSave(st) {
  return new Promise((res) => {
    try { chrome.storage.local.set({ [_SETTLE_KEY]: st }, () => { void chrome.runtime.lastError; res(); }); }
    catch (_) { res(); }
  });
}
// ★[2026-08-05] 회차 이력 — 화면(기록)이 자동 회차를 한 줄도 못 적던 것.
//   기록은 페이지가 제 손으로 돌린 회차만 적어서, 자동을 확장으로 옮긴 뒤로는
//   「최근 22:40」인데 기록 마지막이 어제 00:07 인 모순이 났다(2026-08-05 실측).
//   이력의 주인은 회차의 주인(확장) — 화면이 꺼져 있어도 여기엔 남는다. 최근 60회.
//   강제 중단·도중 끊김도 같은 이력에 남는다(증발 금지 — 기록과 최근이 같은 사실을 말하게).
function _settleHist(st, entry) {
  return [entry].concat(Array.isArray(st.hist) ? st.hist : []).slice(0, 60);
}
// 한 회차 = 저장된 계정 전체를 하나씩(직렬) 로그아웃→로그인→정산수집→서버반영.
//   ★직렬 필수 — 확장은 롯데온 전용 탭 하나를 재사용한다(동시 실행 시 서로 페이지를 갈아엎음).
async function settleRunOnce(st) {
  if (_settleRunning) return { busy: true };
  _settleRunning = true;
  _settleRunAt = Date.now();
  const _gen = _settleGen;   // 내 세대 — 감시가 끊으면 어긋나고, 아래에서 스스로 멈춘다
  // ★[2026-08-04 2차] 심장박동 — MV3 SW 는 30초 조용하면 크롬이 죽인다. 회차가 탭 로드를
  //   조용히 기다리는 동안(밤 롯데온 셀러오피스가 느릴 때) 30초를 넘기면 SW 가 통째로
  //   죽어 회차가 기록도 없이 증발했다(실측: 19:56·20:56 연속 — 낮엔 다른 크롤 활동이
  //   우연히 SW 를 깨워 둬 살아남았던 것). 20초마다 스토리지를 건드려 살아 있음을 알린다.
  const _ka = setInterval(() => {
    try { chrome.storage.local.get("__moum_ka", () => { void chrome.runtime.lastError; }); } catch (_) {}
  }, 20000);
  // ★시작 도장 — 회차가 도중에 죽으면 아무 기록이 없어 「거른 것」과 구분이 안 됐다.
  //   시작을 스토리지에 박아 두고, SW 재기동 시 끝맺음 없는 도장이 보이면 정직하게 남긴다.
  try {
    const _st0 = await settleLoad();
    await settleSave(Object.assign({}, _st0, { runStartedAt: Date.now() }));
  } catch (_) {}
  // 하루에 한 번은 깊게 — 마지막 깊은 회차가 24시간 넘었으면 이번이 그 차례.
  const deep = (Date.now() - (parseInt(st.deepAt || 0, 10) || 0)) >= _SETTLE_DEEP_EVERY_MS;
  const win = _settleWindow(deep ? _SETTLE_DEEP_DAYS : _SETTLE_SHALLOW_DAYS);
  const sum = { ok: 0, verify: 0, fail: 0, orders: 0, soRows: 0, soFail: 0, error: "", deep: deep,
                since: win.since, until: win.until };
  try {
    if (st.base) _mgr.base = st.base;   // 어느 서버(라이브/로컬)에 반영할지 — 켤 때 잡아둔 origin
    const lr = await bgFetch("/accounts/api/crawl-login/accounts").then((x) => x.json()).catch(() => null);
    // ★정직 — 목록을 못 받으면(mou-m 미로그인·서버 무응답) '0계정 성공'이 아니라 오류로 남긴다.
    if (!lr || !lr.ok || !Array.isArray(lr.accounts)) {
      sum.error = "계정 목록을 못 받음 — mou-m 로그인이 풀렸거나 서버 응답 없음";
      return sum;
    }
    const accounts = lr.accounts.filter((a) => a && a.saved);
    if (!accounts.length) { sum.error = "저장된 로그인이 있는 계정이 없음"; return sum; }
    // ★[2026-08-03] 계정별 회차 결과를 서버에 남긴다.
    //   예전엔 「자동이 돌고 있나」를 lotteon_settlements 의 updated_at 으로 **짐작**했는데,
    //   그건 「값이 바뀐 시각」이지 「성공한 시각」이 아니라 양방향으로 틀린다(멀쩡한데 낡아
    //   보이고, 막혔는데 경보가 안 뜬다). 화면은 「실패 2」만 알려줄 뿐 **어느 계정인지**를
    //   못 알려줬다 — 그럼 사장님이 7개를 하나씩 눌러봐야 한다. 그래서 계정 단위로 기록한다.
    // 계정 하나의 결말은 **한 줄만** 남긴다 — 재시도가 있으므로 마지막 결말이 진실이다
    //   (배열에 두 줄 쌓으면 화면·집계가 「성공인데 실패」로 어긋난다).
    const _res = new Map();
    const _mark = (a, result, detail, rows, trNo) => _res.set(a.env_prefix, {
      env_prefix: a.env_prefix, display_name: a.display_name || "",
      tr_no: trNo || a.tr_no || "", result: result,
      detail: (detail || "").slice(0, 300), rows: rows || 0, deep: deep,
    });
    // ★[2026-08-06] 회차 예산 — 다 돌 시간이 없으면 남은 계정을 「순서가 못 옴」으로
    //   정직히 적고 끝낸다. 감시(40분)에 끊기면 계정별 기록이 통째로 안 남는다.
    const runDeadline = _settleRunAt + _SETTLE_RUN_BUDGET_MS;
    const skipped = [];
    // 한 계정 처리 — 결과를 _mark 로 남기고 'ok'|'verify'|'fail' 을 돌려준다.
    const runAccount = async (a) => {
      try {
        const creds = await bgFetch("/accounts/api/crawl-login/" + encodeURIComponent(a.env_prefix) + "/creds",
          { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
          .then((x) => x.json()).catch(() => null);
        if (!creds || !creds.ok) {
          _mark(a, "fail", "자격증명을 못 받음(서버 응답 없음·저장 안 됨)"); return "fail";
        }
        const r = await handleLotteonAccountCollect({ login_id: creds.login_id, password: creds.password,
                                                      since: win.since, until: win.until });
        if (r && r.needs_verify) {                             // SMS 2단계 — 무인으론 못 넘김(정직히 셈)
          _mark(a, "verify", r.error || "본인인증 필요", 0, r.trNo); return "verify";
        }
        if (!(r && r.ok && r.rows)) {
          _mark(a, "fail", ((r && r.step) ? "[" + r.step + "] " : "") + ((r && r.error) || "불명"),
                0, r && r.trNo);
          return "fail";
        }
        _mark(a, "ok", "", r.rows.length, r.trNo);
        // ★source=auto 를 함께 보낸다 — 서버 stats 가 「자동이 돌고 있나」를 답할 수 있게.
        //   이게 없으면 표가 다 차 있어도 그게 언제·무엇으로 채워진 건지 알 길이 없다.
        await bgFetch("/api/margin/lotteon-settlement",
          { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source: "auto", rows: r.rows }) })
          .then((x) => x.json()).catch(() => null);
        // ★[2026-09-05] 지급내역(seCmptDt) 크롤도 같은 회차에 얹는다 — 여태
        //   handleLotteonPaidCrawl 함수는 있는데 아무도 부르지 않아 「입금 완료」를
        //   확인할 유일한 창구(lotteon_paid 표)가 항상 비어 있었다. 여분 시간이 있을
        //   때만 돈다(정산 본체보다 우선순위 낮음 — 실패해도 정산은 성공으로 친다).
        if (Date.now() < runDeadline) {
          try {
            const pr = await handleLotteonPaidCrawl({ since: win.since, until: win.until, trNo: r.trNo });
            if (pr && pr.ok && pr.rows && pr.rows.length) {
              await bgFetch("/api/margin/lotteon-paid",
                { method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ source: "auto", trNo: pr.trNo || r.trNo,
                                          account: a.display_name || "", rows: pr.rows }) })
                .then((x) => x.json()).catch(() => null);
            }
          } catch (_) { /* 부가 수집 — 본체(정산)를 안 죽인다 */ }
        }
        // ★[2026-08-02] 주문 크롤분도 보낸다 — 여태 **수집해놓고 버리고 있었다**.
        //   handleLotteonAccountCollect 는 같은 로그인 세션에서 통합주문조회까지 긁어
        //   orderRows 로 돌려주는데(그 비용은 이미 치렀다), 자동 회차는 그걸 안 보냈다.
        //   수동 경로(crawl_login.html)만 /lotteon-so-upsert 로 보내고 있었다.
        //   이 데이터가 OpenAPI 가 못 주는 취소 라인·취소건 구매자·철회 취소 신호의
        //   유일 원천이라, 자동만 켜둔 상태에선 그것들이 영영 안 들어왔다.
        //   실패해도 정산은 성공으로 친다 — 부가 수집이 본체를 죽이면 안 된다.
        //   ★1,000개씩 나눠 보낸다 — 서버가 rows>2000 을 400 으로 거절하는데
        //     이 호출은 .catch 로 삼켜져 **조용히 통째 유실**된다. 창이 180일로
        //     넓어졌으니 바쁜 계정은 그 상한에 닿을 수 있다.
        const _so = (r.orderRows || []);
        for (let i = 0; i < _so.length; i += 1000) {
          const part = _so.slice(i, i + 1000);
          const ok = await bgFetch("/api/orders-ingest/lotteon-so-upsert",
            { method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ rows: part }) })
            .then((x) => x.json()).catch(() => null);
          if (ok && ok.ok) sum.soRows += part.length;
          else sum.soFail += part.length;   // 조용한 실패 금지 — 회차 요약에 남긴다
        }
        sum.orders += (r.collected || 0);
        return "ok";
      } catch (e) {
        _mark(a, "fail", "예기치 못한 오류: " + String((e && e.message) || e));
        return "fail";
      }
    };

    // ── 1차 — 저장된 계정 전부. 지난 회차에 순서가 못 온 계정이 있으면 거기서부터 시작한다
    //    (같은 계정만 매번 굶는 것을 막는다 — 순번 고정이면 뒷자리는 영영 못 돈다).
    let order = accounts;
    const _from = accounts.findIndex((a) => a.env_prefix === (st.startPfx || ""));
    if (_from > 0) order = accounts.slice(_from).concat(accounts.slice(0, _from));
    for (const a of order) {
      if (_gen !== _settleGen) { sum.aborted = true; break; }   // 감시가 끊은 옛 회차 — 더 나아가지 않는다
      if (Date.now() > runDeadline) { skipped.push(a); continue; }
      await runAccount(a);
    }
    for (const a of skipped) {
      _mark(a, "fail", "회차 시간이 모자라 순서가 못 옴 — 다음 회차에 이 계정부터 돈다");
    }
    // 다음 회차의 출발점 — 굶은 계정이 있으면 그 계정부터.
    sum.startPfx = skipped.length ? skipped[0].env_prefix : "";

    // ── 2차 — 실패한 계정만 한 번 더. 손으로 그 계정만 다시 누르면 되던 것을(2026-08-06 사장님
    //    실측) 회차가 스스로 한다. 로그인 세션·탭 상태가 새로 잡히므로 대개 여기서 붙는다.
    //    ※본인인증(verify)은 무인으로 못 넘기니 다시 시도하지 않는다(시간만 태운다).
    if (!sum.aborted) {
      const retry = order.filter((a) => (_res.get(a.env_prefix) || {}).result === "fail"
                                        && skipped.indexOf(a) < 0);
      for (const a of retry) {
        if (_gen !== _settleGen) { sum.aborted = true; break; }
        if (Date.now() > runDeadline) break;                   // 남은 시간이 없으면 1차 결과 그대로
        sum.retried = (sum.retried || 0) + 1;
        await runAccount(a);                                   // 결말은 _mark 가 덮어쓴다(한 줄 원칙)
      }
    }

    const runlog = Array.from(_res.values());
    for (const x of runlog) {
      if (x.result === "ok") sum.ok++;
      else if (x.result === "verify") sum.verify++;
      else sum.fail++;
    }
    // ★회차 기록을 **끝에 한 번** 보낸다 — 계정마다 보내면 호출이 7배가 되고,
    //   중간에 크롬이 죽으면 어차피 반쪽 기록이라 한 번에 보내는 편이 단순하다.
    //   실패해도 정산 수집 자체는 성공으로 친다(기록이 본체를 죽이면 안 된다).
    try {
      if (runlog.length) {
        await bgFetch("/api/margin/lotteon-crawl-run",
          { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ via: "auto", runs: runlog }) }).then((x) => x.json());
      }
    } catch (_) {}
    // ★[2026-08-06] 뒷정리도 **내 세대일 때만** — 이게 없어서, 감시에 끊긴 옛 회차가
    //   뒤늦게 여기까지 흘러와 **지금 도는 새 회차의 탭을 닫아 버렸다**.
    //   라이브 실측(2026-08-06 17:47 회차): 브랜드마켓 「예기치 못한 오류: No tab with id: 1910162891」
    //   — 계정이 멀쩡히 로그인해 놓고 남이 탭을 치워서 죽은 것이다.
    //   깃발·기록엔 세대 가드가 있었는데 탭 정리에만 빠져 있었다(같은 원칙, 한 곳 누락).
    if (_gen === _settleGen) {
      try { if (_loTabId != null) { await chrome.tabs.remove(_loTabId); _loTabId = null; } } catch (_) {}
      await closeServiceTabIfOwned();   // 우리가 띄운 임시 mou-m 탭 정리(사용자 탭이면 안 닫음)
    }
    return sum;
  // 깃발은 내 세대일 때만 내린다 — 감시가 끊은 뒤엔 새 회차가 이미 들고 있을 수 있다(남의 깃발 금지).
  } finally { clearInterval(_ka); if (_gen === _settleGen) _settleRunning = false; }
}
// 회차 실행 + 다음 마감 기록(성공·실패 무관하게 다음을 잡아야 멈추지 않는다).
async function settleRunAndArm(st) {
  const min = parseInt(st.min || 60, 10) || 60;
  const gen = _settleGen;
  const sum = await settleRunOnce(st);
  if (sum && sum.busy) return;
  // ★감시가 끊은 옛 회차는 상태를 쓰지 않는다 — 마감·기록의 주인은 새 회차다(둘이 쓰면 모순).
  if ((sum && sum.aborted) || gen !== _settleGen) return;
  const done = await settleLoad();
  const _last = { at: Date.now(), ok: sum.ok, verify: sum.verify, fail: sum.fail, orders: sum.orders,
                  soRows: sum.soRows || 0, soFail: sum.soFail || 0,
                  retried: sum.retried || 0,
                  error: sum.error || "", deep: !!sum.deep,
                  since: sum.since || "", until: sum.until || "" };
  const patch = {
    nextAt: Date.now() + min * 60000,   // 끝난 시점 기준으로 다시
    runStartedAt: 0,                    // 끝맺음 — 시작 도장 지움(도장만 남으면 = 도중 사망)
    startPfx: sum.startPfx || "",       // 이번에 순서가 못 온 계정 — 다음 회차는 거기서 출발
    last: _last,
    hist: _settleHist(done, _last),     // 기록용 이력에도 같은 사실을 남긴다(모순 금지)
  };
  // ★깊은 회차는 「한 계정이라도 성공했을 때만」 오늘 것으로 친다 — 전부 실패한 회차를
  //   성공으로 기록하면 다음 24시간 동안 깊은 회차가 안 돌아 과거가 또 안 메워진다.
  if (sum.deep && sum.ok > 0) patch.deepAt = Date.now();
  await settleSave(Object.assign({}, done, patch));
}
// 알람 1회 — '마감 지났나'만 본다(자동화 폴링과 동일 사고방식).
async function settleTick() {
  const st = await settleLoad();
  if (!st.on) { try { chrome.alarms.clear(MOUM_SETTLE_ALARM); } catch (_) {} return; }
  if (_settleRunning) {
    // ★[2026-08-04] 회차 감시 — 상한을 넘긴 회차는 걸린 것으로 보고 강제로 내려놓는다.
    if (!(_settleRunAt && Date.now() - _settleRunAt > _SETTLE_STUCK_MS)) return;
    _settleGen++;                     // 옛 회차 무장해제 — 나아가지도, 상태를 쓰지도 못한다
    _settleRunning = false;
    try { if (_loTabId != null) { const t = _loTabId; _loTabId = null; await chrome.tabs.remove(t); } } catch (_) {}
    // 조용한 복구 금지 — 무슨 일이 있었는지 기록으로 남겨 화면이 말하게 한다.
    try {
      const cur = await settleLoad();
      const stuck = { at: Date.now(), ok: 0, verify: 0, fail: 0, orders: 0, soRows: 0, soFail: 0,
                      error: "회차가 " + Math.round(_SETTLE_STUCK_MS / 60000) +
                             "분을 넘겨 강제 중단(감시) — 다음 회차에 다시 돈다",
                      deep: false, since: "", until: "" };
      await settleSave(Object.assign({}, cur, { runStartedAt: 0, last: stuck,
                                                hist: _settleHist(cur, stuck) }));
    } catch (_) {}
    // 아래로 계속 — 마감이 지났으면 새 회차가 바로 잡는다(옛 회차는 세대표로 무장해제됨).
  }
  if (st.nextAt && Date.now() < st.nextAt) return;
  // ★먼저 다음 마감을 밀어두고 돈다 — 도는 도중 알람이 또 떠도 재발사되지 않게(중복 크롤 방지).
  const min = parseInt(st.min || 60, 10) || 60;
  await settleSave(Object.assign({}, st, { nextAt: Date.now() + min * 60000 }));
  await settleRunAndArm(st);
}
async function settleAutoSet(on, min, base) {
  const st = await settleLoad();
  if (!on) {
    await settleSave(Object.assign({}, st, { on: false, nextAt: 0 }));
    try { chrome.alarms.clear(MOUM_SETTLE_ALARM); } catch (_) {}
    return;
  }
  const m = parseInt(min || st.min || 60, 10) || 60;
  await settleSave(Object.assign({}, st, { on: true, min: m, base: base || st.base || "", nextAt: Date.now() + m * 60000 }));
  try { chrome.alarms.create(MOUM_SETTLE_ALARM, { periodInMinutes: 1 }); } catch (_) {}
  const fresh = await settleLoad();
  settleRunAndArm(fresh);   // 켠 순간 즉시 1회(마감을 기다리지 않는 게 기대 동작)
}
try {
  chrome.alarms.onAlarm.addListener((a) => { if (a && a.name === MOUM_SETTLE_ALARM) settleTick(); });
} catch (_) {}
// SW 가 (재)기동될 때 — 켜져 있으면 알람을 되살린다(크롬 재시작 후에도 이어서 돌게).
// ★[2026-08-04 2차] 부검 — 시작 도장(runStartedAt)만 있고 끝맺음이 없으면, 지난 회차가
//   도중에 SW 와 함께 죽은 것이다(SW 가 새로 떴다 = 그 회차의 실행 흐름은 이미 없다).
//   여태 이 경우 아무 기록이 없어 「거른 것」과 구분이 안 됐다 — 정직하게 남긴다.
try {
  settleLoad().then(async (st) => {
    if (st && st.on) { try { chrome.alarms.create(MOUM_SETTLE_ALARM, { periodInMinutes: 1 }); } catch (_) {} }
    if (!(st && st.runStartedAt)) return;
    if (st.last && st.last.at >= st.runStartedAt) {          // 끝맺음이 있었네 — 도장만 청소
      await settleSave(Object.assign({}, st, { runStartedAt: 0 }));
      return;
    }
    const died = { at: Date.now(), ok: 0, verify: 0, fail: 0, orders: 0, soRows: 0, soFail: 0,
                   error: "회차 도중 크롬이 확장을 재워 끊김 — 다음 회차에 다시 돈다",
                   deep: false, since: "", until: "" };
    await settleSave(Object.assign({}, st, { runStartedAt: 0, last: died,
                                             hist: _settleHist(st, died) }));
  });
} catch (_) {}

// ── [2026-07-17] 정산 「자동 반복」 탭 지킴이 — 크롤-로그인 탭이 재워지지 않게 ──
//   ※이제 스케줄은 확장이 갖지만(위), 구버전 확장으로 폴백한 페이지도 있을 수 있어 유지한다.
//   서버 호출(자격증명·정산 push)에 mou-m 로그인
//   쿠키가 필요한데 SW 직접 fetch 엔 안 실리기 때문(위 _serviceTabId 주석과 같은 이유).
//   그런데 페이지는 크롬 메모리 세이버가 탭을 재우면(discard) 통째로 사라져 마감 확인조차
//   못 한다 → 자동 반복이 조용히 멈춘다. 여기서는 딱 두 가지만 한다.
//     ① 크롤-로그인 탭에 autoDiscardable=false (재우기 금지)
//     ② 1분 알람으로 확인 — 이미 재워졌으면 되살린다(reload). 되살아난 페이지는 저장된
//        마감(localStorage)을 읽어 지났으면 즉시 따라잡는다.
//   ★회차 계산은 절대 여기서 하지 않는다 — 페이지와 이중화되면 두 스케줄이 어긋난다(모순).
const MOUM_SETTLE_AWAKE_ALARM = "moum-settle-keepawake";
async function settleTabs() {
  try { return (await chrome.tabs.query({ url: _baseGlobs() })) || []; } catch (_) { return []; }
}
async function settleKeepAwakeOnce() {
  const tabs = await settleTabs();
  const targets = tabs.filter((t) => t && t.url && t.url.indexOf("/accounts/crawl-login") >= 0);
  if (!targets.length) { settleKeepAwakeStop(); return; }   // 탭을 닫았으면 지킴이도 끝
  for (const t of targets) {
    _pinTab(t.id);                                    // 재우기 금지(크롤 서비스탭과 동일 수법)
    if (t.discarded) { try { await chrome.tabs.reload(t.id); } catch (_) {} }   // 이미 재워졌으면 되살림
  }
}
function settleKeepAwakeStart() {
  settleKeepAwakeOnce();
  try { chrome.alarms.create(MOUM_SETTLE_AWAKE_ALARM, { periodInMinutes: 1 }); } catch (_) {}
}
function settleKeepAwakeStop() {
  try { chrome.alarms.clear(MOUM_SETTLE_AWAKE_ALARM); } catch (_) {}
  // 고정 해제 — 자동 반복을 껐으면 크롬이 알아서 메모리를 회수하게 돌려놓는다.
  settleTabs().then((tabs) => tabs.forEach((t) => {
    if (t && t.url && t.url.indexOf("/accounts/crawl-login") >= 0) {
      try { chrome.tabs.update(t.id, { autoDiscardable: true }, () => { void chrome.runtime.lastError; }); } catch (_) {}
    }
  }));
}
try {
  chrome.alarms.onAlarm.addListener((a) => { if (a && a.name === MOUM_SETTLE_AWAKE_ALARM) settleKeepAwakeOnce(); });
} catch (_) {}

// ── [2026-06-29] 현대H몰 색상/모델모음전 사이즈별 실수량 보강 ──
//   2축(색×사이즈) 모음전 상품은 페이지 HTML(__NEXT_DATA__)에 1축(색)만 옴 → 색별 합계만.
//   사이즈별 실수량은 item-stockcount API(색 번호 uitmSeq별)로만 온다. www→api 는 CORS,
//   서버직접은 404(인증) → 확장(host권한+쿠키 first-party)만 호출 가능. 색별로 호출해
//   per-(색,사이즈) 옵션을 만들어 반환(없으면 null → 서버 parse 의 색-레벨 폴백 유지).
//   참고: reference_hmall_stockcount_api
//   [2026-06-29 v3] item-stockcount 는 www.hmall.com(= navGrab 페이지와 동일 출처)에 있다.
//   SW 컨텍스트 fetch 는 빈 응답(WAF 봇판정/컨텍스트 추정) → navGrab 한 그 탭의 '페이지
//   컨텍스트(MAIN world)'에서 same-origin 상대경로 fetch 로 호출(=SPA 와 동일, 확실). 색
//   번호(uitmSeq) 1..15 순회, 빈 응답이면 색 소진. 2축(uitm2AttrNm) 없으면 단품 → null.

// [2026-07-02] 색상모음전 per-size 옵션 색별 가격 이식. item-stockcount 는 재고만 주고
//   가격=0(sellPrc=0) 이라, 그대로 두면 확장이 'price>0 옵션 0개' → price=null →
//   status=error("옵션 가격 없음") → 크롤 위젯에 거짓 '크롤실패'가 뜬다(서버
//   save_crawl_result 는 fetch_combo_persize_options 로 이미 정상 저장 → 데이터는 옳고
//   위젯만 거짓). 색-레벨 parse 옵션(각 색 표면가 보유)에서 색별 가격을 per-size 에
//   옮겨 붙여 확장 판정을 정직하게 만든다. 서버 build_combo_persize_options 의 color_price
//   병합과 대칭. ⚠️ 이식할 가격이 전무하면 원본 유지(폴백가 날조 금지). 회귀:
//   scripts/test_hmall_combo_price_graft.js
function graftComboColorPrices(parseOptions, perSizeOptions) {
  if (!Array.isArray(perSizeOptions) || !perSizeOptions.length) return perSizeOptions;
  const hasPrice = (o) => o && typeof o.price === "number" && o.price > 0;
  if (perSizeOptions.every(hasPrice)) return perSizeOptions;
  const colorPrice = {};
  let anyPrice = null;
  for (const o of (parseOptions || [])) {
    if (hasPrice(o)) {
      const c = (o.color_text || "").trim();
      if (c && !(c in colorPrice)) colorPrice[c] = o.price;
      if (anyPrice == null) anyPrice = o.price;
    }
  }
  if (anyPrice == null) return perSizeOptions;
  for (const o of perSizeOptions) {
    if (!hasPrice(o)) {
      const c = (o.color_text || "").trim();
      const pr = (c && colorPrice[c] != null) ? colorPrice[c] : anyPrice;
      o.price = pr; o.sale_price = pr;
    }
  }
  return perSizeOptions;
}

async function hmallPerSizeOptions(tabId, url) {
  try {
    const um = String(url || "").match(/slitmCd=(\d+)/);
    if (!um) return { ok: false, why: "no-slitmCd", options: null };
    const slitmCd = um[1];
    let res;
    try {
      res = await chrome.scripting.executeScript({
        // [2026-06-29 v4] world:'MAIN' 은 async 함수 Promise 반환을 await 안 함(크롬 제약)
        //   → 결과 undefined 였음. 기본(ISOLATED) world 는 await 됨. same-origin fetch 동일 동작.
        target: { tabId: tabId }, args: [slitmCd],
        func: async (slitmCd) => {
          const out = [];
          let calls = 0, why = "";
          for (let seq = 1; seq <= 15; seq++) {
            const qs = new URLSearchParams({
              slitmCd: slitmCd, setItemYn: "N", uitmCombYn: "Y", uitmAttrTypeSeq: "2",
              selectBoxIdx: "1", uitmSeq: String(seq), rishpNotfExpsYn: "Y",
              befUitmSeq1: "0", befUitmSeq2: "0", befUitmSeq3: "0", setSlitmCd: slitmCd, setSlitmYn: "N",
            });
            let list = [];
            try {
              const r = await fetch("/api/hf/dp/v1/item-ptc/item-stockcount?" + qs.toString(), { credentials: "include" });
              const j = await r.json();
              list = (j && j.respData && j.respData.stockList) || [];
              calls++;
            } catch (e) { why = "fetch-fail@" + seq; break; }
            if (!list.length) { why = "empty@" + seq; break; }
            if (!list.some((it) => it.uitm2AttrNm)) return { dan: true };
            list.forEach((it) => {
              const c = it.uitm1AttrNm || "", s = it.uitm2AttrNm || "";
              if (c && s) out.push({
                color_text: c, size_text: s,
                // [2026-06-29 S19] 품절 판정 = sellGbcd("00"=판매 / 그 외 예:"11"=품절).
                //   stockCount 아님 — 품절 사이즈도 stockCount=1 로 옴(다크네이비 260/265/275mm).
                //   sellGbcd 없으면 stockCount 폴백(거짓 품절 방지).
                stock: (it.sellGbcd && String(it.sellGbcd) !== "00")
                  ? 0
                  : (typeof it.stockCount === "number" ? it.stockCount : null),
                price: (typeof it.sellPrc === "number" ? it.sellPrc : null),
              });
            });
          }
          return { options: out, calls: calls, why: why };
        },
      });
    } catch (e) { return { ok: false, why: "exec-fail:" + String(e && e.message ? e.message : e).slice(0, 30), options: null }; }
    const r = res && res[0] && res[0].result;
    if (!r) return { ok: false, why: "no-result", options: null };
    if (r.dan) return { ok: false, why: "단품(no-2nd-axis)", options: null };
    const opts = r.options || [];
    return { ok: opts.length > 0, why: opts.length ? ("ok " + opts.length + "옵션/" + r.calls + "색") : ("none " + (r.why || "")), options: opts.length ? opts : null };
  } catch (e) { return { ok: false, why: "exc:" + String(e && e.message ? e.message : e).slice(0, 40), options: null }; }
}

// ── [2026-07-23 · Task10] parse 소싱처 혜택 필드 전달(BENEFIT_PASSTHROUGH) ──
//   서버 파서(/api/sources/parse)는 옵션 dict 에 동적 혜택 키(SSF point_rate·SSG MONEY·
//   현대H몰 H.Point·롯데아이몰 카드할인·스스 리뷰적립 등)를 채워 주는데, 확장이
//   options 매핑에서 {color,size,stock,price}만 남겨 crawl-result 로는 혜택이 안 갔다.
//   (서버는 parse 시점에 자체 영속하므로 데이터는 살아 있었지만 — 무스톰프 실측·핀:
//    tests/pricing/test_parse_path_benefit_no_stomp.py — ①신규 URL 첫 크롤은 parse 의
//    상품레벨 저장이 SP 부재로 건너뛰고 ②hmall 은 per-size 교체로 옵션혜택 행이 prune 돼
//    crawl-result 전달이 실제로 메꾸는 갭이다. one payload = one truth.)
//   키 목록 = 서버 OPTION_DYNAMIC_KEYS 중 parse 6소싱처가 실제 emit 하는 키
//   (lemouton.py/ssf.py/ssg.py/lotteon.py(아이몰)/hmall.py/ss_lemouton.py 실측).
//   롯데온 3종(lotteon_max_price·card_discounts·store_discount)·무신사 키는 BG_JS
//   직읽기 경로가 별도 전송(toItemBG 명시 필드) — 여기 안 넣는다(이중 정의 금지).
// ⚠ 이 배열은 파이썬 테스트(test_parse_path_benefit_no_stomp)가 정적 파싱한다 — 배열 안에 주석·따옴표 낀 텍스트 넣지 말 것
const BENEFIT_PASSTHROUGH = [
  "point_rate", "point_amount", "gift_point_amount", "auto_card_discount",
  "ssg_money_rate", "ssg_money_amount", "ssg_money_already_applied", "ssg_money_text",
  "card_benefit_price", "card_benefit_condition",
  "product_coupon_rate", "product_coupon_amount", "product_coupon_min_order",
  "product_coupon_max_discount", "product_coupon_label",
  "point_rewards", "hmall_point_amount", "hmall_card_label", "hmall_card_discount",
  "lotteimall_card_label", "lotteimall_card_discount", "review_point_max",
];
// 옵션(또는 item) dict 1개에서 혜택 키만 추출. 미수집 표식(null/0/''/false/빈배열)은
//   버린다 — 서버 상품레벨 스캔(save_crawl_result `_pdyn` 필터)과 동일 기준. 절대 채워
//   보내지 않는다(폴백 금지) → 키 부재 시 서버가 parse 영속값을 보존(무스톰프).
function pickBenefits(o) {
  const out = {};
  if (o) for (const k of BENEFIT_PASSTHROUGH) {
    const v = o[k];
    if (v === null || v === undefined || v === "" || v === false || v === 0) continue;
    if (Array.isArray(v) && !v.length) continue;
    out[k] = v;
  }
  return out;
}
// ── [2026-07-23 · M3] 소싱처 카테고리 경로(빵부스러기) 전달 ────────────────────
//   ⚠ BENEFIT_PASSTHROUGH 에 넣지 **않는다**. 그 배열은 '동적 혜택' 화이트리스트로,
//     서버 OPTION_DYNAMIC_KEYS ⊇ BENEFIT_PASSTHROUGH 를 파이썬 테스트가 정적으로 핀
//     박고 있고(tests/pricing/test_parse_path_benefit_no_stomp.py), 거기 넣으면
//     category_path 가 sp.dynamic_benefits_json 에도 중복 저장된다(전용 컬럼
//     source_products.category_path 가 이미 진실 원천 — 중복·모순 금지 원칙 위반).
//     → 혜택이 아닌 별도 필드로 명시 통과시킨다(product_coupon_list 와 같은 방식).
//   ⚠ 빈 값('')도 그대로 보낸다 — 서버 save_crawl_result 가 빈 문자열/None 을 건너뛰어
//     기존값을 보존한다(무스톰프). 확장이 폴백값을 지어내지 않는다(추측 금지).
const CATEGORY_HOME_LABELS = ["홈", "home", "메인", "main", "처음", "top", "전체"];
// 빵부스러기 조각 목록 → '대>중>소'. 서버 lemouton/sourcing/crawlers/base.py::build_category_path
//   와 같은 규칙(조각별 공백정리·빈 조각 제거·맨 앞 더미 라벨만 제외 — 중간 '홈'은 보존).
function buildCategoryPathBG(parts) {
  const c = (parts || [])
    .map((p) => String(p == null ? "" : p).replace(/\s+/g, " ").trim())
    .filter(Boolean);
  while (c.length && CATEGORY_HOME_LABELS.indexOf(c[0].toLowerCase()) >= 0) c.shift();
  return c.join(">");
}
// 결과/파서 응답 객체에서 category_path 를 문자열로 꺼낸다(없으면 '' — null 금지).
function catPathOf(o) {
  const v = o && o.category_path;
  return (typeof v === "string" && v.trim()) ? v.trim() : "";
}

// ==== M4IMG-HELPERS-START ====
// ── [2026-07-23 M4-5] 확장 경로 소싱처(무신사·롯데온) 상품 사진·상세설명 ────────────
//   소싱처 8곳 중 6곳은 서버 파서(lemouton/sourcing/crawlers/*.py)가 이미 뽑는다(M4-4).
//   무신사·롯데온만 추출이 이 파일 안이라 사진이 0장이었다 → 6마켓 전부 대표이미지가
//   필수라 그대로면 **등록 자체가 막힌다**.
//
//   ★ 조립 규칙은 **여기 한 곳**에만 둔다. 페이지에 주입되는 추출기(musinsaExtractor·
//     lotteonExtractor)는 바깥 스코프를 못 쓰므로 **원문 조각만 결과에 담아 넘기고**,
//     주소 조립은 전부 이 블록이 한다(규칙 두 벌 = 모순).
//   ★ **URL 만 만든다. 파일은 내려받지 않는다**(상세 HTML 만 예외 — 아래 사유).
//     이미지는 브랜드 저작물이라 마켓 업로드는 지재권 정책을 통과한 뒤 별도 단계에서 한다.
//   ★ 여기서 나온 값은 서버 수신 경계(webapp/routes/api_pricing.py::save_crawl_result)가
//     base.build_image_urls · base.sanitize_detail_html 로 **다시 정제**한다(멱등).
//     비상품 필터·추적픽셀 제거·남의 몰 링크 폐기는 그 공용 함수가 단일 원천이다.
// ⚠ 이 블록은 파이썬 테스트(tests/sources/test_ext_images_detail.py)가 통째로 떠서
//   node 로 실행한다 — 위아래 표식(M4IMG-HELPERS-START/END)을 지우지 말 것.

// 서버 base.build_image_urls 와 같은 상한(20장). 더 보내 봐야 서버에서 잘린다.
const EXT_IMG_LIMIT = 20;
// 무신사 이미지 CDN. [실측 2026-07-23] PDP 의 og:image 가
//   `https://image.msscdn.net` + thumbnailImageUrl 과 **문자열까지 일치**한다.
const MUSINSA_IMG_HOST = "https://image.msscdn.net";
// 롯데온 상품 이미지·상세파일 호스트. [실측 2026-07-23]
//   이미지 = JSON-LD Product.image 가 이 접두로 시작하고, base API 의
//           imgRteNm+imgFileNm 을 붙이면 같은 문자열이 된다(두 원천 일치).
//   상세   = 후보 6개 중 `/itemdetail` 만 200(나머지는 403). 아래 함수 주석 참조.
const LOTTEON_IMG_HOST = "https://contents.lotteon.com/itemimage";
const LOTTEON_DETAIL_HOST = "https://contents.lotteon.com/itemdetail";

// 이미지 주소 후보 → 절대 URL 목록(순서 유지·중복 제거·상한). 못 쓸 값이면 빈 배열.
//   `host` 는 상대경로를 붙일 기준. 없으면 상대경로는 **버린다**(추측 금지 — 지어낸
//   호스트로 붙이면 남의 도메인 주소가 만들어진다).
function absImageUrlsBG(list, host) {
  const out = [], seen = {};
  const arr = Array.isArray(list) ? list : (list ? [list] : []);
  for (const raw of arr) {
    let u = String(raw == null ? "" : raw).trim();
    if (!u) continue;
    if (u.indexOf("data:") === 0) continue;          // 지연로딩 placeholder — 주소 아님
    if (u.indexOf("//") === 0) u = "https:" + u;
    else if (u.indexOf("http://") !== 0 && u.indexOf("https://") !== 0) {
      if (!host) continue;
      u = host + (u.charAt(0) === "/" ? "" : "/") + u;
    }
    if (seen[u]) continue;
    seen[u] = 1;
    if (out.length < EXT_IMG_LIMIT) out.push(u);
  }
  return out;
}

// 경로 조각 두 개(`/a/b/` + `c.jpg`)를 슬래시 하나로 잇는다. 둘 중 하나라도 비면 ''.
function joinPathBG(rte, name) {
  const a = String(rte == null ? "" : rte).trim();
  const b = String(name == null ? "" : name).trim();
  if (!a || !b) return "";                            // 반쪽이면 지어내지 않는다
  return (a.charAt(0) === "/" ? a : "/" + a) + (a.charAt(a.length - 1) === "/" ? "" : "/") + b;
}

// ── 무신사 ────────────────────────────────────────────────────────────────
//   원천 = 이미 부르고 있는 `api2/goods/{id}` 응답(표면가·카테고리와 **같은 응답**).
//   추가 HTTP 호출 0.
//     대표 = thumbnailImageUrl  (`/images/goods_img/…_500.jpg`)
//     추가 = goodsImages[].imageUrl (`/images/prd_img/detail_…_500.jpg`)
//   ★ 렌디션(`_500`)을 큰 판으로 치환하지 않는다 — 2026-07-23 HEAD 실측에서
//     `_500` 을 떼거나 `_1200` 으로 바꾸면 **404**. 준 주소만 쓴다.
function musinsaImageUrlsBG(gd) {
  const g = gd || {};
  const srcs = [g.thumbnailImageUrl].concat(
    (Array.isArray(g.goodsImages) ? g.goodsImages : []).map((i) => i && i.imageUrl));
  return absImageUrlsBG(srcs, MUSINSA_IMG_HOST);
}
// 무신사 상세설명 = 같은 응답의 `goodsContents`(HTML 원문, 절대 URL). 없으면 ''.
function musinsaDetailHtmlBG(gd) {
  return String((gd && gd.goodsContents) || "").trim();
}

// ── 롯데온 ────────────────────────────────────────────────────────────────
//   1순위 = PDP JSON-LD `Product.image`(절대 URL, 페이지에서 **읽은 값**)
//   폴백  = base API `imgInfo.imageList[]` 의 imgRteNm+imgFileNm 조립
//           (JSON-LD 에 image 키가 없는 상품이 실제로 있다 — PD59900747 실측)
//   ※ 둘 다 없으면 빈 배열. 대체 이미지·추측 금지.
function lotteonImageUrlsBG(ldImages, base) {
  const ld = absImageUrlsBG(ldImages, "");            // 절대 URL 만 인정(상대면 버림)
  if (ld.length) return ld;
  const list = (base && base.imgInfo && base.imgInfo.imageList) || [];
  return absImageUrlsBG(
    (Array.isArray(list) ? list : []).map((it) => joinPathBG(it && it.imgRteNm, it && it.imgFileNm)),
    LOTTEON_IMG_HOST);
}
// 롯데온 상세설명 **파일 주소**. base API `descInfo.epnJsn` 의 `DSCRP` 항목만 쓴다.
//   ⚠ 같은 배열에 `AS_CNTS`(A/S 이용설명)도 온다 — 그걸 상세로 올리면 오등록이다.
//   [탐색 실측 2026-07-23] 후보 6개를 HEAD 로 두들긴 결과 `/itemdesc`·`/desc`·`/pdDesc`
//   등은 전부 403 이고 `/itemdetail` 만 200 HTML(서로 다른 상품 2건: 1,424B·16,238B).
function lotteonDetailUrlBG(base) {
  const arr = (base && base.descInfo && base.descInfo.epnJsn) || [];
  for (const e of (Array.isArray(arr) ? arr : [])) {
    if (e && e.pdEpnTypCd === "DSCRP") {
      const p = joinPathBG(e.dtlFileRteNm, e.dtlFileNm);
      if (p) return LOTTEON_DETAIL_HOST + p;
    }
  }
  return "";
}
// ==== M4IMG-HELPERS-END ====

// 상세설명 **파일**을 서비스워커가 받아온다. 실패는 ''(정직) — 폴백 금지.
//   🔴 페이지(MAIN world)에서 부르면 안 된다: `contents.lotteon.com` 응답에
//     Access-Control-Allow-Origin 이 없어(2026-07-23 실측 헤더 확인) 브라우저가 막는다.
//     서비스워커는 manifest host_permissions(`https://*.lotteon.com/*`)로 통과한다.
//   ★ 상세는 '주소'가 아니라 '본문'이 필요해 유일하게 파일을 받는다(이미지는 URL 만).
//   ★ 길이 상한 — 서버 sanitize_detail_html 이 200,000자에서 태그 경계로 자른다.
//     여기서는 전송량만 묶어 둔다(넉넉히 두 배).
const DETAIL_FILE_MAX = 400000;
async function fetchDetailFileBG(url) {
  const u = String(url || "").trim();
  if (!u) return "";
  try {
    const r = await fetch(u, { credentials: "omit", cache: "no-store",
                               signal: AbortSignal.timeout(8000) });
    if (!r.ok) {
      console.log("[moum m4img] 상세파일 http", r.status, u.slice(0, 120));
      return "";
    }
    const t = await r.text();
    if (!t || !t.trim()) return "";
    return t.length > DETAIL_FILE_MAX ? t.slice(0, DETAIL_FILE_MAX) : t;
  } catch (e) {
    console.log("[moum m4img] 상세파일 실패", String(e).slice(0, 80), u.slice(0, 120));
    return "";
  }
}

// 옵션 배열 → item 레벨 혜택(상품 단위 동일 값 가정 · 첫 non-empty 옵션 채택).
//   서버 extract_dynamic_benefits_from_options 와 동일 정책. hmall 은 per-size 교체로
//   options 에서 혜택이 사라지므로 '교체 전 parse 옵션'을 넣어 item 레벨로 살린다.
function pickBenefitsFromOptions(options) {
  for (const o of (options || [])) {
    const b = pickBenefits(o);
    if (Object.keys(b).length) return b;
  }
  return {};
}

// ── 1건 처리(창 재사용) — 백그라운드 내부 핸들러 직접 호출(메시지 왕복 없음) ──
//   opts.fetchOnly=true → fetch 경로(SW/same-origin)만 시도하고, 실패해도 창(navGrab/렌더)
//   폴백을 안 탄다. winless 동시 레인이 공유 도메인탭을 렌더로 뺏어 오파싱하는 것을 차단(§4 무결성).
async function crawlItemInTabBG(tabId, code, item, opts) {
  const sk = item.source_key, url = item.url;
  // [2026-07-07] 창없는 fast-lane — 플래그 ON + 어댑터 등록된 소싱처만. 성공 시 즉시 반환,
  //   실패/예외면 아래 기존 창 경로로 폴백(경로 폴백). 플래그 비면 이 블록은 건너뜀(동작 불변).
  if (FAST_FETCH_SOURCES.indexOf(sk) >= 0 && typeof FETCH_ADAPTERS[sk] === "function") {
    try {
      const _fx = await FETCH_ADAPTERS[sk](item);
      if (_fx && _fx.status === "ok") return _fx;
    } catch (_e) { /* 창 경로로 폴백 */ }
  }
  // [2026-07-09] SSG·롯데아이몰 — 도메인 탭에서 same-origin fetch(렌더 없이 원문). WAF 통과 경로.
  //   탭이 이미 그 도메인이면 바로 fetch(빠름), 아니면 도메인 루트로 1회 이동해 origin 확보.
  //   원문·서버파서로 price/stock 산출 == 창 경로와 동일. 어떤 실패든 아래 navGrab 창 경로로 폴백(안전).
  if (SAMEORIGIN_FETCH_SOURCES.indexOf(sk) >= 0) {
    try {
      const origin = new URL(url).origin;
      let onOrigin = false;
      try { const cur = await chrome.tabs.get(tabId); onOrigin = !!(cur && cur.url && new URL(cur.url).origin === origin); } catch (_) {}
      if (!onOrigin) {
        try {
          await chrome.tabs.update(tabId, { url: origin + "/" });
          await waitTabComplete(tabId, 20000);
          const c2 = await chrome.tabs.get(tabId);
          onOrigin = !!(c2 && c2.url && new URL(c2.url).origin === origin);
        } catch (_) {}
      }
      if (onOrigin) {
        const out = await chrome.scripting.executeScript({
          target: { tabId: tabId }, world: "ISOLATED", args: [url],
          func: async (u) => {
            try {
              const r = await fetch(u, { credentials: "include" });
              if (!r.ok) return { err: "http " + r.status };
              const t = await r.text();
              return (t && t.length > 3000) ? { html: t } : { err: "short " + (t ? t.length : 0) };
            } catch (e) { return { err: "ex" }; }
          },
        });
        const res = out && out[0] && out[0].result;
        if (res && res.html) {
          let pp = null;
          try {
            pp = await bgFetch("/api/sources/parse", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ source_key: sk, url: url, html: res.html }),
            }).then((x) => x.json());
          } catch (_) { pp = null; }
          if (pp && pp.ok) {
            const o2 = Array.isArray(pp.options) ? pp.options : [];
            const pr = o2.filter((o) => o && typeof o.price === "number" && o.price > 0);
            const bu = pr.filter((o) => (o.stock == null) || o.stock > 0);
            const pl = bu.length ? bu : pr;
            let price = null; if (pl.length) price = pl.reduce((m, o) => (o.price < m ? o.price : m), pl[0].price);
            let st = null; const ssx = o2.filter((o) => o && typeof o.stock === "number"); if (ssx.length) st = ssx.reduce((a, o) => a + Math.max(0, o.stock), 0);
            if (price != null) return Object.assign({
              url: url, source_key: sk, price: price, stock: st,
              // [2026-07-10] price 동봉 — 가격 변동 감지용(서버가 price 로 비교)
              // [Task10] pickBenefits — 파서 옵션의 혜택 키(ssg_money_rate 등)를 함께 전달
              options: o2.map((o) => Object.assign({ color: o.color_text, size: o.size_text, stock: o.stock, price: o.price }, pickBenefits(o))),
              status: "ok", product_name: pp.product_name_raw || null, error: null,
              category_path: catPathOf(pp),   // [M3] 서버 파서가 뽑은 빵부스러기 — 빈 값이면 서버가 무시(무스톰프)
            }, pickBenefitsFromOptions(o2));
          }
        }
      }
    } catch (_) { /* navGrab 창 경로로 폴백 */ }
  }
  // [2026-07-14] winless 동시 레인 모드 — fetch 실패 시 창(navGrab/렌더) 폴백을 생략하고
  //   정직하게 error 반환(공유 도메인탭 렌더 경쟁 원천 차단). 상위에서 1회 재시도(재-fetch)함.
  if (opts && opts.fetchOnly) {
    return { url: url, source_key: sk, status: "error", error: "fetch 실패(창 폴백 생략)" };
  }
  if (BG_JS_SOURCES.indexOf(sk) >= 0) {
    const x = await handleNavExtract({ tabId: tabId, url: url, source_key: sk }) || {};
    // ── [2026-07-23 M4-5] 상품 사진·상세설명 조립 ────────────────────────────
    //   추출기는 원문 조각만 넘긴다(페이지 주입 함수라 바깥 스코프를 못 씀) — 주소
    //   조립 규칙은 M4IMG 헬퍼 블록 한 곳뿐이다. 상세 파일 수신은 CORS 때문에 여기(SW).
    let _m4imgs = [], _m4detail = "";
    if (sk === "musinsa") {
      _m4imgs = musinsaImageUrlsBG(x.musinsa_goods);
      _m4detail = musinsaDetailHtmlBG(x.musinsa_goods);
    } else if (sk === "lotteon") {
      _m4imgs = lotteonImageUrlsBG(x.lotteon_ld_images, x.lotteon_base);
      // 🔴 [2026-07-23 M4-5 리뷰지적] **성공(ok) 크롤에서만** 상세 파일을 받는다.
      //   lotteonExtractor 는 품절이면 ok:false 인데 그때도 _bd(base 응답)는 차 있어,
      //   게이트가 없으면 품절 상품마다 contents.lotteon.com 에 GET 1회(최대 8초)를
      //   날리고 서버는 status='error' 게이트에서 그 결과를 통째로 버린다 = 순수 낭비.
      //   서버쪽 같은 기능(api_pricing.py 현대H몰 상세 보강)이 쓰는 규칙과 동일하다:
      //   실패는 보통 WAF·차단인데 거기에 요청을 더 얹으면 더 조인다.
      if (x.ok) _m4detail = await fetchDetailFileBG(lotteonDetailUrlBG(x.lotteon_base));
    }
    // 🟠 조용한 실패 금지 — 대표이미지 0장이면 6마켓 전부 등록이 막히는데, 아무 말이
    //   없으면 '왜 등록이 안 되지'를 되짚을 단서가 없다. 성공 크롤에서만 경고한다
    //   (실패 크롤은 사진이 없는 게 당연 — 경고 홍수 방지).
    if (x.ok && !_m4imgs.length) {
      console.log("[moum m4img] 사진 0장 — 등록 막힘 위험", sk, String(url).slice(0, 120));
    }
    return {
      url: url, source_key: sk, price: x.price, stock: x.stock, options: x.options,
      status: x.ok ? "ok" : "error", product_name: x.product_name, error: x.error || null,
      is_logged_in: (x.is_logged_in === undefined ? null : x.is_logged_in),
      // [2026-06-14 fix] '현재 브라우저 기준' 혜택 스냅샷 필드 — 추출기가 긁은 혜택을
      //   서버(_build_crawl_snapshot)까지 전달. 이전엔 여기서 누락돼 무신사 미수집(폴백 게이트)됐음.
      benefits_ok: x.benefits_ok, benefit_lines: x.benefit_lines, benefit_amounts: x.benefit_amounts,
      surface_price: x.surface_price, member_price: x.member_price,
      product_coupon_list: x.product_coupon_list || [],   // ★ 2026-07-04 무신사 상품쿠폰 전량(서버 쿠폰별 게이트)
      // [2026-07-23 · T6] 롯데온 pbf 혜택 3종 — 없으면 null(폴백 금지, 서버가 기존 베이스로 계산)
      lotteon_max_price: (x.lotteon_max_price === undefined ? null : x.lotteon_max_price),
    // [2026-07-23 · 2차 T1] Hmall 카드 즉시할인·결제 프로모션 (창 없이 API 수집)
    hmall_card_discounts: (x.hmall_card_discounts === undefined ? null : x.hmall_card_discounts),
    hmall_pay_promos: (x.hmall_pay_promos === undefined ? null : x.hmall_pay_promos),
    // [2026-07-23 · 2차 T6] N쇼핑 경유 4키 — 없으면 null(서버가 기존 값 보존)
    naver_via_rate: (x.naver_via_rate === undefined ? null : x.naver_via_rate),
    naver_via_amount: (x.naver_via_amount === undefined ? null : x.naver_via_amount),
    naver_via_preapplied: (x.naver_via_preapplied === undefined ? null : x.naver_via_preapplied),
    naver_via_label: (x.naver_via_label === undefined ? null : x.naver_via_label),
      lotteon_card_discounts: (x.lotteon_card_discounts === undefined ? null : x.lotteon_card_discounts),
      lotteon_store_discount: (x.lotteon_store_discount === undefined ? null : x.lotteon_store_discount),
      // [2026-07-23 M3] 무신사·롯데온 추출기가 뽑은 카테고리 경로. 못 뽑으면 ''(추측 금지).
      category_path: catPathOf(x),
      // [2026-07-23 M4-5] 상품 사진 URL 목록·상세설명 HTML. 못 뽑으면 []/''(서버가 건너뜀).
      image_urls: _m4imgs,
      detail_html: _m4detail,
    };
  }
  const grab = await handleNavGrab({ tabId: tabId, url: url });
  if (!grab || !grab.ok || !grab.html) {
    return { url: url, source_key: sk, status: "error", error: (grab && grab.error) || "HTML 수집 실패" };
  }
  if (grab.sku_diag) console.log("[moum] sku_stock", sk, url, grab.sku_diag);
  let p;
  try {
    p = await bgFetch("/api/sources/parse", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_key: sk, url: url, html: grab.html, sku_stock: grab.sku_stock || null }),
    }).then((x) => x.json());
  } catch (e) {
    return { url: url, source_key: sk, status: "error", error: "parse 호출 실패: " + e };
  }
  if (!p || !p.ok) {
    return { url: url, source_key: sk, status: "error", error: (p && (p.message || p.error)) || "parse 실패" };
  }
  let opts2 = Array.isArray(p.options) ? p.options : [];
  // [2026-06-29] 현대H몰 모음전(2축): 색별 item-stockcount API 로 사이즈별 실수량 보강.
  //   성공 시 색-레벨 옵션을 per-(색,사이즈) 옵션으로 교체 → 저장·매칭이 사이즈별 3상태 표시.
  if (sk === "hmall") {
    try {
      const ps = await hmallPerSizeOptions(tabId, url);
      try { console.log("[moum hmall 사이즈API]", url, ps && ps.why); } catch (_) {}
      // per-size 옵션(item-stockcount)은 가격 0 → 색-레벨 parse 옵션에서 색별 가격 이식
      //   (안 하면 거짓 '크롤실패'가 위젯에 뜬다. [2026-07-02])
      if (ps && ps.options && ps.options.length) opts2 = graftComboColorPrices(p.options, ps.options);
    } catch (e) { try { console.log("[moum hmall 사이즈API ERR]", e); } catch (_) {} }
  }
  const priced = opts2.filter((o) => o && typeof o.price === "number" && o.price > 0);
  const buyable = priced.filter((o) => (o.stock == null) || o.stock > 0);
  const pool = buyable.length ? buyable : priced;
  let price = null;
  if (pool.length) price = pool.reduce((m, o) => (o.price < m ? o.price : m), pool[0].price);
  let stock = null;
  const stocks = opts2.filter((o) => o && typeof o.stock === "number");
  if (stocks.length) stock = stocks.reduce((sum, o) => sum + Math.max(0, o.stock), 0);
  const ok = price != null;
  // [2026-06-22 진단] 스스 재고 all-999 원인 표면화 — sku_diag(확장 네이버 SKU 수집 결과)
  //   + 서버가 실수량(999 아님)을 몇 개 매핑했나. err:* → 수집실패 / ok:N + 실수량0 → 키불일치.
  const _realN = opts2.filter((o) => typeof o.stock === "number" && o.stock !== 999).length;
  return Object.assign({
    url: url, source_key: sk, price: price, stock: stock,
    // [2026-07-10] price 동봉 — 서버 persist_crawled_options 는 price 를 받을 걸로 설계됐는데
    //   확장이 안 보내서 '가격 변동'이 영원히 0건이었다(회차 보고서 30회차 실측). 파서 옵션엔 price 있음.
    // [Task10] pickBenefits — 파서 옵션의 혜택 키를 함께 전달(hmall per-size 행엔 없음=no-op)
    options: opts2.map((o) => Object.assign({ color: o.color_text, size: o.size_text, stock: o.stock, price: o.price }, pickBenefits(o))),
    status: ok ? "ok" : "error", product_name: p.product_name_raw || null,
    error: ok ? null : "옵션 가격 없음",
    sku_diag: grab.sku_diag || null,
    stock_real_n: _realN, stock_total_n: opts2.length,
    category_path: catPathOf(p),   // [M3] 서버 파서(르무통·SSF·SSG·스스르무통·H몰·아이몰)가 뽑은 빵부스러기
    // [Task10] item 레벨 혜택 — hmall 은 opts2 가 per-size(혜택 無)로 교체되므로
    //   '교체 전 parse 옵션(p.options)'에서 뽑아 상품 레벨 경로로 살린다.
  }, pickBenefitsFromOptions(p.options));
}

// ── [2026-06-18] 저장 헬퍼 — 결과 item 매핑 + crawl-result 저장(소싱처별 증분/최종 공용) ──
//   ★ 버그 수정: 기존엔 모든 소싱처 크롤이 끝난 뒤 '최종 1회'만 bgFetch 저장했는데,
//   그 마지막 저장이 조용히 0건 실패(창 다 닫힌 뒤 서비스탭 fetch 불안정)하면 수집한
//   가격이 전부 버려지고(하드리셋만 남아) 전 옵션이 판매차단됐다. 대책=소싱처가 끝날
//   때마다 그 소싱처 결과를 즉시 저장(크롤 도중 = bgFetch 정상 동작 구간) + 저장결과를
//   로그에 표면화(조용한 실패 제거). 최종 일괄 저장은 백스톱으로 유지(중복 저장은 무해).
// ══════════════════════════════════════════════════════════════════
//  [2026-07-07] 창없는 Fast-lane 어댑터 (Phase 2) — 전부 플래그 OFF(FAST_FETCH_SOURCES=[])
//   등록만 해두고, 소싱처별 G1(실브라우저 값 100% 대조) 통과 후에만 FAST_FETCH_SOURCES 에 추가.
// ══════════════════════════════════════════════════════════════════

// 공통 — BG_PARSE 소싱처(내장JSON/HTML): 창 없이 raw HTML fetch → 기존 서버 파서 재사용.
//   창 크롤(navGrab)과 유일한 차이 = "페이지를 열어 렌더 HTML" 대신 "raw HTML 직접 fetch".
//   데이터가 raw HTML(SSR/내장JSON)에 있으면 동일 결과. WAF/렌더로 비면 status!=ok → 창 폴백.
//   ⚠️ 혜택이 로그인 DOM 인 소싱처(현대H몰·SSF 일부)는 이 경로가 재고·표면가만 → 혜택은 창 필요(켤 때 G1 확인).
async function fetchRawParseAdapter(item) {
  const sk = item.source_key, url = item.url;
  // [2026-07-08] 봇차단(403)·과부하(429)·서버오류(5xx)·빈응답 대비 재시도(backoff).
  //   3회까지 재시도(0.4s·0.8s 대기). 그래도 실패하면 status:error 반환 → 상위 crawlItemInTabBG
  //   가 자동으로 '창 경로(navGrab)'로 폴백(렌더로 더 강하게 뚫음). 창도 실패하면 '확인불가'(거짓 금지).
  let html = null, lastErr = "";
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt) await new Promise((res) => setTimeout(res, 400 * attempt));
    try {
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) {
        lastErr = "http " + r.status;
        if (r.status === 403 || r.status === 429 || r.status >= 500) continue; // 차단·과부하·서버오류=재시도
        break; // 그 외 4xx=재시도 무의미
      }
      const t = await r.text();
      if (!t || t.length < 500) { lastErr = "빈 HTML(" + (t ? t.length : 0) + ")"; continue; }
      html = t; break;
    } catch (e) { lastErr = "fetch 예외"; continue; }
  }
  if (!html) return { url: url, source_key: sk, status: "error", error: "SW fetch 실패(재시도3): " + lastErr };
  let p;
  try {
    p = await bgFetch("/api/sources/parse", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_key: sk, url: url, html: html }),
    }).then((x) => x.json());
  } catch (e) { return { url: url, source_key: sk, status: "error", error: "parse 호출 실패" }; }
  if (!p || !p.ok) return { url: url, source_key: sk, status: "error", error: (p && (p.message || p.error)) || "parse 실패" };
  const opts2 = Array.isArray(p.options) ? p.options : [];
  const priced = opts2.filter((o) => o && typeof o.price === "number" && o.price > 0);
  const buyable = priced.filter((o) => (o.stock == null) || o.stock > 0);
  const pool = buyable.length ? buyable : priced;
  let price = null;
  if (pool.length) price = pool.reduce((m, o) => (o.price < m ? o.price : m), pool[0].price);
  let stock = null;
  const stocks = opts2.filter((o) => o && typeof o.stock === "number");
  if (stocks.length) stock = stocks.reduce((s, o) => s + Math.max(0, o.stock), 0);
  const ok = price != null;
  return Object.assign({
    url: url, source_key: sk, price: price, stock: stock,
    // [2026-07-10] price 동봉 — 서버 persist_crawled_options 는 price 를 받을 걸로 설계됐는데
    //   확장이 안 보내서 '가격 변동'이 영원히 0건이었다(회차 보고서 30회차 실측). 파서 옵션엔 price 있음.
    // [Task10] pickBenefits — 파서 옵션의 혜택 키를 옵션·item 레벨로 함께 전달
    options: opts2.map((o) => Object.assign({ color: o.color_text, size: o.size_text, stock: o.stock, price: o.price }, pickBenefits(o))),
    status: ok ? "ok" : "error", product_name: p.product_name_raw || null,
    error: ok ? null : "옵션 가격 없음",
    category_path: catPathOf(p),   // [M3] 서버 파서가 뽑은 빵부스러기(창없이 경로도 동일 payload)
  }, pickBenefitsFromOptions(opts2));
}

// 무신사 — 창 없이 재고 API(prioritized-inventories) + 표면가 API(goodsPrice.salePrice).
//   ⚠️ 회원 혜택은 로그인 DOM 이라 이 경로엔 없음 → 무신사 fast-lane 은 재고·표면가 갱신용.
//   혜택까지 필요한 전체크롤은 창 경로 유지(켤 때 정책 확정).
async function fetchMusinsaAdapter(item) {
  const url = item.url, sk = "musinsa";
  const id = (url.match(/products\/(\d+)/) || [])[1];
  if (!id) return { url: url, source_key: sk, status: "error", error: "product id 없음" };
  const base = "https://goods-detail.musinsa.com/api2/goods/" + id;
  try {
    const oj = await fetch(base + "/options", { credentials: "include", headers: { Accept: "application/json" } }).then((r) => r.json());
    const basic = (oj.data || {}).basic || [];
    const its = (oj.data || {}).optionItems || [];
    const valueNos = [];
    basic.forEach((g) => (g.optionValues || g.values || []).forEach((v) => { if (v.no != null) valueNos.push(v.no); }));
    const ir = await fetch(base + "/options/v2/prioritized-inventories", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ optionValueNos: valueNos }),
    });
    if (!ir.ok) return { url: url, source_key: sk, status: "error", error: "inv http " + ir.status };
    const ij = await ir.json();
    const invMap = {};
    ((ij && ij.data) || []).forEach((x) => { invMap[x.productVariantId] = x; });
    const gj = await fetch(base, { credentials: "include", headers: { Accept: "application/json" } }).then((r) => r.json());
    const _gd = gj.data || {};
    const salePrice = ((_gd.goodsPrice) || {}).salePrice;
    if (salePrice == null) return { url: url, source_key: sk, status: "error", error: "표면가 없음" };
    // [2026-07-23 M3] 창없이 경로도 같은 응답에서 카테고리 경로를 뽑는다(창 경로 musinsaExtractor 와 동일 원천).
    const _cat = buildCategoryPathBG([1, 2, 3, 4].map((i) => (_gd.category || {})["categoryDepth" + i + "Name"]));
    // 재고 3상태: 품절=0 / 잔여 N개=N(한정) / 표식없음=999(충분·수량 비공개).
    const options = its.map((it) => {
      const size = (it.optionValues && it.optionValues[0] && it.optionValues[0].name) || it.managedCode || "";
      const inv = invMap[it.no];
      let st = null;
      if (inv) st = (inv.outOfStock === true) ? 0 : (typeof inv.remainQuantity === "number" ? inv.remainQuantity : 999);
      // [2026-07-10] price 동봉 — 무신사는 옵션별 가격이 없고 상품 표면가(salePrice) 공통.
      return { color: "", size: size, stock: st, price: salePrice };
    });
    const stock = options.reduce((s, o) => s + (typeof o.stock === "number" ? o.stock : 0), 0);
    // [2026-07-23 M4-5] 창없이 경로도 **같은 응답**에서 사진·상세를 뽑는다(창 경로와 동일 원천).
    //   여기만 빠지면 fast-lane 을 탄 무신사 상품이 조용히 사진 0장으로 남는다.
    const _m4imgs = musinsaImageUrlsBG(_gd);
    if (!_m4imgs.length) console.log("[moum m4img] 사진 0장 — 등록 막힘 위험", sk, url.slice(0, 120));
    return { url: url, source_key: sk, price: salePrice, stock: stock, options: options,
             status: "ok", product_name: null, surface_price: salePrice, category_path: _cat,
             image_urls: _m4imgs, detail_html: musinsaDetailHtmlBG(_gd) };
  } catch (e) { return { url: url, source_key: sk, status: "error", error: "예외 " + String(e).slice(0, 40) }; }
}

// 현대H몰 — 창 없이. raw HTML(__NEXT_DATA__ SSR)로 표면가·색옵션 → 서버 parse,
//   + 색×사이즈 실재고는 item-stockcount API(uitmSeq 프로브)를 SW fetch(cross-origin)로.
//   ★hmall.py 파서는 __NEXT_DATA__ JSON 만 읽음 → 창(렌더)이든 raw든 값 동일(2026-07-09 실측 통과:
//     bbprc/sellPrc/stockList 원문 존재 + item-stockcount 200). 실패 시 error 반환→기존 창 경로 폴백.
async function fetchHmallPerSizeSW(slitmCd) {
  const out = [];
  for (let seq = 1; seq <= 15; seq++) {
    let list = [];
    try {
      const qs = new URLSearchParams({
        slitmCd: slitmCd, setItemYn: "N", uitmCombYn: "Y", uitmAttrTypeSeq: "2",
        selectBoxIdx: "1", uitmSeq: String(seq), rishpNotfExpsYn: "Y",
        befUitmSeq1: "0", befUitmSeq2: "0", befUitmSeq3: "0", setSlitmCd: slitmCd, setSlitmYn: "N",
      });
      const r = await fetch("https://www.hmall.com/api/hf/dp/v1/item-ptc/item-stockcount?" + qs.toString(),
        { credentials: "include", headers: { Accept: "application/json" } });
      const j = await r.json();
      list = (j && j.respData && j.respData.stockList) || [];
    } catch (e) { break; }
    if (!list.length) break;
    if (!list.some((it) => it.uitm2AttrNm)) return null;   // 2축(색×사이즈) 아님 → per-size 미적용
    list.forEach((it) => {
      const c = it.uitm1AttrNm || "", s = it.uitm2AttrNm || "";
      if (c && s) out.push({
        color_text: c, size_text: s,
        // 품절판정 = sellGbcd("00"=판매 / 그 외=품절). stockCount 아님(품절도 1 센티넬).
        stock: (it.sellGbcd && String(it.sellGbcd) !== "00")
          ? 0 : (typeof it.stockCount === "number" ? it.stockCount : null),
        price: (typeof it.sellPrc === "number" ? it.sellPrc : null),
      });
    });
  }
  return out.length ? out : null;
}

async function fetchHmallAdapter(item) {
  const url = item.url, sk = "hmall";
  let html;
  try {
    const r = await fetch(url, { credentials: "include" });
    if (!r.ok) return { url: url, source_key: sk, status: "error", error: "html http " + r.status };
    html = await r.text();
  } catch (e) { return { url: url, source_key: sk, status: "error", error: "html fetch 예외" }; }
  if (!html || html.length < 500) return { url: url, source_key: sk, status: "error", error: "빈 HTML" };
  let p;
  try {
    p = await bgFetch("/api/sources/parse", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_key: sk, url: url, html: html }),
    }).then((x) => x.json());
  } catch (e) { return { url: url, source_key: sk, status: "error", error: "parse 호출 실패" }; }
  if (!p || !p.ok) return { url: url, source_key: sk, status: "error", error: (p && (p.message || p.error)) || "parse 실패" };
  let opts2 = Array.isArray(p.options) ? p.options : [];
  // 모음전(2축) 색×사이즈 실재고 보강 — 창 경로의 hmallPerSizeOptions 와 동일 로직을 SW fetch 로.
  const um = String(url).match(/slitmCd=(\d+)/);
  if (um) {
    try {
      const ps = await fetchHmallPerSizeSW(um[1]);
      if (ps && ps.length) opts2 = graftComboColorPrices(p.options, ps);   // per-size 가격 0 → 색별 가격 이식
    } catch (e) { /* per-size 실패 시 색-레벨 유지 */ }
  }
  const priced = opts2.filter((o) => o && typeof o.price === "number" && o.price > 0);
  const buyable = priced.filter((o) => (o.stock == null) || o.stock > 0);
  const pool = buyable.length ? buyable : priced;
  let price = null;
  if (pool.length) price = pool.reduce((m, o) => (o.price < m ? o.price : m), pool[0].price);
  let stock = null;
  const stocks = opts2.filter((o) => o && typeof o.stock === "number");
  if (stocks.length) stock = stocks.reduce((s, o) => s + Math.max(0, o.stock), 0);
  const ok = price != null;
  // [2026-07-23 · 2차 T1] 카드 즉시할인·결제 프로모션 — 창 없이 item-prmo-lst API.
  //   ⚠️ 이 어댑터(fetchHmallAdapter)가 hmall 전용 경로다. 범용 fetchRawParseAdapter 가
  //   아니라는 점 주의(초기 구현이 그쪽에 들어가 수집이 통째로 누락됐던 실측 버그).
  let _hmPromo = { hmall_card_discounts: [], hmall_pay_promos: [] };
  let _hmVia = {};
  {
    const _um2 = String(url).match(/slitmCd=(\d+)/);
    if (_um2) {
      try { _hmPromo = await fetchHmallPromosSW(_um2[1]); } catch (e) { /* 빈 배열 유지 */ }
      // [T6] N쇼핑 경유 — item-ptc 의 tcDcInf 가 원천(로드 전 실측으로 확정).
      try { _hmVia = hmallNaverViaFromItemPtc(await fetchHmallItemPtcSW(_um2[1])); }
      catch (e) { _hmVia = {}; }
    }
  }
  return Object.assign({
    url: url, source_key: sk, price: price, stock: stock,
    hmall_card_discounts: _hmPromo.hmall_card_discounts,
    hmall_pay_promos: _hmPromo.hmall_pay_promos,
    ..._hmVia,
    category_path: catPathOf(p),   // [M3] hmall.py 파서가 뽑은 빵부스러기(창없이 경로)
    // [2026-07-10] price 동봉 — 서버 persist_crawled_options 는 price 를 받을 걸로 설계됐는데
    //   확장이 안 보내서 '가격 변동'이 영원히 0건이었다(회차 보고서 30회차 실측). 파서 옵션엔 price 있음.
    // [Task10] pickBenefits — per-size 행(혜택 無)엔 no-op. item 레벨은 교체 전 parse 옵션에서.
    options: opts2.map((o) => Object.assign({ color: o.color_text, size: o.size_text, stock: o.stock, price: o.price }, pickBenefits(o))),
    status: ok ? "ok" : "error", product_name: p.product_name_raw || null,
    error: ok ? null : "옵션 가격 없음",
  }, pickBenefitsFromOptions(p.options));
}


// ─────────────────────────────────────────────────────────────────────────────
// [2026-07-23 · 2차 T1] Hmall 카드 즉시할인 + 결제수단 프로모션 — 창 없이 API.
//   실측 경위(스펙 §11): 카드 정보는 SSR HTML·__NEXT_DATA__ 어디에도 없고(익명·로그인
//   fetch 모두 부재) 렌더 DOM 에만 그려진다 → 창이 필요해 보였으나,
//   전용 API `item-prmo-lst` 가 그 원천이었다. 단 쿠키 uh2oxid 를 **헤더로도** 실어야
//   200 (쿠키만 보내면 401 "만료된 uh2oxid"). chrome.cookies 로 읽어 헤더에 넣는다.
//   → 창 0개(기존 FAST_FETCH 레인) 유지하면서 카드 5% 를 정확히 얻는다.
//   응답 실측: crdImdtDcPrmoList[{crdcNm:"삼성카드", famtFxrtGbcd:"1"(1=정률/2=정액),
//   famtFxrtVal:5, strtVal:50000(최소결제), aplyStrtDtm~aplyEndDtm:당일 00:00~23:59,
//   prmoNm:"5% (전관)"}] — 유효기간이 당일이라 **일자별 로테이션**이 데이터로 확증됐고,
//   "(전관)" 표기대로 상품 공통이다. 그래도 상품마다 호출한다(상품 한정 프로모션 대비).
async function hmallUh2oxid() {
  try {
    const c = await chrome.cookies.get({ url: "https://www.hmall.com/", name: "uh2oxid" });
    return (c && c.value) || null;
  } catch (e) { return null; }
}

// [2026-07-23 · 2차 T6] item-ptc 조회 — 경유(tcDcInf) 판별용. 인증 규약은 카드와 동일
//   (쿠키 uh2oxid 를 **헤더로도** 실어야 200).
async function fetchHmallItemPtcSW(slitmCd) {
  const tok = await hmallUh2oxid();
  if (!tok) return null;
  try {
    const r = await fetch(
      "https://www.hmall.com/api/hf/dp/v1/item-ptc/item-ptc?slitmCd=" + encodeURIComponent(slitmCd),
      { credentials: "include", cache: "no-store",
        headers: { Accept: "application/json", uh2oxid: tok } });
    if (!r.ok) { console.log("[moum hmall itemPtc] http", r.status); return null; }
    const j = await r.json();
    return (((j || {}).respData || {}).data || {}).itemPtc || null;
  } catch (e) { console.log("[moum hmall itemPtc] ERR", String(e).slice(0, 90)); return null; }
}

async function fetchHmallPromosSW(slitmCd) {
  const out = { hmall_card_discounts: [], hmall_pay_promos: [] };
  const tok = await hmallUh2oxid();
  if (!tok) return out;      // 토큰 없으면 빈 배열 = 안 깎음(폴백 금지 원칙)
  let j = null;
  try {
    const r = await fetch(
      "https://www.hmall.com/api/hf/dp/v1/item-ptc/item-prmo-lst?slitmCd=" + encodeURIComponent(slitmCd),
      { credentials: "include", cache: "no-store",
        headers: { Accept: "application/json", uh2oxid: tok } });
    if (!r.ok) { console.log("[moum hmall prmo] http", r.status); return out; }
    j = await r.json();
  } catch (e) { console.log("[moum hmall prmo] ERR", String(e).slice(0, 90)); return out; }
  const d = (j && j.respData && j.respData.data) || {};
  const nowStamp = (function () {
    const n = new Date(), p = (x) => String(x).padStart(2, "0");
    return "" + n.getFullYear() + p(n.getMonth() + 1) + p(n.getDate())
      + p(n.getHours()) + p(n.getMinutes()) + p(n.getSeconds());
  })();
  for (const c of (d.crdImdtDcPrmoList || [])) {
    // 노출 플래그·기간 가드 — 만료/미노출 프로모션이 섞여 오면 매입가 과소가 된다.
    if (String(c.crdDcExpsYn || "").toUpperCase() === "N") continue;
    if (c.aplyStrtDtm && String(c.aplyStrtDtm) > nowStamp) continue;
    if (c.aplyEndDtm && String(c.aplyEndDtm) < nowStamp) continue;
    if (String(c.pcAplyYn || "Y").toUpperCase() === "N") continue;
    const label = (c.crdcNm || "").trim();
    const val = Number(c.famtFxrtVal || 0);
    if (!label || !(val > 0)) continue;
    // famtFxrtGbcd: "1"=정률(%) / "2"=정액(원) — 실측 규약. 그 외 코드는 버린다(추측 금지).
    const gb = String(c.famtFxrtGbcd || "");
    if (gb !== "1" && gb !== "2") continue;
    out.hmall_card_discounts.push({
      label: label,
      rate: gb === "1" ? val : 0,          // 퍼센트 단위(5 = 5%)
      amount: gb === "2" ? val : 0,        // 원
      min_order: Number(c.strtVal || 0),   // 최소 결제금액 조건
      promo: (c.prmoNm || "").trim(),
      valid_until: String(c.aplyEndDtm || ""),
    });
  }
  for (const p of (d.stlmWayPrmoList || [])) {
    const nm = (p.prmoNm || "").trim();
    const val = Number(p.famtFxrtVal || 0);
    if (!nm || !(val > 0)) continue;
    out.hmall_pay_promos.push({
      label: nm, rate: String(p.famtFxrtGbcd) === "1" ? val : 0,
      amount: String(p.famtFxrtGbcd) === "2" ? val : 0,
      min_order: Number(p.strtVal || 0), note: (p.evntTxtCntn || "").trim(),
    });
  }
  return out;
}


// ─────────────────────────────────────────────────────────────────────────────
// [2026-07-23 · 2차 T6] N쇼핑 경유(naver_via) 수집 — 몰마다 '표시가 반영 여부'가 달라
//   판별 게이트가 핵심이다(스펙 §11-4 실측).
//     · Hmall  = 「네이버가격비교」 항목이 할인내역에 있으면 **혜택가에 선반영**
//     · 롯데온 = 「제휴할인」 항목이 있으면 경유 상태 + **선반영**
//   선반영이면 preapplied=true 로 알려 서버가 **재차감하지 않게** 한다(이중차감 방지).
//   값을 못 구하면 아무 키도 안 보낸다(폴백 금지 — 서버가 기존 계산 유지).

// Hmall: N쇼핑 경유 판별 — **item-ptc API 의 tcDcInf 노드**가 정확한 원천이다.
//   실측(2026-07-23): tcDcInf = {tcCdNm:"네이버가격비교", dcRate:8, tcDcAmt:14730,
//   dcBndsAmt:30000(최소 주문)}. 이때 **bbprc(표면가) 자체가 이미 할인된 값**이므로
//   선반영 = 재차감 금지다(경유 없이 보면 tcDcInf 가 없거나 tcDcAmt=0).
//   ⚠️ raw HTML 문자열 검색은 못 쓴다 — 할인내역이 JS 렌더라 HTML(12KB 스켈레톤)에
//   없다(초기 구현이 그렇게 했다가 판별 실패, 로드 전 실측으로 잡음).
function hmallNaverViaFromItemPtc(itemPtc) {
  const tc = (itemPtc && itemPtc.tcDcInf) || null;
  if (!tc) return {};
  const nm = String(tc.tcCdNm || "").trim();
  if (!/네이버/.test(nm)) return {};
  const amt = Number(tc.tcDcAmt || 0);
  const rate = Number(tc.dcRate || 0);
  if (!(amt > 0) && !(rate > 0)) return {};
  return {
    naver_via_preapplied: true,          // bbprc 에 이미 반영됨(실측) → 서버는 재차감 금지
    naver_via_amount: amt || 0,
    naver_via_rate: rate > 0 ? rate / 100 : 0,
    naver_via_label: nm,
  };
}

// 등록(플래그 OFF 이므로 아직 아무 소싱처도 이 경로를 타지 않음 — 켜기는 소싱처별 G1 후).
["lemouton", "ssg", "lotteimall", "ssf", "ss_lemouton"].forEach((k) => { FETCH_ADAPTERS[k] = fetchRawParseAdapter; });
FETCH_ADAPTERS["hmall"] = fetchHmallAdapter;     // [2026-07-09] 창없이 어댑터(raw __NEXT_DATA__ + item-stockcount SW fetch)
FETCH_ADAPTERS["musinsa"] = fetchMusinsaAdapter;

function toItemBG(x) {
  return Object.assign({
    url: x.url, price: x.price, stock: x.stock, options: x.options,
    status: x.status, product_name: x.product_name, error: x.error,
    is_logged_in: (x.is_logged_in === undefined ? null : x.is_logged_in),
    benefits_ok: x.benefits_ok, benefit_lines: x.benefit_lines, benefit_amounts: x.benefit_amounts,
    surface_price: x.surface_price, member_price: x.member_price,
    product_coupon_list: x.product_coupon_list || [],   // ★ 2026-07-04 무신사 상품쿠폰 전량(서버 쿠폰별 게이트)
    // [2026-07-23 · T6] 롯데온 pbf 혜택 3종 — /api/sources/crawl-result 로 서버 전달(T7 서버 키).
    //   실패 = null/[] 그대로(폴백 금지). 롯데온 외 소싱처는 undefined → null.
    lotteon_max_price: (x.lotteon_max_price === undefined ? null : x.lotteon_max_price),
    // [2026-07-23 · 2차 T1] Hmall 카드 즉시할인·결제 프로모션 (창 없이 API 수집)
    hmall_card_discounts: (x.hmall_card_discounts === undefined ? null : x.hmall_card_discounts),
    hmall_pay_promos: (x.hmall_pay_promos === undefined ? null : x.hmall_pay_promos),
    // [2026-07-23 · 2차 T6] N쇼핑 경유 4키 — 없으면 null(서버가 기존 값 보존)
    naver_via_rate: (x.naver_via_rate === undefined ? null : x.naver_via_rate),
    naver_via_amount: (x.naver_via_amount === undefined ? null : x.naver_via_amount),
    naver_via_preapplied: (x.naver_via_preapplied === undefined ? null : x.naver_via_preapplied),
    naver_via_label: (x.naver_via_label === undefined ? null : x.naver_via_label),
    lotteon_card_discounts: (x.lotteon_card_discounts === undefined ? null : x.lotteon_card_discounts),
    lotteon_store_discount: (x.lotteon_store_discount === undefined ? null : x.lotteon_store_discount),
    // [2026-07-23 M3] 소싱처 카테고리 경로 — 서버 save_crawl_result 가 it['category_path'] 로 읽어
    //   source_products.category_path 갱신 + source_categories 사전 적재. 빈 문자열이면 서버가
    //   건너뛴다(기존값 보존 = 무스톰프). ★이 줄이 빠지면 수집해도 조용히 유실된다.
    category_path: catPathOf(x),
    // [2026-07-23 M4-5] 소싱처 상품 사진 URL 목록·상세설명 HTML —
    //   서버 save_crawl_result 가 it['image_urls']·it['detail_html'] 로 읽어
    //   base.build_image_urls · base.sanitize_detail_html 로 재정제한 뒤
    //   source_products.images_json · detail_html 에 넣는다.
    //   ★ 빈 값([]/'')이면 서버가 건너뛴다(기존값 보존 = 무스톰프) — 한 번 실패한
    //     크롤이 이미 확보한 사진을 지우면 그 상품은 등록이 통째로 막힌다.
    //   ★ BENEFIT_PASSTHROUGH 에 넣지 않는다 — 혜택 화이트리스트에 끼우면
    //     dynamic_benefits_json 에도 중복 저장된다(전용 컬럼이 진실 원천).
    //   ★ 이 두 줄이 빠지면 확장은 수집하고 서버는 버린다(조용한 실패).
    image_urls: Array.isArray(x.image_urls) ? x.image_urls : [],
    detail_html: String(x.detail_html || ""),
    // [Task10 · v0.7.56] parse 소싱처 item 레벨 혜택 키 통과(BENEFIT_PASSTHROUGH).
    //   있는 키만 실어 보낸다 — 키 부재 = 서버가 parse 영속값 보존(무스톰프, 폴백 금지).
  }, pickBenefits(x));
}
async function saveItemsBG(items) {
  if (!items || !items.length) return { ok: true, updated: 0 };
  return await bgFetch("/api/sources/crawl-result", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items: items.map(toItemBG) }),
  }).then((x) => x.json()).catch((e) => ({ ok: false, error: String(e && e.message ? e.message : e) }));
}

// ── 모음전 1건 전체 크롤(백그라운드판) — ext_bridge.crawlBundleAll 과 동일 로직 ──
async function crawlBundleAllBG(code) {
  _mgr.paused = false;
  const emit = (type, fields) => bgEmit(Object.assign({ type: type, bundle: code }, fields || {}));
  emit("start", { level: "", msg: "전체 로컬 크롤 시작: " + code });
  const ENC = encodeURIComponent(code);
  try { await bgFetch("/api/bundles/" + ENC + "/crawl-reset", { method: "POST" }); } catch (_) {}
  const _finalize = () => bgFetch("/api/bundles/" + ENC + "/crawl-finalize", { method: "POST" }).then((x) => x.json()).catch(() => null);
  let savedTotal = 0;   // 소싱처별 증분 저장 누적(완료 메시지·표면화용)

  const r = await bgFetch("/api/bundles/" + ENC + "/option-matrix").then((x) => x.json());
  const ALL = ALL_SOURCE_KEYS;
  const seen = new Set();
  const bySource = {};
  (r.options || []).forEach((o) =>
    (o.sources || []).forEach((s) => {
      if (!s.product_url || ALL.indexOf(s.source_key) < 0) return;
      if (s.crawl_weight === 0) return;   // [2026-07-10] 계수 0 = 크롤 제외(자동/전체 크롤 모두 안 긁음)
      const key = s.source_key + "|" + s.product_url;
      if (seen.has(key)) return;
      seen.add(key);
      (bySource[s.source_key] = bySource[s.source_key] || []).push({ source_key: s.source_key, url: s.product_url, url_type: s.url_type || "dan" });
    })
  );
  const sourceKeys = Object.keys(bySource);
  const total = sourceKeys.reduce((n, k) => n + bySource[k].length, 0);
  if (!total) { await _finalize(); emit("finish", { level: "warn", msg: "대상 URL 없음" }); return { ok: false, error: "대상 URL 없음" }; }

  // [2026-07-12 2단계] 소싱처별 '동시 상한' — 서버(weight-tree)에서 받아 한 소싱처의 URL 을
  //   여러 창으로 나눠 병렬로 긁는다(공유 커서=중복 0). 못 받으면 1(=현행 순차) 폴백.
  // [2026-07-14 상향] 첫 배포 안전 클램프 3 → 8 (사용자 결정: 화면 설정대로).
  //   이제 화면의 '동시 상한' 스테퍼(5~8)가 실제 창 수를 정한다. 소싱처당 최대 8창.
  //   ⚠️사이트 차단 위험 영역: 첫 실크롤에서 차단·빈응답·중복 여부를 반드시 육안 검증하고,
  //     실패가 보이면 이 상한을 낮춘다(=🔒 재고·가격 정합성 우선).
  const PER_SOURCE_MAX = 8;
  const sourceCaps = {};
  try {
    const _wt = await bgFetch("/api/crawl/weight-tree").then((x) => x.json());
    (_wt && _wt.src || []).forEach((s) => { if (s && s.scope_key != null) sourceCaps[s.scope_key] = s.concurrency; });
  } catch (_) {}
  function effectiveCap(sk) {
    const v = sourceCaps[sk];
    return Math.max(1, Math.min(PER_SOURCE_MAX, (v == null ? 1 : (parseInt(v, 10) || 1))));
  }

  // [2026-07-12] 동시 창 상한 3→10 (사용자 요청) — 예전처럼 창을 넉넉히 열어 빠르게.
  //   실제 도달치는 '메모리 안전장치'(MEM≥96 보류·≥98 강제감소)가 정한다 = 브레이크는 메모리.
  //   ★CPU 기반 자동감소는 해제(evaluateConcurrency): chrome.system.cpu 는 PC 전체 CPU라
  //     다른 앱이 바쁘면 크롤이 지레 1개로 쪼그라들어 느려지던 원인(사용자 확인). 이제 메모리만 브레이크.
  let cap = 30;                         // 천장 30(사용자 요청). ⚠️한 모음전 소싱처 ~8개라 현 구조선 ~8 바인딩(30은 천장). 메모리가 실제 브레이크.
  // [2026-07-12] 시작부터 이 모음전의 소싱처를 한꺼번에 연다(burst) — 4에서 +1씩 기어오르며
  //   창이 찔끔찔끔 열리던 것 개선. 천장(cap)·소싱처 수 안에서 즉시 최대치. 메모리 높으면 자동 감소.
  let concurrency = Math.min(cap, Math.max(1, sourceKeys.length));
  emit("concurrency", { level: "", msg: "초기 동시 창 " + concurrency + "/" + cap, metrics: { concurrency, cap, active: 0, total, done: 0 } });

  const pendingSources = sourceKeys.slice();
  const sourceProgress = {};
  const results = [];
  const latencies = [];
  let done = 0;
  let lastSys = { cpu: null, mem: null };
  let cooldown = 0;
  let prevThroughput = 0;
  let active = 0;

  async function runSource(sk) {
    const list = bySource[sk];
    const startIdx = sourceProgress[sk] || 0;
    let pausedMid = false;
    const srcOuts = [];   // 이 소싱처 결과 누적 → 소싱처 완료 즉시 증분 저장용
    const wins = [];      // 이 소싱처가 연 창들
    let cursor = startIdx;                 // ★ 레인들이 공유하는 URL 커서(단일스레드 → 원자적)
    const nLanes = Math.max(1, Math.min(effectiveCap(sk), list.length - startIdx));

    // [2026-07-14] 소싱처 유형별 병렬 방식 — '동시 상한'(effectiveCap)은 이제 '창 수'가 아니라
    //   "한꺼번에 몇 개를 동시에 긁느냐(레인 수)"다. 같은 URL 을 두 레인이 안 집도록 cursor 는
    //   단일스레드 원자 증가(i = cursor++). 창을 URL 마다 여는 게 병렬화의 본질이 아니다 —
    //   fetch 는 원래 동시 실행되므로 탭 1개(또는 0개) 안에서 동시에 쏘면 창 없이 빨라진다.
    //   · SW fetch(lemouton·ssf·hmall)  = 창 0개. 서비스워커에서 동시 어댑터 호출.
    //   · same-origin(ssg·lotteimall)   = 도메인 탭 1개. 그 탭에서 동시 fetch(창 1개, 렌더 없음).
    //   · 렌더(musinsa·lotteon)          = 레인마다 창 1개(기존 동작 보존).
    //   winless 레인은 fetchOnly=true → fetch 실패 시 창(navGrab) 폴백 생략·정직 error(§4 무결성).
    const isSW = FAST_FETCH_SOURCES.indexOf(sk) >= 0;
    const isSameOrigin = SAMEORIGIN_FETCH_SOURCES.indexOf(sk) >= 0;
    const winless = isSW || isSameOrigin;

    // 한 URL 처리(레인 공통 본문). tabId = null(SW) / 공유 도메인탭(same-origin) / 전용창(렌더).
    async function _processOne(tabId, laneOpts) {
      if (_mgr.paused) { pausedMid = true; return false; }
      const i = cursor++;                 // ★ 원자적(단일스레드) — 레인끼리 URL 안 겹침
      if (i >= list.length) return false;
      const t0 = Date.now();
      let out;
      const _r = await withTimeout(crawlItemInTabBG(tabId, code, list[i], laneOpts), UNIT_TIMEOUT_MS);
      if (_r && _r.__timeout) {
        out = { url: list[i].url, source_key: sk, status: "error", error: "유닛 타임아웃 " + (UNIT_TIMEOUT_MS / 1000) + "s(행 추정·건너뜀)" };
      } else if (_r && _r.__error) {
        out = { url: list[i].url, source_key: sk, status: "error", error: _r.__error };
      } else {
        out = _r || { url: list[i].url, source_key: sk, status: "error", error: "결과 없음" };
      }
      const sec = (Date.now() - t0) / 1000;
      latencies.push(sec); if (latencies.length > 12) latencies.shift();
      results.push(out); srcOuts.push(out); done++;
      if (cooldown > 0) cooldown--;
      emit("item-done", {
        source: sk, level: out.status === "ok" ? "" : "warn",
        url: (out && out.url) || (list[i] && list[i].url) || null,
        name: (out && out.product_name) || null,
        surf: (out && out.price != null) ? out.price : null,
        url_type: (list[i] && list[i].url_type) || "dan",
        lineId: out.status === "ok" ? (sk + "|" + ((out && out.url) || (list[i] && list[i].url) || "")) : null,
        msg: (out.status === "ok"
          ? (sk + " 표면 " + (out.price != null ? out.price.toLocaleString() + "원" : "가격없음") + " (" + sec.toFixed(1) + "s)")
          : (sk + " 실패: " + (out.error || "")))
          + (out.sku_diag != null ? (" [SKU재고 " + out.sku_diag + " · 실수량 " + (out.stock_real_n || 0) + "/" + (out.stock_total_n || 0) + "]") : ""),
        metrics: { concurrency, cap, active, done, total, avgSec: +bgMedian(latencies).toFixed(2), cpu: lastSys.cpu, mem: lastSys.mem },
      });
      if (done % 3 === 0) {
        lastSys = await handleSysinfo().then((s) => ({ cpu: s && s.cpu != null ? s.cpu : null, mem: s && s.mem != null ? s.mem : null })).catch(() => ({ cpu: null, mem: null }));
        if (lastSys.cpu != null || lastSys.mem != null) {
          const hot = (lastSys.cpu != null && lastSys.cpu >= 90) || (lastSys.mem != null && lastSys.mem >= 96);
          if (hot) emit("resource", { level: "warn", msg: "자원 높음 — CPU " + lastSys.cpu + "% / MEM " + lastSys.mem + "%", metrics: { concurrency, cap, active, cpu: lastSys.cpu, mem: lastSys.mem } });
        }
      }
      return true;
    }
    // 레인 = 공유 커서에서 URL 하나씩 뽑아 처리(레인 여러 개 = 동시성)
    async function _lane(tabId, laneOpts) {
      while (!_mgr.stopped) { const cont = await _processOne(tabId, laneOpts); if (!cont) break; }
    }

    let sharedTab = null;
    try {
      if (winless) {
        const laneOpts = { fetchOnly: true };
        if (isSameOrigin) {
          // 도메인 탭 1개 — origin 으로 미리 이동해 두면 레인들이 same-origin fetch(WAF 통과)만 한다.
          const w = await handleOpenWin({});
          if (!w || !w.ok || w.tabId == null) {   // 도메인 탭 못 열었음 → 전건 실패(정직)
            for (let j = startIdx; j < list.length; j++) { results.push({ url: list[j].url, source_key: sk, status: "error", error: "도메인 탭 생성 실패" }); done++; }
            delete sourceProgress[sk];
            emit("source-done", { source: sk, level: "warn", msg: sk + " 도메인 탭 생성 실패 — 건너뜀", metrics: { concurrency, cap, active, done, total } });
            return;
          }
          wins.push(w); sharedTab = w.tabId;
          try {
            const origin = new URL(list[startIdx].url).origin;
            await chrome.tabs.update(sharedTab, { url: origin + "/" });
            await waitTabComplete(sharedTab, 20000);
          } catch (_) { /* origin 확보 실패해도 crawlItemInTabBG 가 레인 내에서 재확보 시도 */ }
        }
        emit("window-open", { source: sk, level: "", wins: (sharedTab != null ? 1 : 0),
          msg: sk + (isSW ? " 창없이" : " 도메인탭 1개") + " · 동시 " + nLanes + "개 긁기",
          metrics: { concurrency, cap, active, done, total } });
        await Promise.all(Array.from({ length: nLanes }, () => _lane(sharedTab, laneOpts)));
      } else {
        // 렌더 경로(무신사·롯데온) — 레인마다 창 1개(기존 동작 보존).
        const _mkLane = async (wi) => {
          const w = await handleOpenWin({});
          if (!w || !w.ok || w.tabId == null) return;   // 이 창 실패 → 다른 창이 남은 URL 커버(커서 공유)
          wins.push(w);
          if (wi === 0) emit("window-open", { source: sk, level: "", wins: nLanes, msg: sk + " 창 시작" + (nLanes > 1 ? (" ×" + nLanes + " (URL 나눠 긁기)") : ""), metrics: { concurrency, cap, active, done, total } });
          await _lane(w.tabId, null);
        };
        await Promise.all(Array.from({ length: nLanes }, (_u, wi) => _mkLane(wi)));
        if (!wins.length) {   // 창을 하나도 못 열었음 → 전건 실패(기존 동작 보존)
          for (let j = startIdx; j < list.length; j++) { results.push({ url: list[j].url, source_key: sk, status: "error", error: "창 생성 실패" }); done++; }
          delete sourceProgress[sk];
          emit("source-done", { source: sk, level: "warn", msg: sk + " 창 생성 실패 — 건너뜀", metrics: { concurrency, cap, active, done, total } });
          return;
        }
      }
      // 실패 URL 1회 자동 재시도 — ★winless 는 '렌더 폴백'으로 한 번 더 뚫는다(기존 안전망 복원).
      //   fetch(fast)로 실패한 건만 렌더로 재시도 → raw fetch 가 WAF 챌린지/빈응답으로 비어도
      //   창 렌더로 값 확보(기존 동작과 동일 커버리지). 재시도는 순차라 공유탭 렌더 경쟁 없음.
      //   same-origin 은 이미 열린 도메인탭 재사용, SW 는 임시창 1개 열어 씀(끝나면 닫음).
      if (!_mgr.stopped && !_mgr.paused) {
        const _failed = srcOuts.filter((o) => o && o.status === "error");
        let _retryTab, _retryWin = null;
        if (winless) {
          if (sharedTab != null) { _retryTab = sharedTab; }                        // 도메인탭 재사용(same-origin)
          else if (_failed.length) { _retryWin = await handleOpenWin({}); _retryTab = (_retryWin && _retryWin.ok) ? _retryWin.tabId : null; }  // SW=임시창
        } else {
          _retryTab = wins[0] && wins[0].tabId;
        }
        const _retryOpts = null;   // ★재시도는 fetchOnly 끔 → 창(navGrab) 렌더 폴백 허용(안전망)
        if (_failed.length && _retryTab != null) {
          emit("retry", { source: sk, level: "", msg: sk + " 실패 " + _failed.length + "건 자동 재시도(렌더)", metrics: { concurrency, cap, active, done, total } });
          for (const _f of _failed) {
            if (_mgr.stopped || _mgr.paused) break;
            const _orig = list.find((x) => x.url === _f.url) || { url: _f.url, source_key: sk };
            const _r2 = await withTimeout(crawlItemInTabBG(_retryTab, code, _orig, _retryOpts), UNIT_TIMEOUT_MS);
            const _out2 = (_r2 && !_r2.__timeout && !_r2.__error && _r2.status === "ok") ? _r2 : null;
            if (_out2) {
              const _si = srcOuts.indexOf(_f); if (_si >= 0) srcOuts[_si] = _out2;
              const _ri = results.indexOf(_f); if (_ri >= 0) results[_ri] = _out2;
              emit("item-retried", { source: sk, level: "", url: _out2.url, name: _out2.product_name || null, surf: (_out2.price != null) ? _out2.price : null, lineId: sk + "|" + _out2.url, msg: sk + " 재시도 성공 — 표면 " + (_out2.price != null ? _out2.price.toLocaleString() + "원" : "가격없음"), metrics: { concurrency, cap, active, done, total } });
            }
          }
        }
        if (_retryWin && _retryWin.winId != null) { try { await handleCloseWin({ winId: _retryWin.winId }); } catch (_) {} }
      }
    } finally {
      for (const _w of wins) { if (_w && _w.winId != null) { try { await handleCloseWin({ winId: _w.winId }); } catch (_) {} } }
    }
    if (pausedMid) { pendingSources.unshift(sk); return; }
    if (_mgr.stopped) return;
    delete sourceProgress[sk];
    // ★ 소싱처 완료 즉시 증분 저장(크롤 도중 = bgFetch 정상 구간). 최종 일괄저장 실패해도 보존.
    const okOuts = srcOuts.filter((o) => o && o.status === "ok");
    const sv = await saveItemsBG(okOuts);
    const svOk = !!(sv && sv.ok && (sv.updated || 0) > 0);
    savedTotal += (sv && sv.updated) || 0;
    emit("source-saved", {
      source: sk, level: svOk ? "done" : (okOuts.length ? "warn" : ""),
      msg: sk + " 저장 " + ((sv && sv.updated) || 0) + "/" + okOuts.length + "건"
        + ((sv && sv.error) ? (" ⚠️실패: " + sv.error) : ((okOuts.length && !svOk) ? " ⚠️0건(저장 실패)" : "")),
      metrics: { concurrency, cap, active, done, total },
    });
    // [2026-06-18] 정직성 게이트 — 성공 0건인데 '완료'로 위장하던 버그 제거(silent fail 표면화).
    //   okOuts = 이 소싱처 status==='ok' 건. 전건성공=완료 / 부분=부분실패 / 0건=전건실패.
    const _okN = okOuts.length;
    emit("source-done", {
      source: sk,
      level: (_okN > 0 && _okN >= list.length) ? "done" : "warn",
      msg: sk + (_okN === 0 ? " ⚠️ 전건 실패" : (_okN >= list.length ? " 완료" : " ⚠️ 부분 실패")) + " (" + _okN + "/" + list.length + "건 성공)",
      metrics: { concurrency, cap, active, done, total },
    });
  }

  function evaluateConcurrency() {
    if (cooldown > 0) return;
    if (latencies.length < 3) return;
    const med = bgMedian(latencies) || 0.001;
    const throughput = concurrency / med;
    const cpu = lastSys.cpu, mem = lastSys.mem;
    // [2026-07-12] CPU 기반 감소 해제 — chrome.system.cpu 는 PC 전체 CPU라 다른 앱이 바쁘면
    //   크롤이 지레 1개로 줄어 느려졌다(사용자 확인). 브레이크는 '메모리'만 둔다.
    if (mem != null && mem >= 98) {
      if (concurrency > 1) { concurrency--; cooldown = 3; prevThroughput = throughput; emit("concurrency", { level: "down", msg: "메모리 한계(MEM≥98) 강제 −1 → " + concurrency, metrics: { concurrency, cap, active, cpu, mem, done, total } }); }
      return;
    }
    const blockUp = (mem != null && mem >= 96);   // 메모리 높을 때만 +1 보류(CPU는 무시)
    if (throughput > prevThroughput * 1.05) {
      prevThroughput = throughput;
      if (concurrency < cap && !blockUp) { concurrency++; cooldown = 3; emit("concurrency", { level: "up", msg: "처리량 개선 → 창 +1 = " + concurrency, metrics: { concurrency, cap, active, cpu, mem, done, total } }); }
      else if (blockUp && concurrency < cap) { emit("resource", { level: "warn", msg: "처리량 여력 있으나 메모리 높음(MEM≥96) → +1 보류", metrics: { concurrency, cap, active, cpu, mem, done, total } }); }
    } else if (throughput < prevThroughput * 0.9 && concurrency > 1) {
      concurrency--; cooldown = 3; prevThroughput = throughput; emit("concurrency", { level: "down", msg: "처리량 하락 → 창 −1 = " + concurrency, metrics: { concurrency, cap, active, cpu, mem, done, total } });
    } else { prevThroughput = Math.max(prevThroughput, throughput); }
  }

  let endReason = "done";
  await new Promise((resolveAll) => {
    let done2 = false; let pollTimer = null;
    function finish(reason) { if (done2) return; done2 = true; endReason = reason; if (pollTimer) clearTimeout(pollTimer); resolveAll(); }
    function schedulePoll() { if (pollTimer) clearTimeout(pollTimer); pollTimer = setTimeout(() => { pollTimer = null; pump(); }, 1200); }
    function pump() {
      if (done2) return;
      if (_mgr.stopped) { if (active === 0) finish("stopped"); else schedulePoll(); return; }
      if (_mgr.paused) { if (active > 0) schedulePoll(); return; }
      evaluateConcurrency();
      while (active < concurrency && pendingSources.length > 0) {
        const sk = pendingSources.shift(); active++;
        runSource(sk).catch((_) => {}).then(() => { active--; pump(); });
      }
      if (active === 0 && pendingSources.length === 0) { finish("done"); return; }
      schedulePoll();
    }
    _mgr._kick = pump;
    pump();
  });
  _mgr._kick = null;

  // ★ [2026-06-22] 최종 재시도 패스 — 동시창이 모두 닫혀 시스템 부하가 낮아진 지금,
  //   아직 실패(error)인 URL만 신규 창에서 1회 더 재크롤. 크롤 도중의 즉시 재시도(같은 창·
  //   고부하 시점)가 못 살린 '부하성·일시 hiccup' 실패를 자가치유 → 소싱처 통째 0% 방지.
  //   폴백 금지 — 여기서도 못 받으면 그대로 실패로 둔다(가짜값 안 채움).
  if (!_mgr.stopped) {
    const stillFailed = results.filter((o) => o && o.status === "error" && o.url);
    if (stillFailed.length) {
      emit("final-retry", { level: "", msg: "최종 재시도 — 실패 " + stillFailed.length + "건(부하 낮은 시점 재크롤)", metrics: { concurrency, cap, active, done, total } });
      await new Promise((r) => setTimeout(r, 1500));   // 일시 hiccup 가실 시간
      const bySk = {};
      stillFailed.forEach((o) => { (bySk[o.source_key] = bySk[o.source_key] || []).push(o); });
      for (const sk of Object.keys(bySk)) {
        if (_mgr.stopped) break;
        let rWinId = null, rTabId = null;
        try {
          const w = await handleOpenWin({});
          if (!w || !w.ok || w.tabId == null) continue;
          rWinId = w.winId; rTabId = w.tabId;
          const recovered = [];
          for (const _f of bySk[sk]) {
            if (_mgr.stopped) break;
            const _orig = (bySource[sk] || []).find((x) => x.url === _f.url) || { source_key: sk, url: _f.url };
            const _r3 = await withTimeout(crawlItemInTabBG(rTabId, code, _orig), UNIT_TIMEOUT_MS);
            if (_r3 && !_r3.__timeout && !_r3.__error && _r3.status === "ok") {
              const _ri = results.indexOf(_f); if (_ri >= 0) results[_ri] = _r3;
              recovered.push(_r3);
              // [2026-06-22] item-retried(복구) — done 불변 + 웹앱 fail→ok 보정(오버카운트/실패오표시 방지)
              emit("item-retried", { source: sk, level: "", url: _r3.url, name: _r3.product_name || null, surf: (_r3.price != null) ? _r3.price : null, lineId: sk + "|" + _r3.url, msg: sk + " 최종 재시도 성공 — 표면 " + (_r3.price != null ? _r3.price.toLocaleString() + "원" : "가격없음"), metrics: { concurrency, cap, active, done, total } });
            }
          }
          if (recovered.length) { const sv = await saveItemsBG(recovered); savedTotal += (sv && sv.updated) || 0; }
        } finally {
          if (rWinId != null) { try { await handleCloseWin({ winId: rWinId }); } catch (_) {} }
        }
      }
    }
  }

  // 최종 일괄 저장(백스톱) — 소싱처별 증분 저장이 이미 됐으면 중복(무해). toItemBG 공용 매핑.
  const save = await saveItemsBG(results);
  // ★ 저장 결과 표면화 — 조용한 실패 제거([[project_silent_failure_bug_class]]).
  emit("save-result", {
    level: (save && save.ok && (save.updated || 0) > 0) ? "" : "warn",
    msg: "최종 일괄 저장 " + ((save && save.updated) || 0) + "건"
      + ((save && save.error) ? (" ⚠️실패: " + save.error) : ((save && !(save.updated > 0)) ? " ⚠️0건" : "")),
  });

  try { await bgFetch("/api/bundles/" + ENC + "/touch-crawled", { method: "POST" }); } catch (_) {}

  try {
    const rr = await bgFetch("/api/bundles/" + ENC + "/option-matrix").then((x) => x.json());
    const repByLine = {};
    (rr.options || []).forEach((o) => (o.sources || []).forEach((s) => {
      const p = s.crawled_price;
      if (!(p > 0) || !s.product_url) return;
      const inStock = (s.crawled_stock == null) || (s.crawled_stock > 0);
      if (!inStock) return;
      const lid = s.source_key + "|" + s.product_url;
      const cur = repByLine[lid];
      if (!cur || p < cur.sale_price) repByLine[lid] = { sku: o.sku, source_id: s.source_id, source_key: s.source_key, url: s.product_url, sale_price: p, lineId: lid };
    }));
    const reps = Object.values(repByLine);
    if (reps.length) {
      const bd = await bgFetch("/api/source-benefits/breakdowns", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: reps.map((r) => ({ sku: r.sku, source_id: r.source_id, sale_price: r.sale_price })) }),
      }).then((x) => x.json()).catch(() => null);
      const bdres = (bd && bd.results) || {};
      reps.forEach((r) => {
        const b = bdres[r.sku + "|" + r.source_id];
        if (!b || b.error || b.final_price == null) return;
        const surf = Math.round(b.sale_price != null ? b.sale_price : r.sale_price);
        const buy = Math.round(b.final_price);
        emit("item-final", { source: r.source_key, level: "done", lineId: r.lineId, url: r.url, surf: surf, buy: buy, steps: (b.steps || null), msg: r.source_key + " 표면 " + surf.toLocaleString() + "원 → 매입 " + buy.toLocaleString() + "원" });
      });
    }
  } catch (_) {}

  const okCount = results.filter((x) => x.status === "ok").length;
  const finalize = await _finalize();
  const stoppedTxt = endReason === "stopped" ? "중지됨 — " : "완료 — ";
  emit("finish", {
    level: endReason === "stopped" ? "warn" : "done", stopped: endReason === "stopped",
    msg: stoppedTxt + okCount + "/" + results.length + " 성공 · 저장 " + Math.max(savedTotal, (save && save.updated) || 0) + "건" + (finalize && finalize.blocked ? " · 판매차단 " + finalize.blocked : ""),
    metrics: { concurrency, cap, active, done, total, cpu: lastSys.cpu, mem: lastSys.mem },
  });
  return { ok: true, crawled: results.length, ok_count: okCount, save, finalize, stopped: endReason === "stopped" };
}

// ════════════════════════════════════════════════════════════════════
//  [2026-06-18] 백그라운드 크롤 상태 영속 + SW 재가동 자동재개
//   _mgr(큐·running·base·view)를 chrome.storage.session 에 저장한다(브라우저 세션 한정 —
//   브라우저 완전 종료 시 자동 소멸 = 재부팅 후엔 재개 안 함이 맞음). MV3 SW 가 잠들었다/
//   죽었다 다시 깨어나면(top-level 1회 + keepalive 알람) bgBootResume 이 체크포인트를 읽어
//   진행 중이던 크롤을 runQueueBG 로 이어서 돌린다. 추출·아이템 로직은 일절 안 건드림
//   (끊긴 모음전을 처음부터 재크롤만 — 하드리셋+finalize fail-safe 라 잘못 저장 없음).
// ════════════════════════════════════════════════════════════════════
const _CKPT_KEY = "moum_crawl_ckpt";
function bgPersist() {
  try {
    const ck = { queue: _mgr.queue.slice(), running: _mgr.running, base: _mgr.base,
                 paused: _mgr.paused, view: _mgr.view, ts: Date.now() };
    chrome.storage.session.set({ [_CKPT_KEY]: ck }, () => { void chrome.runtime.lastError; });
  } catch (_) {}
}
function bgClearPersist() {
  try { chrome.storage.session.remove(_CKPT_KEY, () => { void chrome.runtime.lastError; }); } catch (_) {}
}
let _bootResumed = false;
function bgBootResume() {
  if (_bootResumed || _mgr.running) return;   // 이미 재가동했거나 진행 중이면 중복 방지
  try {
    chrome.storage.session.get(_CKPT_KEY, (o) => {
      void chrome.runtime.lastError;
      const ck = o && o[_CKPT_KEY];
      if (!ck || !ck.running) return;          // 진행 중이던 크롤 없음 → no-op
      if (_bootResumed || _mgr.running) return; // 비동기 사이 새 크롤이 시작됐으면 양보
      _bootResumed = true;
      _mgr.base = ck.base || _mgr.base;
      _mgr.view = ck.view || {};
      const q = [ck.running];                  // 끊긴 모음전을 큐 맨 앞에 + 나머지 대기열 복원
      (ck.queue || []).forEach((c) => { if (c && q.indexOf(c) < 0) q.push(c); });
      _mgr.queue = q; _mgr.running = null; _mgr.paused = false; _mgr.stopped = false;
      bgEmit({ type: "resume-boot", bundle: ck.running, level: "", msg: "백그라운드 재가동 — 중단된 크롤 이어서 진행" });
      bgEmitQueue();
      runQueueBG();
    });
  } catch (_) {}
}
// SW 가 (재)기동될 때마다 1회 시도 — 진행 중이던 크롤이 있으면 자동 재개.
try { bgBootResume(); } catch (_) {}

// ── [Task E2] 소싱처 주문상태 확인 ─────────────────────────────────────────
//   원본(단독앱) modules/sourcing_checker.py 의 check_order_sync → check_order_status 를
//   메커니즘만 이식: Python Playwright(전용 프로필) 대신, 로그인된 이 브라우저에서 주문 URL 을
//   보이는 창(focused:false)으로 열고 → 사이트별 파서(orderStatusExtractor)를 chrome.scripting
//   으로 주입해 상태를 읽고 → 창을 닫는다(handleCrawl/crawlOne 의 탭 수명주기와 동일).
//
//   반환: { ok, order_status, courier, tracking, site_name, source, logs, error, is_logged_in }
//     · ok=true       : 확정된 상태(배송완료/배송중/취소/반품/교환/미발송)를 읽음
//     · is_logged_in=false : 로그인 페이지로 리다이렉트됨 → 거짓 성공 금지, 정직 표면화
//     · 그 외          : 확인불가/파싱실패 사유를 error 에 담아 반환
//   창 누수 방지: 성공/실패/예외 무관하게 finally 에서 창을 닫는다.
async function handleCheckOrder(payload) {
  const url = payload.url || "";
  const siteKey = payload.site_key || "";
  const siteName = payload.site_name || "";
  const logs = [];
  const fail = (error, extra) => Object.assign({
    ok: false, order_status: "", courier: "", tracking: "",
    site_name: siteName, source: "ext-local", logs, is_logged_in: null, error,
  }, extra || {});

  if (!url) return fail("주문 URL 없음");
  logs.push("[1/3] 로그인된 브라우저로 주문 URL 열기: " + url);

  let win = null;
  try {
    win = await chrome.windows.create({ url, focused: false });
    const tab = win && win.tabs && win.tabs[0];
    if (!tab) return fail("주문 확인 창 생성 실패");
    const tabId = tab.id;
    await waitTabComplete(tabId, 25000);
    // SPA(무신사 등) 상태/송장 DOM 이 로드 완료 뒤 늦게 뜰 수 있어 안정화 대기.
    await new Promise((r) => setTimeout(r, 2500));
    logs.push("[2/3] 페이지 로드 완료 → 사이트별 상태 파싱(site_key=" + (siteKey || "generic") + ")");

    const out = await chrome.scripting.executeScript({
      target: { tabId }, world: "ISOLATED",
      func: orderStatusExtractor, args: [siteKey],
    });
    const res = (out && out[0] && out[0].result) || null;
    if (!res) return fail("상태 파싱 결과 없음(주입 실패)");

    if (res.status === "로그인필요") {
      logs.push("[3/3] 로그인 리다이렉트 감지 → 로그인 필요");
      return {
        ok: false, order_status: "", courier: "", tracking: "",
        site_name: siteName, source: "ext-local", logs, is_logged_in: false,
        error: "로그인 필요 — 이 브라우저에서 소싱처에 로그인 후 재시도",
      };
    }
    logs.push("[3/3] 상태: " + (res.status || "확인불가") + (res.detail ? (" (" + res.detail + ")") : ""));
    const confirmed = !!(res.status && res.status !== "확인불가" && !res.error);
    return {
      ok: confirmed,
      order_status: res.status || "확인불가",
      courier: res.courier || "",
      tracking: res.tracking || "",
      site_name: siteName, source: "ext-local", logs, is_logged_in: true,
      error: res.error || "",
    };
  } catch (e) {
    return fail(String(e && e.message ? e.message : e));
  } finally {
    if (win && win.id != null) { try { await chrome.windows.remove(win.id); } catch (_) {} }
  }
}

// orderStatusExtractor — 주문상세 페이지 컨텍스트(ISOLATED world)에서 실행되는 순수 파서.
//   ⚠️ 이 함수는 chrome.scripting 이 문자열화해 페이지에 주입한다 → 바깥 스코프 변수 참조 금지.
//      (site_key 는 args 로 전달됨.) 페이지 DOM 을 변형(버튼/메뉴 제거)하나 창은 곧 닫히므로 무해.
//
//   원본 sourcing_checker.py 이식(메커니즘 아닌 로직):
//     · _check_login_redirect  (URL 로그인 키워드)                         원본 2038
//     · _check_musinsa         (p.company-name / button.tracking-number)   원본 2067
//     · _check_ssfshop         (checkDelivery onclick 파싱)                원본 2202
//     · _extract_status_from_labels + _classify_status_text (범용 라벨/키워드) 원본 2281·2300
//     · _DOM_CLEAN_JS          (버튼/메뉴 제거 → '반품 신청' 버튼 오탐 방지)  원본 2329
//   미이식(라이브 확정 필요): 무신사 '배송 조회' 버튼 클릭 흐름·롯데 DeliveryTrace URL 이동·
//     쿠키 복원/자동로그인·오판 스냅샷 저장. → 송장/택배사는 best-effort.
function orderStatusExtractor(siteKey) {
  var S = {
    DELIVERED: "배송완료", SHIPPING: "배송중", NOT_SENT: "주문완료(미발송)",
    CANCEL: "취소", RETURN: "반품", EXCHANGE: "교환", UNKNOWN: "확인불가", LOGIN: "로그인필요",
  };
  function has(t, arr) { for (var i = 0; i < arr.length; i++) { if (t.indexOf(arr[i]) >= 0) return true; } return false; }

  // 0) 로그인 리다이렉트 감지 (원본 _check_login_redirect)
  var href = (location.href || "").toLowerCase();
  if (has(href, ["login", "member.one", "signin", "sign-in", "/auth", "lcloginmem"])) {
    return { status: S.LOGIN, courier: "", tracking: "", detail: "로그인 리다이렉트", error: "" };
  }

  var rawBody = "";
  try { rawBody = (document.body && document.body.innerText) || ""; } catch (e) { rawBody = ""; }
  if (!rawBody || rawBody.length < 20) {
    return { status: S.UNKNOWN, courier: "", tracking: "", detail: "", error: "페이지 본문 비어있음(렌더 실패/미로그인 가능)" };
  }
  // 없는 주문/접근 오류 = 계정불일치/번호오류 가능 → 정직하게 확인불가+사유
  if (has(rawBody, ["주문정보를 찾을 수 없", "주문 정보가 없", "존재하지 않는 주문", "찾을 수 없습니다"])) {
    return { status: S.UNKNOWN, courier: "", tracking: "", detail: "", error: "주문 정보 없음(계정 불일치/주문번호 오류 가능)" };
  }

  // 1) 택배사/송장 — 사이트별 셀렉터 우선, 실패 시 범용 라벨 패턴 (DOM 변형 전에 raw 에서 추출)
  var courier = "", tracking = "";
  var COURIERS = ["CJ대한통운", "롯데글로벌로지스", "대한통운", "한진택배", "롯데택배", "우체국택배", "로젠택배", "경동택배"];
  for (var ci = 0; ci < COURIERS.length; ci++) { if (rawBody.indexOf(COURIERS[ci]) >= 0) { courier = COURIERS[ci]; break; } }
  try {
    if (siteKey === "musinsa") {
      var cn = document.querySelector("p.company-name"); if (cn && (cn.innerText || "").trim()) courier = cn.innerText.trim();
      var tn = document.querySelector("button.tracking-number"); if (tn) tracking = (tn.innerText || "").trim();
    } else if (siteKey === "ssfshop") {
      var btn = document.querySelector('button[onclick*="checkDelivery"]');
      if (btn) {
        var oc = btn.getAttribute("onclick") || "";
        var mm = oc.match(/checkDelivery\s*\(\s*['"]([^'"]*)['"]\s*,\s*['"]([^'"]*)['"]/);
        if (mm) { if (mm[1]) courier = mm[1]; tracking = mm[2] || ""; }
      }
    }
  } catch (e) { /* 셀렉터 실패 → 범용 폴백 */ }
  if (!tracking) {
    var TW = ["송장번호", "운송장번호", "운송장", "송장", "트래킹", "tracking"];
    for (var ti = 0; ti < TW.length; ti++) {
      var kw = TW[ti].replace(/\s+/g, "\\s*");
      var m2 = rawBody.match(new RegExp(kw + "\\s*[:：#(]?\\s*([A-Z0-9\\-]{9,20})", "i"));
      if (m2) {
        var cand = m2[1];
        // 전화번호(0으로 시작 10~11자리) 배제
        if (/\d/.test(cand) && !/^0\d{8,10}$/.test(cand.replace(/[-\s]/g, ""))) { tracking = cand; break; }
      }
    }
  }

  // 2) 상태 판별용 정제 텍스트 — 버튼/메뉴 제거로 '반품 신청'·'교환 신청' 버튼 오탐 방지 (원본 _DOM_CLEAN_JS)
  var cleanBody = rawBody;
  try {
    var kill = [
      "button", "a.btn", 'a[class*="btn"]', ".btn-area", ".btns", ".btn-group",
      '[class*="button"]', '[role="button"]', 'input[type="button"]', 'input[type="submit"]',
      "nav", ".gnb", ".lnb", ".side-menu", ".snb", ".menu", ".category",
      "footer", "header", ".header", ".util", ".util-menu", ".quick-menu",
      ".order-btn", ".action-area", ".cs-area", ".cs-menu",
    ];
    kill.forEach(function (sel) {
      try { document.querySelectorAll(sel).forEach(function (el) { el.remove(); }); } catch (e) {}
    });
    cleanBody = (document.body && document.body.innerText) || rawBody;
  } catch (e) { cleanBody = rawBody; }

  // 3) 상태 분류 (원본 _classify_status_text — 종결상태 우선순위: 배송완료 > 반품완료 > 취소 > 반품접수 > 교환 > 배송중 > 미발송)
  function classify(text) {
    if (has(text, ["배송완료", "배달완료"])) return [S.DELIVERED, "배송완료 감지"];
    if (has(text, ["반품완료", "반품 완료", "반품처리완료"])) return [S.RETURN, "반품완료 감지"];
    if (has(text, ["주문취소", "취소완료", "결제취소", "취소 완료"])) return [S.CANCEL, "취소 감지"];
    if (has(text, ["반품접수", "반품신청"])) return [S.RETURN, "반품접수 감지"];
    if (has(text, ["교환완료", "교환 완료", "교환접수", "교환신청"])) return [S.EXCHANGE, "교환 감지"];
    if (has(text, ["배송중", "배송 중", "배달중", "배송출발", "간선상차"])) return [S.SHIPPING, "배송중 감지"];
    if (has(text, ["발송완료", "발송 완료", "출고완료", "출고 완료"])) return [S.SHIPPING, "발송완료 감지"];
    if (has(text, ["결제완료", "주문접수", "상품준비", "주문완료", "입금완료"])) return [S.NOT_SENT, "미발송 감지"];
    return ["", ""];
  }
  // 3a) 라벨 우선 ("주문상태: 배송완료" 등) — 원본 _extract_status_from_labels
  var labels = ["주문상태", "배송상태", "처리상태", "현재상태", "진행상태"];
  var labelVal = "";
  for (var li = 0; li < labels.length; li++) {
    var lm = cleanBody.match(new RegExp(labels[li] + "\\s*[:：\\n\\r\\s]+([가-힣A-Za-z0-9/\\s]{2,20}?)(?:\\n|$|\\s{2,})"));
    if (lm) { var v = (lm[1] || "").trim(); if (v.length >= 2 && v.length <= 15) { labelVal = v; break; } }
  }
  var st = "", dt = "";
  if (labelVal) { var r1 = classify(labelVal); if (r1[0]) { st = r1[0]; dt = "라벨[" + labelVal + "]→" + r1[1]; } }
  if (!st) { var r2 = classify(cleanBody); st = r2[0]; dt = r2[1]; }
  if (!st) {
    // ★ 송장번호만 있고 상태 키워드가 하나도 없으면 배송중으로 단정하지 않는다 —
    //   송장은 배송완료/반품 주문에도 남는다. 금전 판단(블랙스팟)에 오버클레임 금지 →
    //   확인불가(미확정)로 반환하되 송장은 그대로 노출(정보 손실 없음). 상태를 지어내지 않음.
    if (tracking) { st = S.UNKNOWN; dt = "송장번호만 발견 — 상태 미확정"; }
    else { st = S.UNKNOWN; dt = "상태 판별 불가"; }
  }
  return { status: st, courier: courier, tracking: tracking, detail: dt, error: "" };
}

// ══════════════════════════════════════════════════════════════════════════
//  [2026-08-02] 노션 「투두리스트 (영빈)」 요일 칸 캡처 → mou-m.com 업로드
//   왜 여기(로컬 PC)에서 하나: 라이브 서버는 램 2GB·1코어라 크롬을 얹으면
//   2026-07 의 램 고갈 프리즈가 재발한다. 캡처는 이미 노션에 로그인돼 있는
//   이 브라우저가 하는 게 맞다(크롤=로컬 원칙과 같은 결).
//
//   흐름: 1분 알람 → 서버에 "지금 캡처 필요?" 물어봄 → 필요하면 노션을
//         백그라운드 탭으로 열어 오늘 요일 칸만 잘라 PNG 업로드 → 탭 닫음.
//
//   ★캡처는 chrome.debugger(Page.captureScreenshot + captureBeyondViewport)로 한다.
//     captureVisibleTab 은 「보이는 화면」만 찍어서 화면보다 긴 요일 칸이 잘린다.
//     디버거는 백그라운드 탭에도 붙고, 그 탭에만 알림 띠가 뜬다(곧 닫는 탭).
// ══════════════════════════════════════════════════════════════════════════
const NOTION_SHOT_ALARM = "moum-notion-shot";
let _notionShotBusy = false;

function _notionWaitTab(tabId, ms) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    const tick = async () => {
      try {
        const t = await chrome.tabs.get(tabId);
        if (t && t.status === "complete") return resolve(true);
      } catch (_) { return resolve(false); }
      if (Date.now() - t0 > ms) return resolve(false);
      setTimeout(tick, 400);
    };
    tick();
  });
}

// 노션 탭 안에서 실행 — 오늘 요일 칸의 위치·크기를 문서 좌표로 돌려준다.
//   노션 CSS 클래스는 수시로 바뀌므로 클래스에 기대지 않는다. 「요일 글자」를
//   찾아 위로 올라가며 충분히 큰 블록(칸)을 고른다.
async function _notionFindWeekdayRect(weekday) {
  const SEL_BLOCK = "[data-block-id]";
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ★「요일 이름이 하나만 들어있는」 가장 큰 덩어리를 고른다.
  //   그냥 위로 올라가며 「충분히 큰 블록」을 잡으면 여러 요일 칸을 감싸는 바깥
  //   덩어리가 잡혀 **옆 칸까지 같이 찍힌다**(2026-08-02 실측: 일요일 옆에 목요일이
  //   반쯤 붙어 나옴). 요일 라벨 개수로 경계를 판별하면 노션 구조가 바뀌어도 버틴다.
  const DAY_RE = /(월|화|수|목|금|토|일)요일/g;
  function dayCount(el) {
    const t = (el.innerText || "");
    const m = t.match(DAY_RE);
    return m ? m.length : 0;
  }

  function findEl() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node, hit = null;
    while ((node = walker.nextNode())) {
      if ((node.nodeValue || "").trim() === weekday) { hit = node; break; }
    }
    if (!hit) return null;

    // 요일 라벨에서 위로 올라가되, **다른 요일이 섞이기 직전**까지만 올라간다.
    let el = hit.parentElement, best = null;
    while (el && el !== document.body) {
      const r = el.getBoundingClientRect();
      if (dayCount(el) > 1) break;              // 여기부터는 옆 칸이 섞인다
      if (r.width >= 120 && r.height >= 150) best = el;   // 조건 맞으면 계속 키운다
      el = el.parentElement;
    }
    return best || hit.parentElement;
  }

  let el = findEl();
  if (!el) return { ok: false, error: "요일 글자를 못 찾음: " + weekday };

  // ★스크롤로 렌더를 유도하면 안 된다 — 노션은 화면을 벗어난 블록을 **위아래 양쪽**
  //   모두 지운다(2026-08-02 실측: 아래를 그리러 내려가니 위가 지워져 「일요일」만 남음).
  //   대신 호출부가 화면 높이를 아주 크게 위장해 두므로, 여기서는 **스크롤 없이**
  //   높이가 더 안 자랄 때까지 기다리기만 한다.
  let last = -1, stable = 0;
  for (let i = 0; i < 40; i++) {
    el = findEl() || el;
    const h = el.getBoundingClientRect().height;
    if (Math.abs(h - last) < 2) stable++; else stable = 0;
    last = h;
    if (stable >= 3) break;
    await sleep(300);
  }

  el = findEl() || el;
  const r = el.getBoundingClientRect();
  const pad = 8;
  return {
    ok: true,
    x: Math.max(0, r.left + window.scrollX - pad),
    y: Math.max(0, r.top + window.scrollY - pad),
    width: Math.min(r.width + pad * 2, 2000),
    height: Math.min(r.height + pad * 2, 12000),
    viewportH: window.innerHeight,
    dpr: window.devicePixelRatio || 1,
  };
}

async function _notionCapture(pageUrl, weekday) {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const tab = await chrome.tabs.create({ url: pageUrl, active: false });
  if (!tab || tab.id == null) throw new Error("노션 탭 생성 실패");
  const tabId = tab.id;
  let attached = false;
  try {
    await _notionWaitTab(tabId, 40000);
    await chrome.debugger.attach({ tabId }, "1.3");
    attached = true;

    // ★핵심: 화면 높이를 아주 크게 위장한다. 노션은 「보이는 만큼만」 그리므로,
    //   화면이 9000px 이라고 알려주면 요일 칸 전체를 한꺼번에 그린다. 스크롤이
    //   필요 없어져 「아래를 그리면 위가 지워지는」 문제가 원천적으로 사라진다.
    await chrome.debugger.sendCommand({ tabId }, "Emulation.setDeviceMetricsOverride", {
      width: 1440, height: 9000, deviceScaleFactor: 1, mobile: false,
    });
    await sleep(2500);   // 큰 화면으로 다시 그릴 시간

    let rect = null;
    for (let i = 0; i < 12; i++) {
      const out = await chrome.scripting.executeScript({
        target: { tabId }, func: _notionFindWeekdayRect, args: [weekday],
      });
      const r = out && out[0] && out[0].result;
      if (r && r.ok) { rect = r; break; }
      await sleep(1500);
    }
    if (!rect) throw new Error("요일 칸을 못 찾음(" + weekday + ") — 토글이 접혀 있는지 확인");

    const shot = await chrome.debugger.sendCommand({ tabId }, "Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: true,
      clip: { x: rect.x, y: rect.y, width: rect.width, height: rect.height, scale: 1 },
    });
    if (!shot || !shot.data) throw new Error("캡처 결과가 비었음");
    console.log("[moum] 노션 캡처 —", Math.round(rect.width) + "x" + Math.round(rect.height),
                "화면높이", rect.viewportH);
    return shot.data;
  } finally {
    if (attached) {
      try { await chrome.debugger.sendCommand({ tabId }, "Emulation.clearDeviceMetricsOverride"); } catch (_) {}
      try { await chrome.debugger.detach({ tabId }); } catch (_) {}
    }
    try { await chrome.tabs.remove(tabId); } catch (_) {}
  }
}

// base64 → mou-m 탭 안에서 same-origin 업로드(쿠키 동봉). SW 직접 fetch 는 쿠키가 안 실린다.
function _notionUploadInTab(b64, weekday) {
  return (async () => {
    try {
      const bin = atob(b64);
      const arr = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
      const fd = new FormData();
      fd.append("shot", new Blob([arr], { type: "image/png" }), "shot.png");
      const r = await fetch("/api/reports/notion-todo/shot?weekday=" + encodeURIComponent(weekday), {
        method: "POST", credentials: "same-origin", body: fd,
      });
      return { ok: r.ok, status: r.status, text: (await r.text()).slice(0, 200) };
    } catch (e) { return { ok: false, status: 0, text: String(e).slice(0, 200) }; }
  })();
}

async function moumNotionShotOnce() {
  if (_notionShotBusy) return;
  _notionShotBusy = true;
  try {
    const r = await bgFetch("/api/reports/notion-todo/shot/needed?lead=10");
    const j = r && r.json ? await r.json() : null;
    if (!j || !j.needed) return;

    console.log("[moum] 노션 캡처 시작 —", j.weekday, "회차", j.slot);
    const b64 = await _notionCapture(j.page_url, j.weekday);

    const tabId = await ensureServiceTab();
    const out = await chrome.scripting.executeScript({
      target: { tabId }, func: _notionUploadInTab, args: [b64, j.weekday],
    });
    const res = out && out[0] && out[0].result;
    console.log("[moum] 노션 캡처 업로드:", res && res.status, res && res.text);
  } catch (e) {
    console.warn("[moum] 노션 캡처 실패:", String(e));
  } finally {
    _notionShotBusy = false;
    try { await closeServiceTabIfOwned(); } catch (_) {}
  }
}

try {
  chrome.alarms.create(NOTION_SHOT_ALARM, { periodInMinutes: 1 });
  chrome.alarms.onAlarm.addListener((a) => {
    if (a && a.name === NOTION_SHOT_ALARM) moumNotionShotOnce();
  });
} catch (_) {}
