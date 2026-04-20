import { useCallback, useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useConsoleState } from './useConsoleState';
import { useWebSocket } from './useWebSocket';
import { applyStepOutputEvent } from '../lib/task-events';
import {
  type ApprovalMode,
  type Task,
  approveTask,
  createDialog,
  getAppSettings,
  getDialogs,
  getTasks,
  healthCheck,
  replanTask,
  submitChat,
  updateAppSettings,
} from '../lib/api';


export function useHomeController() {
  const [currentDialogId, setCurrentDialogId] = useState('');
  const queryClient = useQueryClient();

  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: healthCheck,
    refetchInterval: 15000,
  });

  const isBackendConnected = Boolean(healthQuery.data && healthQuery.data.status !== 'unhealthy');

  const dialogsQuery = useQuery({
    queryKey: ['dialogs'],
    queryFn: getDialogs,
    enabled: isBackendConnected,
  });

  const appSettingsQuery = useQuery({
    queryKey: ['app-settings'],
    queryFn: getAppSettings,
    enabled: isBackendConnected,
  });

  const { isConnected: wsConnected, lastMessage, connectionError, reconnect } = useWebSocket(currentDialogId);

  const tasksQuery = useQuery({
    queryKey: ['tasks', currentDialogId],
    queryFn: () => getTasks(currentDialogId),
    enabled: Boolean(currentDialogId),
    refetchInterval: wsConnected ? false : 5000,
  });

  const dialogs = dialogsQuery.data || [];
  const tasks = tasksQuery.data || [];

  const refreshDialogs = useCallback(() => {
    return queryClient.invalidateQueries({ queryKey: ['dialogs'] });
  }, [queryClient]);

  const refreshCurrentTasks = useCallback(() => {
    return queryClient.invalidateQueries({ queryKey: ['tasks', currentDialogId] });
  }, [currentDialogId, queryClient]);

  const createDialogMutation = useMutation({
    mutationFn: createDialog,
    onSuccess: (dialog) => {
      setCurrentDialogId(dialog.id);
      refreshDialogs();
    },
  });

  const {
    currentDialog,
    currentRepo,
    currentTask,
    selectedTaskId,
    selectTask,
    selectDialog,
    queueRepoDialog,
    createAnotherDialog,
    applyChatResult,
  } = useConsoleState({
    currentDialogId,
    setCurrentDialogId,
    dialogs,
    tasks,
    dialogsLoaded: dialogsQuery.isSuccess,
    isCreatingDialog: createDialogMutation.isPending,
    lastMessage,
    createDialog: (repo) => createDialogMutation.mutate(repo),
  });

  const sendMessageMutation = useMutation({
    mutationFn: ({ dialogId, message }: { dialogId: string; message: string }) =>
      submitChat(dialogId, message),
    onSuccess: (result) => {
      applyChatResult(result);
      if (result.mode === 'task') refreshCurrentTasks();
      refreshDialogs();
    },
  });

  const approvalMutation = useMutation({
    mutationFn: ({ taskId, approved }: { taskId: string; approved: boolean }) =>
      approveTask(taskId, approved),
    onSuccess: () => {
      refreshCurrentTasks();
    },
  });

  const updateSettingsMutation = useMutation({
    mutationFn: (approvalMode: ApprovalMode) => updateAppSettings(approvalMode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['app-settings'] });
    },
  });

  const replanTaskMutation = useMutation({
    mutationFn: ({ taskId, failureMessage }: { taskId: string; failureMessage: string }) =>
      replanTask(taskId, failureMessage),
    onSuccess: () => {
      refreshCurrentTasks();
      refreshDialogs();
    },
  });

  useEffect(() => {
    if (!lastMessage) return;

    if (lastMessage.type === 'step_output') {
      queryClient.setQueryData<Task[] | undefined>(['tasks', currentDialogId], (currentTasks) =>
        applyStepOutputEvent(currentTasks, lastMessage)
      );
      return;
    }

    if (
      lastMessage.type === 'task_created' ||
      lastMessage.type === 'task_updated' ||
      lastMessage.type === 'approval_required'
    ) {
      refreshCurrentTasks();
    }

    if (lastMessage.type === 'message_added') {
      refreshDialogs();
    }
  }, [currentDialogId, lastMessage, queryClient, refreshCurrentTasks, refreshDialogs]);

  const handleSendMessage = (message: string) => {
    if (!currentDialogId) return;
    sendMessageMutation.mutate({ dialogId: currentDialogId, message });
  };

  const handleApproval = (approved: boolean) => {
    if (!currentTask) return;
    approvalMutation.mutate({ taskId: currentTask.id, approved });
  };

  const handleReplanTask = (failureMessage: string) => {
    if (!currentTask) return;
    replanTaskMutation.mutate({ taskId: currentTask.id, failureMessage });
  };

  return {
    currentDialogId,
    dialogs,
    tasks,
    currentDialog,
    currentRepo,
    currentTask,
    selectedTaskId,
    isBackendConnected,
    wsConnected,
    connectionError,
    reconnect,
    approvalMode: appSettingsQuery.data?.approval_mode || 'no',
    isCreatingDialog: createDialogMutation.isPending,
    isSendingMessage: sendMessageMutation.isPending,
    isApproving: approvalMutation.isPending,
    isReplanning: replanTaskMutation.isPending,
    isSavingSettings: updateSettingsMutation.isPending,
    selectTask,
    selectDialog,
    queueRepoDialog,
    createAnotherDialog,
    handleSendMessage,
    handleApproval,
    handleReplanTask,
    updateApprovalMode: (mode: ApprovalMode) => updateSettingsMutation.mutate(mode),
  };
}
