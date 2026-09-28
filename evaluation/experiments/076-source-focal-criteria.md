# 076 — 전체 catalog 유지, 단일 Resource FIRST 판단

## 가설과 기존기각과의차이

074/075는정확한원문·자연어해석이있어도Source누락/과잉이계속됐다.
한응답에서여러Resource를공동선택하는부담의영향을좁게검사한다.
v43의all-membership→positive-details, family의catalog축소, v23의실패repair와다르다.
이번은전체Sourcecatalog와원문을그대로받는FIRST에서focus1개의필요여부+details를
함께판정한다. 074/075기각변경을얹지않고원Product입력/role을기준으로한다.

역할본문의전체반환책임3문구만단일Resource책임으로정합화한다. 새로운업무규칙/예시/
단어trigger를추가하지않는다. required_information/scope/Work의제품정의는그대로다.
현재SourceSchema를해당후보1개로닫고기존validator를적용한다. 나머지후보는결정하지
않았으므로NOT_REQUIRED를채우거나전체merge하지않는다.

## 고정실행8회

- Core017→049→005, 각각TASK→GMAIL_DRAFT FIRST1씩, 총6호출.
- 기존v43합성DraftUPDATE→자료제공DraftCREATE control, 각각GMAIL_DRAFT1, 총2호출.
- Core선택은source누락/새Output오인/기존selected성공을포함. 합성반례는'항상Draft없음'
  편향을확인한다. Canonical92분모에합성자료를합치지않는다.
- Core는v42actualsourcewire/current재구성으로잠근다. 합성은v43원raw/원입력hash를
  재사용하고현재Productwire와대조한다. 새upstream/Provider실행이라고하지않는다.
- 각focus FIRST1,concurrency1,timeout180,retry/repair/rerun0.
- qwen3.5:9b 동일digest/temp0.05/seed20260923/ctx16384/think=false,다른옵션불변.
- 실패도보존; transport/미완료/모델drift는미실행을표시하고회로중단.
- generation중편집/pytest/다른모델0. 실제Provider/Approval/WRITE/Graph0.

## 판정

- TASK:005는선택단일Task상태·기한;017은현재Task목록;049는기존AtlasTask정보.
  새로만들Task마감이나출력수신자를기존자료의필수값으로요구하지않음.
- GMAIL_DRAFT:017/049새초안·005Task조회는기존Draft근거요구가없음.
  합성UPDATE는현재본문·보존값SINGULAR필요; 합성CREATE는명시조회금지/주어진값보존.
- 긍정/부정판정뿐아니라details/scope/Work잘못된생성도실패로기록한다.
- 다른Source,전체RU/Route/Source집합,최종업무는미평가. partial결과를합쳐업무PASS금지.
- 개선이면전체catalog합성/대조군/실제upstream에서호출비용까지검증할근거로만사용.
  효과없으면같은Prompt문구를더추가하거나전체92를실행하지않는다.
- 선택Task기존성공과DraftUPDATE정상필요성을회귀시키면채택하지않는다.

원본실험의실패는그대로유지하고, Productsource/Promptactivation/State/Node변경0.
