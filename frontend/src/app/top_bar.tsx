type Props = {
  statusLine: string;
  onOpenSettings: () => void;
  onShowHelp: () => void;
  onToggleResourcePanel: () => void;
  onToggleConversationPanel: () => void;
  resourcePanelOpen: boolean;
  conversationPanelOpen: boolean;
  theme: string;
  onThemeChange: (theme: string) => void;
};

export function TopBar({
  statusLine,
  onOpenSettings,
  onShowHelp,
  onToggleResourcePanel,
  onToggleConversationPanel,
  resourcePanelOpen,
  conversationPanelOpen,
  theme,
  onThemeChange,
}: Props): JSX.Element {
  return (
    <header className="topbar">
      <div className="topbar-brand">
        <button
          className="icon-button topbar-icon-button"
          type="button"
          aria-label="자료 패널 전환"
          aria-pressed={resourcePanelOpen}
          onClick={onToggleResourcePanel}
        >
          ☰
        </button>
        <span className="brand-mark" aria-hidden="true">m</span>
        <strong>mcp-work-agent</strong>
        <span className="sr-only" aria-live="polite">{statusLine}</span>
      </div>
      <div className="topbar-actions">
        <button className="icon-button topbar-icon-button" type="button" aria-label="도움말" title="도움말" onClick={onShowHelp}>?</button>
        <button
          className="icon-button topbar-icon-button"
          type="button"
          aria-label="테마 전환"
          onClick={() => onThemeChange(theme === "dark" ? "light" : "dark")}
        >
          {theme === "dark" ? "☀" : "☾"}
        </button>
        <button
          className="icon-button topbar-icon-button"
          type="button"
          aria-label="대화 내역 전환"
          aria-pressed={conversationPanelOpen}
          onClick={onToggleConversationPanel}
        >
          ◫
        </button>
        <button className="icon-button topbar-icon-button" type="button" aria-label="설정" title="설정" onClick={onOpenSettings}>⚙</button>
      </div>
    </header>
  );
}
