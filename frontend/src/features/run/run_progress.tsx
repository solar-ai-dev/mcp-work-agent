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
        {rows.map((row) => {
          const visibleDetails = row.details.filter((detail) => detail.display_text);
          return <details className={`agent-activity-row${row.state === "RUNNING" ? " agent-status-line--active" : ""}`} key={row.execution_id}>
            <summary data-testid="run-event-progress">
              {row.role} · {row.label}
            </summary>
            <div className="agent-activity-detail">
              {visibleDetails.length === 0 ? <p>이 단계에 표시할 추가 업무 사실이 없습니다.</p> : (
                <div className="agent-activity-detail-facts">{visibleDetails.map((detail, index) => (
                  <p key={detail.fact_id ?? `${detail.label}:${detail.value}:${index}`}>
                    {detail.display_text}
                    {detail.state && detail.state !== "RECORDED" ? <span className={`activity-detail-state activity-detail-state--${detail.state.toLowerCase()}`}> · {({ RUNNING: "진행 중", WAITING: "확인 대기", FAILED: "실패" })[detail.state]}</span> : null}
                  </p>
                ))}</div>
              )}
            </div>
          </details>;
        })}
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
