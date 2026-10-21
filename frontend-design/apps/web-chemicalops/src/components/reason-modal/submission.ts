export function createReasonSubmission() {
  let pending = false;
  return {
    async submit(reason: string, action: (reason: string) => Promise<unknown>) {
      if (pending || !reason.trim()) return false;
      pending = true;
      try { await action(reason.trim()); return true; }
      finally { pending = false; }
    },
  };
}
