import { useEffect, useState } from "react";
import type { ContextPreview } from "../../api/contract";

type Props = {
  preview: ContextPreview;
  busy: boolean;
  onAdjust: (
    kind: "EXCLUDE_EVIDENCE" | "RETRIEVE_MORE",
    value: string[] | string,
  ) => Promise<void>;
};

export function ContextPreviewCard({ preview, busy, onAdjust }: Props): JSX.Element {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedCategory, setSelectedCategory] = useState<ContextCategory | null>(null);
  const [requestedInformation, setRequestedInformation] = useState("");
  useEffect(() => {
    setSelected(new Set());
    setExpanded(new Set());
    setSelectedCategory(null);
    setRequestedInformation("");
  }, [preview.retrieval_revision]);
  useEffect(() => {
    if (!open) return undefined;
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  const canExclude = preview.adjustment_allowed
    && preview.allowed_adjustments.includes("EXCLUDE_EVIDENCE");
  const canRetrieveMore = preview.adjustment_allowed
    && preview.allowed_adjustments.includes("RETRIEVE_MORE");
  const githubCount = preview.github_count ?? 0;
  const contextCount = preview.gmail_count + preview.tasks_count + preview.calendar_count + githubCount;
  const visibleItems = selectedCategory === null
    ? preview.items
    : preview.items.filter((item) => item.category === selectedCategory);

  return (
    <div className="context-preview-anchor">
      <button className="context-preview-trigger" type="button" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>
        사용 컨텍스트 <strong>{contextCount}개</strong>
      </button>
      {open ? (
        <div className="context-modal-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target) setOpen(false); }}>
          <section className="context-modal" role="dialog" aria-modal="true" aria-labelledby="context-modal-title">
            <header>
              <div>
                <strong id="context-modal-title">사용 컨텍스트 {contextCount}개</strong>
                <p className="context-kind-switcher" aria-label="컨텍스트 종류">
                  {CONTEXT_CATEGORIES.map(({ category, label }, index) => (
                    <span key={category}>
                      {index > 0 ? <span aria-hidden="true"> · </span> : null}
                      <button
                        className={`context-kind-link${selectedCategory === category ? " selected" : ""}`}
                        type="button"
                        aria-pressed={selectedCategory === category}
                        onClick={() => setSelectedCategory((current) => current === category ? null : category)}
                      >
                        {label} {categoryCount(preview, category)}
                      </button>
                    </span>
                  ))}
                </p>
              </div>
              <button className="icon-button icon-button--plain" type="button" aria-label="사용 컨텍스트 닫기" onClick={() => setOpen(false)}>×</button>
            </header>
            {visibleItems.length ? (
              <ul className="context-item-list">
                {visibleItems.map((item) => {
                  const isExpanded = expanded.has(item.resource_identity);
                  return (
                    <li key={item.resource_identity} className={canExclude ? undefined : "context-item-without-adjustment"}>
                      {canExclude ? (
                        <input
                          aria-label={`${item.title} 제외 선택`}
                          type="checkbox"
                          checked={selected.has(item.resource_identity)}
                          onChange={(event) => setSelected((current) => {
                            const next = new Set(current);
                            if (event.target.checked) next.add(item.resource_identity);
                            else next.delete(item.resource_identity);
                            return next;
                          })}
                        />
                      ) : null}
                      <button
                        className="context-item-toggle"
                        type="button"
                        aria-expanded={isExpanded}
                        aria-label={`${item.title} 내용 ${isExpanded ? "접기" : "펼치기"}`}
                        onClick={() => setExpanded((current) => toggledSet(current, item.resource_identity))}
                      >
                        <strong>{item.title}</strong>
                        <span className={isExpanded ? "context-item-content" : "context-item-preview"}>
                          {isExpanded ? item.content : item.preview}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="muted">
                {selectedCategory === null
                  ? "현재 사용 중인 컨텍스트가 없습니다."
                  : `${categoryLabel(selectedCategory)} 컨텍스트가 없습니다.`}
              </p>
            )}
            {canExclude ? (
              <button
                className="button-secondary"
                type="button"
                disabled={busy || selected.size === 0}
                onClick={() => void onAdjust(
                  "EXCLUDE_EVIDENCE",
                  [...new Set(
                    preview.items
                      .filter((item) => selected.has(item.resource_identity))
                      .flatMap((item) => item.segment_ids),
                  )],
                )}
              >
                선택한 근거 제외
              </button>
            ) : null}
            {canRetrieveMore ? (
              <div className="context-retrieve-more">
                <label>추가로 필요한 정보<input value={requestedInformation} onChange={(event) => setRequestedInformation(event.target.value)} maxLength={2048} /></label>
                <button
                  className="button-secondary"
                  type="button"
                  disabled={busy || !requestedInformation.trim()}
                  onClick={() => void onAdjust("RETRIEVE_MORE", requestedInformation.trim())}
                >
                  추가 자료 찾기
                </button>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}
    </div>
  );
}

type ContextCategory = ContextPreview["items"][number]["category"];

const CONTEXT_CATEGORIES: ReadonlyArray<{ category: ContextCategory; label: string }> = [
  { category: "mail", label: "메일" },
  { category: "task", label: "태스크" },
  { category: "calendar", label: "일정" },
  { category: "github", label: "GitHub" },
];

function categoryCount(preview: ContextPreview, category: ContextCategory): number {
  return {
    mail: preview.gmail_count,
    task: preview.tasks_count,
    calendar: preview.calendar_count,
    github: preview.github_count ?? 0,
  }[category];
}

function categoryLabel(category: ContextCategory): string {
  return CONTEXT_CATEGORIES.find((item) => item.category === category)?.label ?? category;
}

function toggledSet(current: Set<string>, value: string): Set<string> {
  const next = new Set(current);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}
