# 066 v45 — Tool metadata 제외는 Source 오류를 교체: REJECT

## 비교 조건

실행 HEAD `4761c381e6ad367ed0ff089a7bbebf5865813616`. 사전 기준은
`066-source-catalog-projection-v45.md`이며 Product 변경0이다. 기존 Source FIRST에서
`source_candidates[].read_tool_ids`만 system/prompt 두 입력 사본에서 제외했다.
원문·Goal·Work·선택 identity·Resource/facts·role·Schema·validator·sampling은 동일하다.
READ eligibility는 전체 원 Registry catalog와 exact 대조했다.

CORE009/049/059 각 후보1회, 신규3회·과거 baseline3회 재사용. 원 baseline SHA는
`e9a09524f398b6e6f34b841fbdb239ed930fc32f`로 현재와 다르다. 현재 assembler/transport의
전체 wire·Schema·validator 결과가 같은지 실행 전3/3 재구성했다. Source 파일의 과거 대비
차이는 이미 제거한 all-NOT_REQUIRED 의미 guard였고 이번 FIRST/Schema에는 영향이 없다.

모델 qwen3.5:9b digest
`6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`, Ollama0.34.0,
temperature0.05/seed20260923/ctx16384/think=false. presence 옵션은 미전송(모델기본1.5).
후보3/3 strict 구조 통과, 원 raw와 validated 값 동일, repair/retry/codec/rerun0.

## 어떤 의미가 달라졌는가

| Case | baseline → v45 | 최초 차이와 업무 영향 |
| --- | --- | --- |
| CORE009 | FAIL → PASS | baseline의 Task NOT_REQUIRED가 TASK CRITERIA와 notes/due/completion_status로 바뀌어 필요한 메일+Task 근거를 함께 요구. TaskList identity 추가는 과선택 관찰이지만 parent 접근 자체를 실패로 세지 않음 |
| CORE049 | PARTIAL → FAIL | 입력의 원문·Goal·Work에 메일/작업/캘린더가 남아 있는데 FIRST에서 메일과 Task 모두 NOT_REQUIRED, Event만 요구. 기존 Draft 과선정 제거가 필수 근거 누락을 상쇄하지 않음 |
| CORE059 | PASS → PARTIAL | Reply용 메일 내용/이력은 유지하나 요청하지 않은 기존 Draft snapshot을 새 필수 Source로 추가. SINGULAR는 특정 Reply 대상 해석일 수 있어 그 값만으로 별도 회귀라 하지 않음 |

양쪽 모두 **1 PASS / 1 PARTIAL / 1 FAIL**이지만 같은 업무가 통과한 것이 아니다.
필수 근거 누락 복구1, 부분결과 악화1, 기존 PASS 회귀1이다. 009의 필수 Task 누락은
기존 v42/v44의 FAIL을 유지했다. 일부 메일 근거가 있다는 이유로 PARTIAL로 사후 완화하지 않았다.
독립 재검수도 최종 동일 판정이다. 최초 의미 변화는 모두 Source FIRST이며 validator의
수정이나 downstream 실행 결과가 아니다. SEND effect 변화·실제 Confirmation 발생은 미검증이다.

**REJECT / Product 유지.** Tool ID를 숨기는 것만으로 역할 선택이 안정되지 않았다.
이를 새 Prompt 표현을 더 추가할 근거로 사용하지 않는다. 제한된 catalog metadata 부담이
유일한 원인이라는 가설은 지지되지 않았다. Source owner의 의미 오류는 미해결이다.

## 비용·자원·검증 경계

| 비교 | calls | input / output tokens | reported latency |
| --- | ---: | ---: | ---: |
| baseline 재사용 | 3 | 12,216 / 670 | 24,619ms |
| 후보 신규 | 3 | 11,517 / 601 | 45,337ms |

후보 wall45,452ms, load14,615ms, usage 누락0. 입력699token 감소지만 첫 load와 실행 시점이
다르므로 지연의 인과 효과는 주장하지 않는다. 한 번의 개선을 반복 안정성으로 부르지 않는다.
시작 여유RAM19.73/31.71GiB·GPU0/8188MiB, generation전46°C, 중간4841MiB/45%/59°C,
종료 여유RAM16.25GiB·GPU4843MiB/0%/55°C. snapshot이지 peak가 아니다.
generation 동시1, 모델 실행 중 pytest/편집0. 다른 사용자 process·서버 재시작0.

사전 직접/관련 테스트150 PASS/13.74s, Ruff와 두 모듈 mypy PASS. Source-only 실제9B
진단이며 실제 RU upstream/Tool Route/Provider/Planning/92 전체 업무 성공은 미검증이다.
Product·활성Prompt·State·Graph·승인·실행·Dataset 변경0, 외부 Provider READ/WRITE0.

## 근거·다음 판단

- raw: `evaluation/results/066-source-catalog-v45-t1/raw.json`, SHA256
  `eec9c173953794e1766905786071186c257b4869a5826ee887b0ed6d8f29a3c4`.
- plan: `evaluation/results/066-source-catalog-v45-plan/preregistered-plan.json`, object hash
  `b9d3ffdc8d47cff5bf98fa563904fcea028a01857c5173d1aca1039c6e8de7d9`.
- Dataset `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`;
  Fixture `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`.

현재 Source 실패를 다른 downstream 수정의 성과로 가리지 않는다. 다음은 이미 채택한
수정의 실제 연결 검증이다. 과거 CORE005 MainGraph T2는 Output Prompt1.1.0에서 미요청
UPDATE/SEND로 ANSWER에 도달하지 못했다. 이후 Product는 Output1.1.1, repair/authority/
handoff와 Planning 경계가 바뀌었다. 새 Trial로 현재 실제 upstream→MainGraph를 1회 확인하고,
옛 실패를 대체하지 않으며 새 실패가 나면 그 최초 owner를 기록한다. v45는 적용하지 않는다.
