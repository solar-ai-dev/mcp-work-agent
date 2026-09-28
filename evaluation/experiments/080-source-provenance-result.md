# 080 — exact provenance는 보존됐지만 Source 의미 개선은 불안정

판단 **REJECT(Production 미채택)**. 구조적 결속을 통과한 값이 의미적으로 올바른
것은 아니다. Source 표현 확장만으로 기존/신규 대상 혼동이 해결되지 않았다.

실행 SHA `7f9fcfa5` / plan SHA256
`215ff8b8be279d4d051c90b8f04338faf1311fc148eaf5e4492fdfd8a9e52c63`.
Core017/049/005/009/059 각 FIRST1, 고정5 모두 실행·보존, repair/retry0.

| Case | 기존 Source → 080 | 최초 차이/남은 문제 |
| --- | --- | --- |
|005|PASS → PASS|선택 Task의 상태·기한/SINGULAR/Work 유지. TaskList 추가는 보조 container 가능성이 있어 의미 자동 감점하지 않고 비용 후보로 분리.|
|009|FAIL → PARTIAL|빠졌던 TASK/notes/due/status 회복. 다만 Thread는 identity만, Message는 message_history로 사실 귀속이 부정확. 실제 메일 획득 실패까지 관측한 것은 아님.|
|017|PARTIAL → PARTIAL|Task/Calendar 유지. 새로 작성할 ‘메일 초안을’을 기존 GMAIL_DRAFT READ의 원문 근거로 잘못 선택.|
|049|PARTIAL → FAIL|기존 Atlas 자료를 봐야 하는데 TASK는 ‘인계 작업을’, EVENT는 ‘점검 일정과’로 새 산출물 구간을 선택하고 SINGULAR로 축소. first model output에서 발생.|
|059|PASS → PARTIAL|답장 근거는 유지하지만 ‘바로 답장 보내줘’를 기존 Draft 조회의 근거로 사용. 새로운 불필요 Source.|

Source-only 역사 baseline **2P/2PART/1F → 1P/3PART/1F**.
기존 PASS059 회귀, 기존 PARTIAL049 악화,009 부분 개선이다. Source 해석 판정이지
전체 RU→Tool Route·Query·Provider·업무 성공률이 아니다. 독립 검수도 같은 결론이다.
079의 문구 한정 위험과 실제 조회 실패를 구분하는 addendum은 별도 보존했다.

## 구조·handoff 검증

- strict5/5, 현재 token range와 원문 offset/text 결속5/5, end binding unchanged=true.
- 직접34 + 인접57 = **91 tests PASS**, scoped Ruff/mypy PASS.
- 합성 compiled component는 실제 merge→Registry route binding→Query input projection을
  호출한다. shared Gmail READ1과 두 Work union·기존 anchors 불변을 확인했다.
  fine Resource는 원 Route ID로 연결해 Query의 coarse EMAIL/CALENDAR에서 역추정하지 않는다.
- 다른 선택 identity·원문·Work·Source·artifact·중복 Route 변조 반례 거절.
  유효하지만 잘못 고른 새 Output 구간은 validator가 정답으로 바꾸지 않는다.
- 테스트 초기에는 RouteBindingCandidate dataclass를 dict로 취급한 fixture 오류13건이
  발생했다. 평가 테스트만 수정했으며 이 오류를 제품 결함/모델 실패로 세지 않았다.
- 이 component 결과는 실제 Query LLM/Provider/Production MainGraph 성공이 아니다.

## 비용과 다음 축

| 구분 | calls | input/output tokens | reported latency 합 |
| --- | ---: | ---: | ---: |
|역사 Source 참조|5|20,442 / 1,119|51,211ms|
|080 신규|5|24,059 / 1,732|79,510ms|

모델/Runtime/options는 동결했으나 역사 baseline과 동시 paired timing이 아니므로 순수
추론 지연 증가율로 단정하지 않는다. generation 동시1/실행 중 편집·pytest0.
원본 Source 입력과 sampling 보존, 새 full92·Provider READ/WRITE·승인·Product 활성화0.

raw `evaluation/results/080-source-provenance-t1/raw.json`, SHA256
`de94aaa3850f8df0554ffd31798297081810fc49770305711a190f74a6369e53`.
상세 raw는 로컬 ignore, 비민감 결론·runner·criteria·tests만 원격에 보존한다.

같은 Source Prompt/필드 추가의 재시도는 새 근거가 있을 때만 한다. 이 후보의 기각으로
Epic을 종료하지 않는다. 다음 유력 축은067/068에서 확정값이 실제 입력에 있어도 다시
서술하며 과잉해석한 Planning ANSWER다. 단일 Task lookup에서 모델은 fact ref를 선택하고
값은 기존 snapshot/formatter가 렌더하는 output ownership 후보를 작은 범위로 비교한다.
일반 요약을 정형 필드로 강제하거나 기존 completeness guard를 완화하지 않는다.
