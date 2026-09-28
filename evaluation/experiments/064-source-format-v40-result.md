# 064 v40 — Source FIRST format 생략 진단: REJECT

실행 HEAD `4242f7d75b450ef80f4ab45f2d784c4335720530`.
사전 기준은 `064-source-format-v40-criteria.md`이며 기존 v35 constrained FIRST
005/017/049 세 개를 재사용하고 후보만 각1회, **신규3calls** 실행했다.
반복·repair·retry·Graph·외부 업무 Provider 호출0. 과거 baseline을 새 실행으로 세지 않았다.

## 첫 출력에서 관측한 차이

| Case | 기존 constrained FIRST | format 생략 후보 FIRST | 판정 근거 |
| --- | --- | --- | --- |
|005|선택 TASK/SINGULAR 및 상태·기한 포함. 요청하지 않은 title/notes/identity까지 필요 사실에 포함|같은 Task fact inventory를 복사하고 TASK_LIST의 identity/title도 필수로 추가. 나머지8개 후보 판정 누락|필수 Task 사실을 잃지는 않았지만 필요한 정보 범위의 과잉이 해소되지 않았고 기존 exact-set 계약 실패|
|017|Task/Event 보존, TaskList/Calendar parent와 별도 필요성이 없는 기존 Draft도 필수|동일5개 Source 유지, Calendar metadata 및 Event fact inventory로 확장. 나머지5개 후보 판정 누락, Event 정보9개로 기존 최대8 계약도 실패|작성할 새 Draft와 조회할 기존 Draft의 역할 혼동이 그대로. 필수 Task/Event 보존만으로 의미 개선이라고 할 수 없음|
|049|명시한 Mail/Task/Event 근거 보존, 기존 Draft/parent 자료도 필수|필수 근거와 기존 Draft 유지. Attachment/Freebusy까지 필수로 추가, NOT_REQUIRED GitHub에 금지된 추가 필드. Event 정보9개|확대된 자료의 필수성이 입력에서 입증되지 않았고 원래 혼동도 남음. 기존 구조 계약 실패|

사용자 요청의 필수 자료는 양쪽 **3/3에서 포함**되지만, 신규 Output을 위한 기존 Draft의
필수 의존성은017/049에서 그대로 남는다. 005의 상태·기한 외 fact 과잉도 남는다.
Attachment/Freebusy/parent 자료를 읽었다는 이유만으로 업무 실패나 금지 위반을
선언하지 않는다. 여기서의 문제는 별도 근거 없이 **필수**로 지정한 범위이며, 실제
조회 차단·Evidence·작성안에 미칠 영향은 실행하지 않았다. 합리적인 Thread/Message
대안이나 WorkUnit 개수 하나를 Gold로 강제하지 않았다.

모든 emitted positive item은 기존 `work-1`을 사용했고 주요 target_scope는 유지했다.
이는 Work 귀속 ID/자료 유형 보존이지 Goal·시간·Output 등 upstream 오류까지 복구했다는
뜻이 아니다. 입력 Goal/Work/조건과 과거 raw는 변경하지 않았다.

## 구조와 의미를 분리한 결정

- 기존 strict JSON/schema/owner 검증: **3/3 VALIDATED**(현재 validator 재검증).
- 후보 원 strict JSON: **0/3**, 모두 단일 json fence.
- 엄격 fence wrapper 제거 후 기존 schema: **0/3**, 위 exact-set/필드/항목수 오류.
- 누락한 후보에 NOT_REQUIRED를 채우거나 초과 사실을 잘라내지 않았다.
- 최초 차이는 모두 LLM FIRST이며 codec/normalizer의 의미 수정은 없다.

**REJECT**: Source에서도 format 생략을 Product에 적용하지 않는다.
엄격 decoding이 fact inventory 복사나 Source/Output 역할 혼동의 유일한 원인이라는
가설을 지지하지 않는다. 제약을 제거해도 해당 의미 오류가 남고 형식·출력량이 악화됐다.
반대로 이것만으로 모델 한계라고 확정하지도 않는다.

Source owner 진단의 구조·내용 관측이며 최종 업무 PASS/PARTIAL/FAIL 또는 Canonical92
점수를 새로 만들지 않는다. 다른 owner의 실험 결과와 합산하지 않는다. 같은 format
변형의 추가 실행과 불안정 후보의92개 확장은 하지 않는다. Product parser/Prompt/
Schema/State/예산/activation은 그대로다. 다음 작업은 이미 별도 재현한 Review의
0-call 예산 오차단 및 Planning ANSWER의 dispatch trace 누락을 수정·검증하는 것이다.

## 비용·조건·자원

모델 qwen3.5:9b, digest
`6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
Source Prompt1.1.0 hash `153294cfdb512a6b252a1d9593692001a088489268ac88b4efbec4317311c092`.
temperature0.05, seed20260923, ctx16384, thinkfalse, timeout180초.
실제 Product assembler로 원 wire hash3/3 일치 확인 후 top-level format만 삭제했다.

| 측정 | 기존 응답3 재사용 | 신규 후보3 |
| --- | ---: | ---: |
| input / output tokens |12,730 / 794|12,730 / 1,516|
| reported / wall latency 합|34,735 / 34,796ms|64,902 / 65,001ms|
| usage 누락 / repair / retry|0 / 0 / 0|0 / 0 / 0|

후보 첫 cold load7,654ms와 비동시 단발 비교이므로 지연 차이를 순수 format 효과나 반복
성능으로 일반화하지 않는다. 신규 요청3개 모두 RETURNED이며 실패 대체는 없다.
단일 모델 직렬, 실행 중 코드편집/pytest/mypy/다른 모델0. RAM 여유20.1→18.0GB,
VRAM 종료6,385MiB, GPU 관측42→60→63°C. 사용자 프로그램 종료0.

Dataset hash `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`,
fixture hash `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`.
005 기준시각은 원 실행 `2026-09-28T18:50:58+09:00`,017/049는
`2026-08-07T09:00:00+09:00`; fault/Case/원 call/hash도 plan에 결속했다.

## 보존 근거

- raw: `evaluation/results/064-source-format-v40-t1/raw.json`, SHA256
  `8ce324a42dfa04bf940625d07571ee75ef8af358605818a97c31d53609e6b2da`.
- plan: `evaluation/results/064-source-format-v40-plan/preregistered-plan.json`, 파일SHA256
  `fcdcac66423b4103bec75517f9273cd3fbdba18c9e367552243a0e234b27079d`,
  object hash `544e9ad782b73b1ea14676dc38833cf569c5a9a5cd02f18b4fca468945f36c74`.
- raw 의미 표식 UNREVIEWED는 유지하며 이 문서가 별도 내용 검수다. 상세 raw는 로컬ignore,
  사전 기준·실행기·검증·비민감 결론은 버전관리한다.
- 독립 읽기 검수도 input/Prompt/options/hash와 위 REJECT 판정에 일치했다. 검수용 추가
  모델 호출은0이다. 기존 sparse/key-map/Output handoff/envelope 실패축도 다시 실행하지 않는다.
