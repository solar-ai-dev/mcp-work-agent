import type { ConversationViewModel } from "../features/conversation";
import { ConversationView } from "../features/conversation";

export type CenterWorkspaceProps = {
  conversationViewModel: ConversationViewModel;
};

export function CenterWorkspace({ conversationViewModel }: CenterWorkspaceProps): JSX.Element {
  return (
    <main className="panel center-workspace">
      <ConversationView viewModel={conversationViewModel} />
    </main>
  );
}
