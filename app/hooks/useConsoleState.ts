import { useEffect, useMemo, useState } from 'react';

import type { ChatResponse, Dialog, GitHubRepo, Task, TaskEvent } from '../lib/api';

const DEFAULT_DIALOG_REPO: GitHubRepo = {
  // Keep first-run bootstrapping on a public repo until the empty-state flow is redesigned.
  owner: 'octocat',
  name: 'Hello-World',
  branch: 'main',
};

interface UseConsoleStateParams {
  currentDialogId: string;
  setCurrentDialogId: (dialogId: string) => void;
  dialogs: Dialog[];
  tasks: Task[];
  dialogsLoaded: boolean;
  isCreatingDialog: boolean;
  lastMessage: TaskEvent | null;
  createDialog: (repo: GitHubRepo) => void;
}

interface UseConsoleStateResult {
  currentDialog: Dialog | null;
  currentRepo: GitHubRepo;
  currentTask: Task | null;
  selectedTaskId: string;
  selectTask: (taskId: string, dialogId?: string) => void;
  selectDialog: (dialogId: string) => void;
  queueRepoDialog: (repoInput: string) => void;
  createAnotherDialog: () => void;
  applyChatResult: (result: ChatResponse) => void;
}

export function useConsoleState({
  currentDialogId,
  setCurrentDialogId,
  dialogs,
  tasks,
  dialogsLoaded,
  isCreatingDialog,
  lastMessage,
  createDialog,
}: UseConsoleStateParams): UseConsoleStateResult {
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [currentRepo, setCurrentRepo] = useState<GitHubRepo>(DEFAULT_DIALOG_REPO);

  const currentDialog = useMemo(
    () => dialogs.find((dialog) => dialog.id === currentDialogId) || null,
    [currentDialogId, dialogs]
  );

  const currentTask = useMemo(
    () => tasks.find((task) => task.id === selectedTaskId) || tasks[0] || null,
    [selectedTaskId, tasks]
  );

  useEffect(() => {
    if (!dialogs.length || currentDialogId) return;
    setCurrentDialogId(dialogs[0].id);
  }, [currentDialogId, dialogs, setCurrentDialogId]);

  useEffect(() => {
    if (!currentDialog?.repo) return;
    setCurrentRepo(currentDialog.repo);
  }, [currentDialog]);

  useEffect(() => {
    if (!tasks.length) {
      setSelectedTaskId('');
      return;
    }

    if (!selectedTaskId || !tasks.some((task) => task.id === selectedTaskId)) {
      setSelectedTaskId(tasks[0].id);
    }
  }, [selectedTaskId, tasks]);

  useEffect(() => {
    if (lastMessage?.type === 'task_created' && lastMessage.task_id) {
      setSelectedTaskId(lastMessage.task_id);
    }
  }, [lastMessage]);

  useEffect(() => {
    // TODO: drop the auto-bootstrap once the empty dialog screen can carry repo selection on its own.
    if (!dialogsLoaded || dialogs.length > 0 || isCreatingDialog) return;
    createDialog(currentRepo);
  }, [createDialog, currentRepo, dialogs.length, dialogsLoaded, isCreatingDialog]);

  const selectTask = (taskId: string, dialogId?: string) => {
    setSelectedTaskId(taskId);
    if (dialogId && dialogId !== currentDialogId) {
      setCurrentDialogId(dialogId);
    }
  };

  const selectDialog = (dialogId: string) => {
    setCurrentDialogId(dialogId);
    setSelectedTaskId('');
  };

  const queueRepoDialog = (repoInput: string) => {
    const [owner, name] = repoInput.trim().split('/');
    if (!owner || !name) return;

    const nextRepo = { owner, name, branch: 'main' };
    setCurrentRepo(nextRepo);
    createDialog(nextRepo);
  };

  const createAnotherDialog = () => {
    createDialog(currentRepo);
  };

  const applyChatResult = (result: ChatResponse) => {
    if (result.mode === 'task') {
      setSelectedTaskId(result.task_id);
    }
  };

  return {
    currentDialog,
    currentRepo,
    currentTask,
    selectedTaskId,
    selectTask,
    selectDialog,
    queueRepoDialog,
    createAnotherDialog,
    applyChatResult,
  };
}
