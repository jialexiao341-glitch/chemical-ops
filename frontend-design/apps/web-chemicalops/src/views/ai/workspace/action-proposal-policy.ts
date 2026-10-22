export interface ActionProposalState {
  confirmation_id: string;
  preview_version: number;
  status: string;
  blockers?: string[];
  requires_user_confirmation?: boolean;
}

export function canConfirmActionProposal(
  proposal: ActionProposalState | undefined,
  currentPreviewVersion: number,
  submitting: boolean,
): boolean {
  return Boolean(
    proposal?.confirmation_id &&
      proposal.status === 'PENDING' &&
      proposal.requires_user_confirmation !== false &&
      proposal.preview_version === currentPreviewVersion &&
      !(proposal.blockers?.length) &&
      !submitting,
  );
}

export function shouldReplaceActionProposal<T extends ActionProposalState>(
  current: T | undefined,
  incoming: T,
): boolean {
  if (!current || current.confirmation_id !== incoming.confirmation_id) return true;
  return incoming.preview_version >= current.preview_version;
}
