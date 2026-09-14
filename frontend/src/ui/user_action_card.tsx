import type { ReactNode } from "react";

export type UserActionTone = "approval" | "confirmation";
export type UserActionGlyphName =
  | "action"
  | "calendar"
  | "confirmation"
  | "github"
  | "mail"
  | "task";

export function UserActionCard({
  tone,
  glyph,
  title,
  description,
  ariaLabel,
  dataToolName,
  children,
  footer,
}: {
  tone: UserActionTone;
  glyph: UserActionGlyphName;
  title: string;
  description?: ReactNode;
  ariaLabel?: string;
  dataToolName?: string;
  children: ReactNode;
  footer?: ReactNode;
}): JSX.Element {
  return (
    <article
      className={`user-action-card user-action-card--${tone}`}
      aria-label={ariaLabel ?? title}
      data-tool-name={dataToolName}
    >
      <header className="user-action-header">
        <UserActionGlyph name={glyph} />
        <div>
          <h3>{title}</h3>
          {description ? <div className="user-action-description">{description}</div> : null}
        </div>
      </header>
      <div className="user-action-content">{children}</div>
      {footer ? <footer className="user-action-footer">{footer}</footer> : null}
    </article>
  );
}

export function UserActionFields({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <dl className="user-action-fields" aria-label={label}>
      {children}
    </dl>
  );
}

export function UserActionField({
  label,
  value,
  multiline = false,
  hideLabel = false,
}: {
  label: string;
  value: ReactNode;
  multiline?: boolean;
  hideLabel?: boolean;
}): JSX.Element {
  return (
    <div className={multiline ? "user-action-field user-action-field--multiline" : "user-action-field"}>
      <dt className={hideLabel ? "sr-only" : undefined}>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function UserActionDisclosure({
  label = "세부 정보",
  children,
  open = false,
}: {
  label?: string;
  children: ReactNode;
  open?: boolean;
}): JSX.Element {
  return (
    <details className="user-action-disclosure" open={open}>
      <summary>{label}</summary>
      <div className="user-action-disclosure-content">{children}</div>
    </details>
  );
}

export function UserActionEditor({
  title = "내용 수정",
  children,
}: {
  title?: string | null;
  children: ReactNode;
}): JSX.Element {
  return (
    <section className="user-action-editor" aria-label={title ?? undefined}>
      {title ? <h4>{title}</h4> : null}
      {children}
    </section>
  );
}

export function UserActionNotice({ children }: { children: ReactNode }): JSX.Element {
  return (
    <div className="user-action-notice" role="note">
      <span className="user-action-notice-icon" aria-hidden="true">!</span>
      <span>{children}</span>
    </div>
  );
}

function UserActionGlyph({ name }: { name: UserActionGlyphName }): JSX.Element {
  const path = {
    action: <path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1m0-12.8-2.1 2.1m-8.6 8.6-2.1 2.1M15.5 12a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0Z" />,
    calendar: <><path d="M6 3v3m12-3v3M4.5 8.5h15" /><rect x="4.5" y="5" width="15" height="15" rx="2.5" /><path d="M8 12h3v3H8z" /></>,
    confirmation: <><circle cx="12" cy="12" r="8.5" /><path d="M9.7 9.5a2.4 2.4 0 0 1 4.6 1c0 1.8-2.3 2-2.3 3.7M12 17.3h.01" /></>,
    github: <><circle cx="12" cy="12" r="8.5" /><path d="M12 8v5m0 3h.01" /></>,
    mail: <><rect x="3.5" y="5.5" width="17" height="13" rx="2.5" /><path d="m5 8 7 5 7-5" /></>,
    task: <><circle cx="12" cy="12" r="8.5" /><path d="m8.2 12 2.4 2.4 5.2-5.2" /></>,
  }[name];
  return (
    <span className="user-action-glyph" aria-hidden="true">
      <svg viewBox="0 0 24 24">{path}</svg>
    </span>
  );
}
