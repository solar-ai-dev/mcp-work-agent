# 084 — 출력 의미를 바꾸지 않고 분기 선택을 먼저 생성

실행 SHA `7dee8b37`. 같은 세 입력×FIRST2회에서 **6 PASS / 0 PARTIAL / 0 FAIL**.
083의 **4 PASS / 0 PARTIAL / 2 FAIL**과 비교한 결과다. 새로운 독립6개 Case나 전체
업무 성공률이 아니다. 의미·Prompt 규칙을 늘리지 않고 top-level format의 각 branch에서
`mode` property만 먼저 옮겼다. Product는 아직 활성화하지 않는다.

## 무엇이 달라졌나

| 입력 | 083 원래 순서 | 084 mode-first | 판단 |
| --- | --- | --- | --- |
| 실제 CORE005 상태·기한만 | 미완료 / 2026-08-10 | 같은 두 필드, 같은 값 | 2 PASS 유지 |
| 합성 완료 상태·메모 | 완료 / 메모 원문 | 제목도 함께 표시, 완료 / 메모 원문 | 2 PASS 유지, 선택량 증가 관측 |
| 합성 메모 정리·원문 인용 금지 | 네 필드를 원문 인용, 명시적 금지 위반 | PROSE로 계정 발급·장비 수령 두 확인 항목을 정리, 인용·수행 완료 주장 없음 | 2 FAIL → 2 PASS |

완료 control 요청은 “상태와 메모를 알려줘”로만 한정돼 있고 “두 필드만”이라는 제한은
없다. 같은 선택 Task의 실제 제목을 문맥으로 표시한 것을 의미 실패로 만들지 않았다.
다만 응답 길이/선택량 증가는 남긴다. 반대로 CORE005의 명시적 “상태와 기한만”은 지켜졌다.
정리 baseline은 이미083에서2 PASS였으며 후보 개선으로 baseline 실패까지 해결했다고
주장하지 않는다. Task lookup의 근거값 재생성 방지와 서술 요청의 선택권을 함께 유지한
작은 진단 결과다.

## 최초 divergence와 실제 전송

083은6/6 `items → mode`, 084는6/6 `mode → payload` 순서였다. 두 반복의 답변은 각
입력에서 byte-identical이다. 반례는 FIRST의 mode 선택이 PROSE로 바뀌었고 기존
materializer/validator가 그대로 전달했다. schema validation과 normalized draft 보존6/6.

`oneOf` branch 순서(FACT 먼저), 허용 필드·값, required 배열, 원문/State/Evidence/snapshot,
Prompt/SYSTEM 문자열 및 runtime 옵션은 모두 그대로다. object equality로 두 wire는 같고
실제 serialization bytes만 다르다. `object_hash`는 이를 보지 못하므로 각 case의 전송
SHA256/property-order를 별도 봉인했고 loaded plan 및 actual dispatch의 일치를 확인했다.
이 결과는 이 backend/입력에서 생성 순서가 의미 선택에 영향을 줬다는 근거다. 모든
9B 실패의 원인이 grammar라는 결론이나, 다른 owner/다른 backend에도 무조건 mode-first를
적용하라는 정책은 아니다. 공식 구현 근거와064의 선행 order 실험은 사전 기준에 연결했다.

## 비용·고정 조건

| 비교 구간 | calls | input tokens | output tokens | reported latency 합(ms) |
| --- | ---: | ---: | ---: | ---: |
| 083 같은 후보6회(역사 재사용) | 6 | 16,958 | 1,000 | 46,575 |
| 084 신규6회 | 6 | 16,958 | 646 | 34,866 |

입력 토큰은 동일하고 출력은354 감소했다. 정리2회 output은592→210, 완료 control은
106→134였다. reported 합계는11,709ms 감소했지만 시점/cache/cold load가 있어 제품
전체 지연 개선으로 단정하지 않는다. 084 첫 lookup load7,609ms(083은7,638ms).
새 호출6, retry/repair/rerun0, usage누락0, 동시성1. GPU약6.4GiB로 단일9B만 실행했다.
모델 digest/Ollama/seed/ctx/think 및 미전송 sampling은083 실제 wire 그대로다.

직접·인접98 tests PASS, scoped Ruff/mypy PASS. tests는 byte-order drift, 두 branch의
기존 admission, 외부 ref/빈 선택, no fallback, 잘못된 runtime 중단, 재실행 방지까지
포함한다. 단위 테스트 점수를 모델 의미 성공률에 합산하지 않는다.

## 판단과 남은 범위

**다음 검증 기준으로 ADOPT, Production는 미반영.** 좁은 lookup 선택과 일반 서술을
같은 compose owner가 선택할 수 있다는 근거가 생겼다. automatic eligibility, 모든
Resource/partial/복합 답변, 실제 upstream 재실행, broader regression은 여전히 미검증이다.
다음에는 새로운 규칙을 더하지 않고 기존 별도 Task notes·Calendar control을 재사용해
인접 회귀를 확인한다. 실제 CORE005 외 compose input 기록이 없는 사례를 기존 실제
upstream 성공으로 꾸미지 않는다.

raw(local ignored): `evaluation/results/084-answer-mode-first-t1/raw.json`

- raw SHA256 `3ce662090733ad1d7c8811a566f8f4541514198463212b69615540beca6a8a1b`
- plan semantic hash `54ef36f328fab699763e2ed79eb31aec27c584f77c2a64f7430be366c62efb81`
- actual per-call byte hashes는 plan/raw에 별도 보존. binding_unchanged=true.
- Product source/활성 Prompt/State/Graph/Approval 변경0, Dataset/Gold 변경0.
- Provider READ/WRITE0, 새 실제 업무 Run0. 미검증 범위를 최종 업무 성공으로 승계하지 않음.
