# 064 — Output format 생략 + 엄격 fence admission의 Core5 확장 기준

## 가설과 고정 범위

v36의 Core005/017/049에서는 decoding format 생략 시 내용이 보존됐지만 Product strict
JSON parser는 코드펜스를 거절했다. v37의 JSON-mode는005의 불필요 WRITE를 고치지 못했다.
다음 후보는 **기존 Prompt·본문 schema·sampling을 유지하고 format만 생략한 생성 +
엄격한 단일 json fence admission**이다. codec은 문법 wrapper만 제거하고 의미를 고치지 않는다.
먼저 저장된 v36/v37 raw를 모델0으로 재검증한 뒤 이 별도 Core5를 실행한다.

실행 전 대상은 **Core009/019/023/025/059 × baseline/candidate × 각1회 = 신규10calls**로
고정한다. 순서는009 baseline→candidate,019 candidate→baseline,023 baseline→candidate,
025 candidate→baseline,059 baseline→candidate다. 각 HTTP timeout180초, 직렬1개,
retry/repair/revision/Graph/Provider 호출0. 실패도 모두 보존하고 Trial을 대체하지 않는다.

이전 Core8의 실제 Production Output FIRST(call5) **입력만 재사용**한다. 과거 Prompt1.1.0의
응답·wire·점수를 현재baseline으로 승계하지 않는다. 현재Prompt1.1.1과 Product assembler/
transport로 양 arm을 새로 만들고 baseline도 다시 실행한다. payload/input/schema/options는
같고 candidate에서 top-level format 하나만 제거한다. 원 PromptRef·원 wire hash와 신규
PromptRef·wire hash를 구분해 기록한다. upstream Goal/Work를 정답으로 교체하지 않는다.

입력 출처:

- 009/019/023: `evaluation/results/064-connected-core8-t1/<CASE-ID>/production/calls.json`
- 025/059: `evaluation/results/064-connected-core8-continuation-t1/<CASE-ID>/production/calls.json`

각 원 call·raw·plan/hash, 신규 HEAD/실행 코드/현재Prompt/본문schema/model digest/runtime,
Canonical dataset/fixture/Case reference time·fault binding을 사전 plan에 결속한다.
Holdout/Stress는 사용하지 않는다. 실제 결과를 본 뒤 Case를 추가·제거하지 않는다.

## Output owner의 의미 기준

Canonical user request와 current owner 책임에서 다음을 도출한다. Gold·평가 설명은 모델에
전달하지 않는다. Work 수를 강제하지 않고 현재 확정된 Work binding의 사용자 결과를 보존한다.

| Case | 선택 이유 | 필요한 Output 의미 | 명확한 실패 |
| --- | --- | --- | --- |
|009|복수자료 READ·불필요 WRITE 반례|메일/Task로 상황을 알려 달라는 요청 → 빈 Output|Task/Draft 생성 등 추가 WRITE|
|019|미확정 시간·복수 사용자 결과 control|요청한 Event CREATE와 안내 Draft CREATE를 각각 해당 Work에 유지|하나 누락, SEND로 변경, 불필요 추가 WRITE|
|023|참고자료와 작성 대상 구별|Calendar Event CREATE|참고한 메일/Task를 변경하거나 Draft 추가|
|025|기존 단일 Event 성공 control|Calendar Event CREATE|누락, effect 변경, 다른 WRITE 추가|
|059|명시 SEND의 반대효과 control|GMAIL_MESSAGE SEND|Draft CREATE/UPDATE로 축소 또는 불필요 추가|

019는 소요시간이 부족하므로 관련 READ 후 구체적 확인이 가능한 정상 Case다. 이 단계에서
Event/Draft의 요청 의도를 보존하는 것은 실제 생성·정확한 Preview 완료 판정이 아니다.
기본 소요시간을 발명해 승인안으로 확정하거나 즉시 실행하면 전체 업무에서는 실패다.
이번 schema가 표현하지 않는 수신자/날짜/본문/Source/Action arguments는 미검증으로 남긴다.

사전 입력 검수에서 발견한 upstream 의미는 수정하지 않는다. 009에는 명시되지 않은 SEND
금지 판정, 019에는 Goal 완료조건의 메일 발송 표현, 025에는 명시되지 않은 title/description
제약이 있다. 059의 Goal은 이미 확인했다고 알리는 답장을 확인 요청으로 흔들고 있다.
023은 Event 의도와10시/30분을 유지하지만 Source 존재 조건·예정일 투영은 별도 확인 대상이다.
이는 Output 단계가 새로 만든 오류와 구분해 보고하며, 새 후보가 원문을 우선해 올바른
Output을 고르더라도 전체 upstream 의미가 복구됐다고 해석하지 않는다.

## 판정과 확대 조건

- 첫 원 응답의 strict JSON/schema/owner 판정과 codec 이후 판정을 각각 저장한다.
- codec은 응답 전체가 lowercase `json` 태그의 단일 완결 fence일 때만 제거한다.
  앞뒤 설명·여러 fence·부분 JSON·기타 언어·불완전 JSON은 거절한다. 원 응답은 불변이다.
- 양 arm 모두 같은 schema·closed binding·prohibition owner validator를 적용한다.
- 업무 의미 판정은 요청되지 않은 WRITE, 필요한 결과/effect/Work binding 누락·변경을
  포함한다. Resource/effect 개수만 맞다고 전체 의미 성공이라 하지 않는다.
- 원 raw는 UNREVIEWED로 보존하고 별도 근거 기반 PASS/PARTIAL/FAIL을 남긴다.
- 불필요 WRITE가 증가하거나 기존 올바른 Output이 회귀하면 Product 채택하지 않는다.
  개선이 없으면 같은 format 실험을 더 반복하지 않고 최초 실패를 분리한다.
- owner 결과가 명확히 개선되고 control 회귀가 없을 때만 실제 upstream을 사용하는
  compiled RU→Tool Route의 작은 연결 확인으로 넓힌다. 이10calls만으로 Product 활성화나
  Canonical92/업무 성공을 선언하지 않는다.

calls/input·output tokens/reported·wall latency와 누락usage를 기록한다. cold-load 편향을
분리하고 작은 표본으로 성능 개선을 일반화하지 않는다. 모델 실행 중 pytest/mypy/다른
모델을 겹치지 않으며 RAM/VRAM/온도를 시작·종료 시 확인한다. 현재 사용 가능한 컴퓨터
자원이 부족하면 미실행 Case를 보존하고 환경을 회복한 뒤 **미실행 부분만** 이어간다.
