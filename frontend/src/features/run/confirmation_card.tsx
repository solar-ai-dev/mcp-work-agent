import type { PendingInterrupt } from "../../api/contract";
import { UserActionCard } from "../../ui/user_action_card";

export function ConfirmationCard({ interrupt, text, busy, onTextChange, onSubmit }: {
  interrupt: PendingInterrupt;
  text: string;
  busy: boolean;
  onTextChange: (value: string) => void;
  onSubmit: (selectedOption?: string) => void;
}): JSX.Element {
  return (
    <UserActionCard
      tone="confirmation"
      glyph="confirmation"
      title="추가 정보가 필요해요"
      description={interrupt.question}
      ariaLabel="추가 확인"
      footer={interrupt.response_mode === "OPTION" ? undefined : (
        <div className="user-action-footer-main">
          <button className="button-primary" type="button" disabled={busy || !text.trim()} onClick={() => onSubmit()}>응답 보내기</button>
        </div>
      )}
    >
      {interrupt.response_mode === "OPTION" ? (
        <div className="user-action-options" aria-label="선택 항목">
          {interrupt.options.map((option) => <button className="user-action-option" type="button" key={option} disabled={busy} onClick={() => onSubmit(option)}>{option}</button>)}
        </div>
      ) : (
        <label className="user-action-input" htmlFor={`confirmation-answer-${interrupt.interrupt_id}`}>
          답변
          <textarea id={`confirmation-answer-${interrupt.interrupt_id}`} rows={3} maxLength={4000} disabled={busy} value={text} onChange={(event) => onTextChange(event.target.value)} />
        </label>
      )}
    </UserActionCard>
  );
}
