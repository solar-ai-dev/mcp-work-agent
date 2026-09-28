# 066 — Source catalog owner-local projection / v45

## 가설·범위

현재 Source FIRST의 반복 실패는 필요한 메일/Task 누락과 새 Output을 기존 조회 대상으로
해석하는 것이다. 입력에 원문이 없거나 생성 Goal이 원문을 대체한 문제는 아니다.
003/063/064의 sparse·분리·fusion·간결화·sampling·membership·few-shot 기각을 반복하지 않는다.
044 Output provenance span과 change-span 분리도 이미 기각됐으므로 새 후보로 삼지 않는다.

남은 작은 진단은 `source_candidates[].read_tool_ids`만 모델 입력에서 제외하는 것이다.
Source owner는 Resource/필요 정보/범위/Work binding을 판단하고 Tool 선택은 별도 owner다.
READ eligibility와 출력 validator는 원 Registry catalog를 그대로 사용한다. 원문·Goal·
Work·선택 identity·reference time·Resource·owned facts·Prompt 역할·Schema·sampling은 유지한다.
Tool ID가 실제 오판 원인이라는 직접 근거는 아직 약하다. 개선을 선결론 내리지 않는다.
이는 15의 비활성 EVALUATION 입력-envelope 진단이며 Product 입력/활성 Prompt를 바꾸지 않는다.
새 projection을 Product assembler가 정식 수용한 계약이라고 주장하지 않는다.

## 고정 예산·판정

CORE-009(메일+Task 누락), 049(기존 근거/새 결과 혼동), 059(기존 성공 reply Source)를
각 후보 FIRST 1회, 총3회로 고정한다. baseline은 v42의 default FIRST 3개만 재사용한다.
Source 파일 변경을 같은 SHA라 속이지 않고 current assembler/transport로 wire 전체와
Schema·현재 validator 결과를 재구성해 같을 때만 재사용한다. 파일 차이는 plan에 별도 기록한다.
Dataset/Fixture/Case/기준시각/model digest·옵션·raw row/파일 hash를 결속한다.

qwen3.5:9b, Ollama0.34.0, Source temp0.05/seed20260923/ctx16384/think=false,
presence 옵션 미전송(모델 기본1.5), timeout180초. 동시1, repair/retry/codec/rerun0.
성공·실패·timeout 모두 보존한다. 모델 실행 중 편집·pytest·다른 generation을 겹치지 않는다.
자원은 시작·종료 snapshot으로 기록하며 peak라고 주장하지 않는다.

- 009: 메일과 Task 진행 근거 둘 다 필요. parent/동등 Gmail 표현 차이는 허용.
- 049: 요청된 기존 메일/Task/Calendar 근거와 새 Task/Event/Draft 계획값의 역할 구별.
- 059: 답장 SEND에 필요한 메일 내용/이력 유지. Source0은 실패.

Source 이름/개수만으로 채점하지 않고 Canonical의 required/forbidden 의미를 적용한다.
strict 구조와 의미를 분리한다. 기존 PASS 회귀 또는 역할 혼동 악화면 기각한다.
명확한 개선일 때만 실제 upstream/더 넓은 반례로 확대하며 같은3개 rerun은 하지 않는다.
재사용 baseline의 지연은 동시 paired 비교가 아니므로 시간 차이를 인과 효과로 주장하지 않는다.
이 Source-only 진단은 RU→Route·업무 성공·92 점수가 아니다. Provider/Graph 실행0.

## 함께 재검토했지만 수정하지 않은 경계

- Calendar fact catalog9개와 자유문자열 required_information 상한8: 실제 오류는 catalog
  전부 복사+미요청 Source/WRITE였다. 유효한 필수9fact 차단 근거가 없어 상한을 늘리지 않음.
- CRITERIA의 업무별 Source item과 Query: Work binding별 항목은 유지되고 full Intent가
  initial/followup으로 전달됨. 공통 Route라는 이유만으로 소실 결함이라 하지 않음.
- 복수 business concept union: 단일 CONCEPT 선택 enum이며 모두를 AND 강제하지 않음.
- 복수 selected exact identity의 충돌은 기존064 prototype에서 이미 확인한 계약 범위이며
  이번 실험의 신규 발견/해결로 세지 않음.

## 실행 전 확인

현재 assembler/transport/Schema/validator로 실제 과거 wire를 재구성해 3/3 동등성을
확인했다(모델0). 과거와 다른 Source 파일 내용은 이미 제거한 all-NOT_REQUIRED 의미 guard이며
이번 FIRST 생성·Schema·선택된 baseline3 검증에는 영향을 주지 않는다. 이를 같은 SHA라고
표현하거나 이 기존 수정의 효과를 새 후보 점수로 승계하지 않는다.

신규21 + 기존 Source/format 회귀를 단일 pytest 프로세스로 실행해 **150 PASS / 13.74초**.
이는 구조/입력/기록 안전 검증이지 모델 의미 성공이 아니다. 후보 결과와 비용·회귀·다음
선택은 원 raw 보존 후 별도 결과 문서에 기록한다.
