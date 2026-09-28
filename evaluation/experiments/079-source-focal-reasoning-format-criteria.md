# 079 — native reasoning × structured decoding 분리

실행 전 고정. 078의 첫049 TASK는 final이 비어 중단됐다. 기존 v12/v13/078은 think=true와
top-level format을 함께 사용했다. v36/v39/v40의 format 생략은 think=false였고, 072는
think=true 자유 출력이나 본문 Schema도 없었다. 따라서 이번에는 **078 wire의 top-level
format만 생략**하여 미검증 상호작용을 확인한다. 역할/본문Schema/원문/Goal/constraints/
Work/catalog/focus/model/sampling/endpoint는 유지한다. Prompt patch가 아니다.

같은 runner의 `--format-mode omitted`만 사용한다. 076 frozen wire에서 think=true를
적용한078형 payload와 비교하면 format 외 변경0이어야 한다. 078 실패를 지우거나 재시도
성공으로 대체하지 않으며, Product에서 format을 제거하지 않는다.

## 고정 실행

049 TASK→005 TASK→017 GMAIL_DRAFT→합성 Draft UPDATE GMAIL_DRAFT, 각1회 최대4.
각180초/concurrency1/retry0/repair0. 원문/Fixture/기준시각은076의 binding 그대로다.
첫/후속 구조 실패(빈 final,invalid JSON/Schema/owner,timeout/error)는 기록 후 미실행
나머지를 NOT_DISPATCHED로 남긴다. 구조가 맞고 의미가 틀리면 고정 control은 진행한다.

실제 wire에는format키가 없다. 응답은 **본문에 고정된 Schema와 현재 Source owner**로
그대로 검증한다. 공통 validator에 넘기는 임시 비교사본은 명시 구분하고 raw wire/hash를
변경하지 않는다. fence제거/부분JSON추출/의미교정/hidden-reasoning사용0.

의미 기준은078과 동일. 실제 실행분의 PARTIAL/PASS/FAIL, final유효성, 원출력→검증값,
calls/tokens/latency를 보고한다. 078은1호출만 실행됐으므로 전체4개비용과 동일분모인
것처럼 비교하지 않는다.076의비추론결과는별도참조다. 새interactionsuccess가있어도
전체Source/RU/Graph/학습필요성/Productactivation성공으로승격하지 않는다.

## 공식 계약 참고

[Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)는
format을 decoding Schema로 받고 본문에도 Schema 제공을 권한다.
[thinking](https://docs.ollama.com/capabilities/thinking)은 generate의 reasoning/final을
별도 field로 정의한다. 과거 타버전의 issue는 이번설치의원인증거로사용하지않는다.
최종공개response만검증하고생성중편집/pytest/다중추론0,Provider0을유지한다.
