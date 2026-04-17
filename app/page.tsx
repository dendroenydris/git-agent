'use client';

import { useCallback, useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import TopBar from './components/TopBar';
import LeftSidebar from './components/LeftSidebar';
import SettingsModal from './components/SettingsModal';
import TaskWorkflow from './components/TaskWorkflow';
import RightSidebar from './components/RightSidebar';
import { useConsoleState } from './hooks/useConsoleState';
import { useWebSocket } from './hooks/useWebSocket';
import {
  ApprovalMode,
  Task,
  TaskEvent,
  approveTask,
  createDialog,
  getAppSettings,
  getDialogs,
  getTasks,
  healthCheck,
  replanTask,
  submitChat,
  updateAppSettings,
} from './lib/api';

const applyStepOutputEvent = (tasks: Task[] | undefined, event: TaskEvent): Task[] | undefined => {
  if (!tasks || event.type !== 'step_output' || !event.task_id) return tasks;

  const stepId = typeof event.payload.step_id === 'string' ? event.payload.step_id : null;
  const stepPosition =
    typeof event.payload.step_position === 'number' ? event.payload.step_position : null;
  const stream = event.payload.stream === 'stderr' ? 'stderr' : 'stdout';
  const chunk = typeof event.payload.chunk === 'string' ? event.payload.chunk : '';
  if (!chunk || (!stepId && stepPosition === null)) return tasks;

  return tasks.map((task) => {
    if (task.id !== event.task_id) return task;

    return {
      ...task,
      status: task.status === 'queued' ? 'running' : task.status,
      steps: task.steps.map((step) => {
        const matchesStep =
          (stepId !== null && step.id === stepId) ||
          (stepPosition !== null && step.position === stepPosition);
        if (!matchesStep) return step;

        if (stream === 'stderr') {
          return {
            ...step,
            status: step.status === 'pending' ? 'running' : step.status,
            error: `${step.error ?? ''}${chunk}`,
          };
        }

        return {
          ...step,
          status: step.status === 'pending' ? 'running' : step.status,
          output: `${step.output ?? ''}${chunk}`,
        };
      }),
    };
  });
};

export default function Home() {
  const [isLeftSidebarOpen, setIsLeftSidebarOpen] = useState(true);
  const [isRightSidebarOpen, setIsRightSidebarOpen] = useState(true);
  const [isTerminalOpen, setIsTerminalOpen] = useState(true);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
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

  const {
    isConnected: wsConnected,
    lastMessage,
    connectionError,
    reconnect,
  } = useWebSocket(currentDialogId);

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

    if (lastMessage.type === 'task_created' || lastMessage.type === 'task_updated' || lastMessage.type === 'approval_required') {
      refreshCurrentTasks();
    }

    if (lastMessage.type === 'message_added') {
      refreshDialogs();
    }
  }, [currentDialogId, lastMessage, queryClient, refreshCurrentTasks, refreshDialogs]);

  const handleSendMessage = async (message: string) => {
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

  const repoName = currentDialog?.repo
    ? `${currentDialog.repo.owner}/${currentDialog.repo.name}`
    : `${currentRepo.owner}/${currentRepo.name}`;

  return (
    <main className="min-h-screen bg-mac-gray">
      <TopBar
        onToggleLeftSidebar={() => setIsLeftSidebarOpen(!isLeftSidebarOpen)}
        onToggleRightSidebar={() => setIsRightSidebarOpen(!isRightSidebarOpen)}
        onToggleTerminal={() => setIsTerminalOpen(!isTerminalOpen)}
        onToggleSettings={() => setIsSettingsOpen(true)}
        isLeftSidebarOpen={isLeftSidebarOpen}
        isRightSidebarOpen={isRightSidebarOpen}
        isTerminalOpen={isTerminalOpen}
        backendConnected={isBackendConnected}
        wsConnected={wsConnected}
        approvalMode={appSettingsQuery.data?.approval_mode || 'no'}
      />

      <div className="pt-12 flex">
        <LeftSidebar
          isOpen={isLeftSidebarOpen}
          currentBranch={currentRepo.branch || 'main'}
          repoName={repoName}
          tasks={tasks}
          onTaskSelect={selectTask}
          selectedTaskId={selectedTaskId}
          onRepoChange={queueRepoDialog}
          isConnected={isBackendConnected}
        />

        <div
          className={`flex-1 transition-all ${isLeftSidebarOpen ? 'ml-64' : ''} ${isRightSidebarOpen ? 'mr-80' : ''}`}
        >
          <TaskWorkflow
            task={currentTask}
            isConnected={wsConnected}
            connectionError={connectionError}
            onReconnect={reconnect}
            onApprove={handleApproval}
            isApproving={approvalMutation.isPending}
            onReplan={handleReplanTask}
            isReplanning={replanTaskMutation.isPending}
          />
        </div>

        <RightSidebar
          isOpen={isRightSidebarOpen}
          dialogs={dialogs}
          currentDialogId={currentDialogId}
          onSendMessage={handleSendMessage}
          onNewDialog={createAnotherDialog}
          onSelectDialog={selectDialog}
          isConnected={wsConnected && !sendMessageMutation.isPending}
          currentRepo={currentRepo}
        />
      </div>

      <SettingsModal
        isOpen={isSettingsOpen}
        approvalMode={appSettingsQuery.data?.approval_mode || 'no'}
        isSaving={updateSettingsMutation.isPending}
        onClose={() => setIsSettingsOpen(false)}
        onChangeApprovalMode={(mode) => updateSettingsMutation.mutate(mode)}
      />
    </main>
  );
}