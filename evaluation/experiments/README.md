# Experiments

기본 기능 baseline과 이후 실제 실험의 정의·최종 결과 요약을 순서대로 기록한다. 각 실험은 `000-baseline-...`, `001-...`, `002-...` 형식의 파일 하나로 관리한다.

새 trace, JSON, ZIP은 Git에 누적하지 않고 로컬 [results](../results/)에만 둔다.
cleanup 이전의 과거 원시 관측과 누적 실행 기록은 Git history로 보존하며,
여기에는 비교에 필요한 장기 요약만 남긴다.

현재 branch에서 복원되지 않은 과거 기록과 번호 충돌을 피하기 위해 최근 RU 기록은
Git history와 Issue에서 확인되는 마지막 번호 043 다음부터 이어간다.

- [044 — RU source prompt 1.0.3 — REJECT](044-ru-source-prompt-103.md)
- [045 — #287 preservation floor — REJECT](045-ru287-preservation-floor.md)
- [046 — #287 direct-fact requirement — REJECT](046-ru287-direct-fact-requirement.md)
- [047 — #288 single-authority same-call — REJECT](047-ru288-single-authority-same-call.md)
- [048 — #294 minimal few-shot — REJECT](048-ru294-minimal-fewshot.md)
- [049 — #294 concise zero-shot — REJECT](049-ru294-concise-zeroshot.md)
- [050 — #294 requested-fact evaluator correction — COMPLETED](050-ru294-requested-fact-evaluator-correction.md)

#288 Candidate F는 실행하지 않았으며 corrected evaluator 기반의 별도 승인 전까지 `NOT RUN / HOLD`다.
