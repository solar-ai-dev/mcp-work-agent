import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiClientError } from "../api/client";
import { ConversationHistoryPanel, useConversation } from "../features/conversation";
import { ResourceSidebar, ResourceViewer, type ResourceBrowserProjection } from "../features/resource_browser";
import { getRuntime, type RuntimeSummary } from "../features/diagnostics";
import {
  SettingsDrawer,
  getCurrentGoogleAccount,
  getGoogleConnection,
  getGitHubConnection,
  getSettings,
  updateSettings,
  type CurrentGoogleAccount,
  type GoogleConnection,
  type GitHubConnection,
  type SettingsView,
} from "../features/settings";
import { CenterWorkspace } from "./center_workspace";
import { MainShell } from "./main_shell";
import { StartupFlow, type StartupFlowContext } from "./startup_flow";

export function App(): JSX.Element {
  return <StartupFlow>{(context) => <AuthenticatedWorkspace initial={context} />}</StartupFlow>;
}
function AuthenticatedWorkspace({ initial }: { initial: StartupFlowContext }): JSX.Element {
  const [settings, setSettings] = useState<SettingsView>(initial.settings);
  const [theme, setTheme] = useState(initial.settings.theme === "DARK" ? "dark" : "light");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [runtime, setRuntime] = useState<RuntimeSummary>(initial.runtime);
  const [google, setGoogle] = useState<GoogleConnection>(initial.google);
  const [github, setGitHub] = useState<GitHubConnection | null>(initial.github);
  const [currentAccount, setCurrentAccount] = useState<CurrentGoogleAccount["account"]>(initial.currentAccount);
  const [calendarTimezone, setCalendarTimezone] = useState(initial.calendarTimezone);
  const [statusLine, setStatusLine] = useState("로컬 API에 연결되어 있습니다.");
  const [workspaceReady, setWorkspaceReady] = useState(false);
  const [resourceProjection, setResourceProjection] = useState<ResourceBrowserProjection>({
    activeSource: null,
    focusedItem: null,
    selectedContext: { items: [], resourceIds: [], selectionHandles: [], labels: [] },
    composerPrompt: "선택한 메일에 대해 질문하거나 업무를 요청하세요...",
    emptyMessage: "자료를 불러오는 중입니다.",
    focusedItemSelected: false,
    toggleFocusedSelection: () => undefined,
    openFocusedContainer: () => undefined,
  });
  const conversation = useConversation({
    selectedResourceHandles: resourceProjection.selectedContext.selectionHandles,
    onStatusLine: setStatusLine,
    requestedMode: runtime.runtime_mode.requested_mode,
  });
  const {
    conversations,
    selectedConversationId,
    historyMessages,
    runSnapshot,
    runSnapshots,
    runContext,
    composerText,
    composerError,
    busyCommand,
    pendingConfirmation,
    confirmationText,
    setComposerText,
    setComposerError,
    setConfirmationText,
    refreshConversations,
    beginConversationProjection,
    selectConversation,
    selectRun,
    handleStartRun,
    handleApprove,
    handleSimpleAction,
    handleAttachDescriptors,
    handleCancelRun,
    handleResumeRun,
    handleResumeAfterReauth,
    handleAdjustContext,
    handleConfirmation,
    handleResolveRecovery,
  } = conversation;
  const restoredOpenRunRef = useRef(false);
  const reauthResumeAttemptRef = useRef<string | null>(null);
  const operationalCommandIds = useRef(new Map<string, string>());
  const githubRepositories = useMemo(
    () => settings.selected_github_repositories
      ?.filter((item) => item.account_id === github?.account_id)
      .map((item) => item.repository) ?? [],
    [github?.account_id, settings.selected_github_repositories],
  );

  useEffect(() => {
    if (restoredOpenRunRef.current) {
      return;
    }
    restoredOpenRunRef.current = true;
    void refreshConversations().then(async (items) => {
      const openConversation = items.find((item) => item.open_run_id !== null);
      if (openConversation?.open_run_id) {
        await selectRun(openConversation.open_run_id);
      }
    }).catch((error: unknown) => {
      setStatusLine(error instanceof ApiClientError ? error.message : "이전 작업을 복구하지 못했습니다.");
    }).finally(() => setWorkspaceReady(true));
  }, [currentAccount, refreshConversations, selectRun]);

  const conversationViewModel = {
    controller: {
      selectedConversationId,
      historyMessages,
      runSnapshot,
      runSnapshots,
      runContext,
      pendingConfirmation,
      confirmationText,
      setConfirmationText,
      composerText,
      composerError,
      setComposerText,
      setComposerError,
      busyCommand,
      handleStartRun,
      handleApprove,
      handleSimpleAction,
      handleAttachDescriptors,
      handleCancelRun,
      handleResumeRun,
      handleAdjustContext,
      handleConfirmation,
      handleResolveRecovery,
    },
    resourceContext: {
      selectedResourceIds: resourceProjection.selectedContext.resourceIds,
      selectedResourceLabels: resourceProjection.selectedContext.labels,
      composerPrompt: resourceProjection.composerPrompt,
    },
    formatTime,
    onOpenSettings: () => setSettingsOpen(true),
    onOpenDiagnostics: () => setStatusLine("설정의 Runtime 상태에서 진단 정보를 확인하세요."),
  };
  const refreshRuntimeSummary = useCallback(async (): Promise<void> => {
    const [runtimeResponse, googleResponse, githubResponse, accountResponse, settingsResponse] = await Promise.all([
      getRuntime(),
      getGoogleConnection(),
      getGitHubConnection().catch(() => null),
      getCurrentGoogleAccount(),
      getSettings(),
    ]);
    setRuntime(runtimeResponse);
    setGoogle(googleResponse);
    setGitHub(githubResponse);
    setCurrentAccount(accountResponse.account);
    setSettings(settingsResponse);
    setTheme(settingsResponse.theme === "DARK" ? "dark" : "light");
    setCalendarTimezone(settingsResponse.timezone);
  }, []);

  useEffect(() => {
    if (runSnapshot?.run.status !== "REAUTH_REQUIRED") {
      reauthResumeAttemptRef.current = null;
      return;
    }
    const identity = `${runSnapshot.run.run_id}:${runSnapshot.run.version}`;
    if (reauthResumeAttemptRef.current === identity) return;
    const reauthAction = runSnapshot.error?.actions.find((action) =>
      action.kind === "REAUTHENTICATE_CONNECTOR" || action.kind === "REAUTHENTICATE_GOOGLE"
    );
    const connectorId = reauthAction?.kind === "REAUTHENTICATE_CONNECTOR"
      ? reauthAction.connector_id
      : "google_workspace";
    const resumeAfterFreshConnection = (): void => {
      if (reauthResumeAttemptRef.current === identity) return;
      reauthResumeAttemptRef.current = identity;
      void handleResumeAfterReauth().catch((error: unknown) => {
        setStatusLine(error instanceof ApiClientError ? error.message : "재인증 후 작업을 재개하지 못했습니다.");
      });
    };
    let cancelled = false;
    let timer: number | undefined;
    const checkConnection = (): void => {
      const readConnection = connectorId === "github" ? getGitHubConnection : getGoogleConnection;
      void readConnection().then((freshConnection) => {
        if (cancelled) return;
        if (connectorId === "github") setGitHub(freshConnection);
        else setGoogle(freshConnection);
        if (freshConnection.connection_status === "CONNECTED") {
          resumeAfterFreshConnection();
          return;
        }
        timer = window.setTimeout(checkConnection, 2_000);
      }).catch((error: unknown) => {
        if (cancelled) return;
        const fallback = connectorId === "github"
          ? "GitHub 재인증 상태를 확인하지 못했습니다."
          : "Google 재인증 상태를 확인하지 못했습니다.";
        setStatusLine(error instanceof ApiClientError ? error.message : fallback);
        timer = window.setTimeout(checkConnection, 2_000);
      });
    };
    checkConnection();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [handleResumeAfterReauth, runSnapshot]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  async function handleThemeChange(nextTheme: string): Promise<void> {
    const persistedTheme = nextTheme === "dark" ? "DARK" : "LIGHT";
    setTheme(nextTheme === "dark" ? "dark" : "light");
    try {
      const updated = await updateSettings(
        commandIdFor(`settings:theme:${persistedTheme}`),
        { theme: persistedTheme },
      );
      operationalCommandIds.current.delete(`settings:theme:${persistedTheme}`);
      setSettings(updated);
      setTheme(updated.theme === "DARK" ? "dark" : "light");
    } catch (error) {
      setTheme(settings.theme === "DARK" ? "dark" : "light");
      setStatusLine(error instanceof ApiClientError ? error.message : "테마 설정을 저장하지 못했습니다.");
    }
  }

  async function handleConversationPanelOpenChange(isOpen: boolean): Promise<void> {
    const operation = `settings:conversation-panel:${isOpen ? "open" : "closed"}`;
    try {
      const updated = await updateSettings(commandIdFor(operation), {
        panel_preferences: {
          ...settings.panel_preferences,
          right_panel_default_open: isOpen,
        },
      });
      operationalCommandIds.current.delete(operation);
      setSettings(updated);
    } catch (error) {
      setStatusLine(error instanceof ApiClientError ? error.message : "패널 설정을 저장하지 못했습니다.");
    }
  }

  function commandIdFor(operation: string): string {
    let commandId = operationalCommandIds.current.get(operation);
    if (!commandId) {
      commandId = crypto.randomUUID();
      operationalCommandIds.current.set(operation, commandId);
    }
    return commandId;
  }

  if (!workspaceReady) {
    return <main className="startup" aria-busy="true" aria-label="이전 작업 복구 중" />;
  }

  return (
    <MainShell
      statusLine={statusLine}
      theme={theme}
      onThemeChange={(nextTheme) => void handleThemeChange(nextTheme)}
      conversationPanelDefaultOpen={settings.panel_preferences.right_panel_default_open}
      onConversationPanelOpenChange={(isOpen) => void handleConversationPanelOpenChange(isOpen)}
      onShowHelp={() => setStatusLine("자료를 선택하거나 자연어 요청을 입력해 업무를 시작할 수 있습니다.")}
      onOpenSettings={() => setSettingsOpen(true)}
      settingsPanel={settingsOpen ? (
        <SettingsDrawer
          runtime={runtime}
          theme={theme}
          onThemeChange={(nextTheme) => void handleThemeChange(nextTheme)}
          onClose={() => setSettingsOpen(false)}
          onOperationalStateChanged={refreshRuntimeSummary}
        />
      ) : null}
    >
        <ResourceSidebar
          scopeKey={`${runtime.service_instance_id}|google:${currentAccount?.account_id ?? "disconnected"}|google-selection:${JSON.stringify([settings.selected_calendar_ids, settings.selected_tasklist_ids, settings.google_resource_account_id])}|github:${github?.account_id ?? "disconnected"}|repositories:${JSON.stringify(githubRepositories)}`}
          googleAccountId={currentAccount?.account_id}
          githubAccountId={github?.account_id}
          googleConnected={google.connection_status === "CONNECTED" && google.missing_required_scopes.length === 0}
          githubConnected={github?.connection_status === "CONNECTED" && github.missing_required_scopes.length === 0}
          githubRepositories={githubRepositories}
          onOpenSettings={() => setSettingsOpen(true)}
          timezone={calendarTimezone}
          onProjectionChange={setResourceProjection}
        />

        <CenterWorkspace
          resourceViewer={<ResourceViewer projection={resourceProjection} />}
          conversationViewModel={conversationViewModel}
        />

        <ConversationHistoryPanel
          conversations={conversations}
          selectedConversationId={selectedConversationId}
          hasRunSnapshot={runSnapshot !== null}
          onBeginConversation={() => beginConversationProjection(null)}
          onSelectConversation={(conversationId) => void selectConversation(conversationId)}
        />
    </MainShell>
  );
}

function formatTime(value: number): string {
  return new Date(value).toLocaleString("ko-KR", { hour12: false });
}
