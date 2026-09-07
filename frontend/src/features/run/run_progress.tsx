import type { RunSnapshot } from "../../api/contract";
import type { RunSseEvent } from "./api/run_sse_event";

export function RunProgress({ snapshot, busy, interactive = true, onResume }: {
  snapshot: RunSnapshot;
  latestEvent?: RunSseEvent | null;
  busy: string | null;
  interactive?: boolean;
  onResume: (resumeKind: "SAFE_CHECKPOINT_RESUME") => void;
}): JSX.Element {
  const manuallyResumable = ["RECOVERY_REQUIRED", "FAILED", "BLOCKED"].includes(snapshot.run.status);
  const resumeAction = interactive && manuallyResumable
    ? snapshot.error?.actions.find((action) => action.kind === "RESUME_SAFE_CHECKPOINT" && action.resume_kind === "SAFE_CHECKPOINT_RESUME")
    : undefined;
  const rows = snapshot.activity?.schema_version === 1 ? snapshot.activity.rows : [];
  return (
    <section className="agent-progress" aria-label="에이전트 진행">
      <div className="agent-progress-lines" aria-live="polite" key={snapshot.run.run_id}>
        {rows.length === 0 ? <p>저장된 단계 이력이 없습니다. 현재 상태와 최종 답변을 확인해 주세요.</p> : null}
        {rows.map((row) => (
          <details className={`agent-activity-row${row.state === "RUNNING" ? " agent-status-line--active" : ""}`} key={row.execution_id}>
            <summary data-testid="run-event-progress">
              <span aria-hidden="true">{({ RUNNING: "●", WAITING: "◷", RECORDED: "✓", PARTIAL: "△", FAILED: "!", INTERRUPTED: "–", UNKNOWN: "?" })[row.state]}</span>
              {" "}{row.role} · {row.label}
            </summary>
            <div className="agent-activity-detail">
              <p className="helper-text">이 실행 시점의 기록입니다. 이후 수정된 현재 계획과 다를 수 있습니다.</p>
              {row.details.length === 0 ? <p>이 단계에 저장된 추가 상세가 없습니다.</p> : (
                <dl>{row.details.map((detail, index) => (
                  <div key={detail.fact_id ?? `${detail.label}:${detail.value}:${index}`}>
                    <dt>
                      {detail.label}
                      {detail.state ? <span className={`activity-detail-state activity-detail-state--${detail.state.toLowerCase()}`}> · {({ RUNNING: "진행 중", WAITING: "확인 대기", RECORDED: "완료", FAILED: "실패" })[detail.state]}</span> : null}
                    </dt>
                    <dd>{detail.value}</dd>
                  </div>
                ))}</dl>
              )}
            </div>
          </details>
        ))}
        {snapshot.run.status === "FAILED" ? <p className="status-warn">작업을 완료하지 못했습니다.</p> : null}
        {snapshot.terminal_result_kind === "PARTIAL" ? <p className="status-warn">확인하거나 완료한 범위만 반영했습니다. 미완료 이유는 기록과 최종 답변을 확인해 주세요.</p> : null}
        {snapshot.run.status === "REAUTH_REQUIRED" ? <p>사용한 연결의 재인증이 필요합니다.</p> : null}
        {snapshot.recovery_summary.unknown_result_action_count > 0 ? <p className="status-warn">외부 변경 여부가 불확실한 작업이 있습니다. 검증 전 성공으로 판단하지 않습니다.</p> : null}
      </div>
      <div className="button-row">
        {resumeAction ? <button className="button-secondary" type="button" disabled={busy === "resume-run"} onClick={() => onResume(resumeAction.resume_kind!)}>재개</button> : null}
      </div>
    </section>
  );
}
