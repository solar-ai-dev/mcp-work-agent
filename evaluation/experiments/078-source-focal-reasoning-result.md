# 078 — focal Schema에서도 native reasoning final 없음

**REJECT(호환성) / 의미 품질 판정 불가.** 사전 고정 최대4회 중 첫049 TASK에서
`done=true / done_reason=stop / response=""`를 반환해 나머지3건은 NOT_DISPATCHED다.
1건 runtime 실패를4건 의미 실패로 세지 않고, 실패 Trial을 교체하지 않았다.

076의 전체 원문·Goal·constraints·Work·catalog·단일 Resource Schema를 그대로 보존하고
think만true로 바꿨다. 첫 응답 strict JSON admission은 INVALID_JSON(빈 문자열)이다.
reasoning 존재 bool은true지만 숨겨진 내용은 저장·검토·응답 대체에 사용하지 않았다.
출력93 tokens를 최종 답변93 tokens라고 표현하면 안 된다.

## 조건·비용·검증

- 실행 SHA `7090565c`, qwen3.5:9b/Q4_K_M,
  digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
  Ollama0.34.0/temp0.05/seed20260923/ctx16384/think=true/stream=false.
- actual1call,input4,007/output93,reported13,248ms,wall13,266ms,load7,567ms.
  usage누락0,binding변경0,retry/repair/rerun-to-pass0.
- 직접 harness 테스트106PASS, scopedRuff/mypyPASS. Canonical92 평가가 아니다.
- GPU 실행 전0MiB/0%/49°C,응답 뒤6,383MiB/0%/59°C(snapshot).
- Product source/활성Prompt/Graph/State/Provider/Approval/WRITE 변경·실행0.

v12의 전체 Source 출력 부재와 같은 failure family가 더 작은 출력에서도 관측됐다.
이 결과로 숨겨진 추론에 정답이 있다고 가정하거나 reasoning 전체가 불가능하다고
결론내리지 않는다. 072 자유 출력에서는 final을 완료한 기록이 있다. 신규 학습 이전에
structured decoding과 native reasoning의 조합이 실제 완료에 미치는 영향을 분리할
여지가 남았다. 과거 버전·다른 모델의 upstream issue를 현재 원인 증명으로 사용하지 않는다.

## 재현

- plan `evaluation/results/078-source-focal-reasoning-plan/preregistered-plan.json`, object hash
  `d0b06b2633e823cd2b4fc64b629382828e4b7d08e4233e983264e14a88cc9caf`.
- raw `evaluation/results/078-source-focal-reasoning-t1/raw.json`, bytes hash
  `1e4fb037877bb176452a26580dde762966b2ce092f33b0df3ca7e517d2fa9f40`.
- 참조076 raw 및Dataset/Fixture/model/current-source hash는 plan에 결속.
  상세 raw는기존 로컬ignore영역이고 이 문서가 원격리뷰용 요약이다.
