'use client';

import { useState } from 'react';

import TopBar from './components/TopBar';
import LeftSidebar from './components/LeftSidebar';
import SettingsModal from './components/SettingsModal';
import TaskWorkflow from './components/TaskWorkflow';
import RightSidebar from './components/RightSidebar';
import { useHomeController } from './hooks/useHomeController';

export default function Home() {
  const [isLeftSidebarOpen, setIsLeftSidebarOpen] = useState(true);
  const [isRightSidebarOpen, setIsRightSidebarOpen] = useState(true);
  const [isTerminalOpen, setIsTerminalOpen] = useState(true);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const {
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
    approvalMode,
    isSendingMessage,
    isApproving,
    isReplanning,
    isSavingSettings,
    selectTask,
    selectDialog,
    queueRepoDialog,
    createAnotherDialog,
    handleSendMessage,
    handleApproval,
    handleReplanTask,
    updateApprovalMode,
  } = useHomeController();

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
        approvalMode={approvalMode}
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
        />

        <div
          className={`flex-1 transition-all ${isLeftSidebarOpen ? 'ml-64' : ''} ${isRightSidebarOpen ? 'mr-80' : ''}`}
        >
          <TaskWorkflow
            task={currentTask}
            isConnected={wsConnected}
            isTerminalOpen={isTerminalOpen}
            connectionError={connectionError}
            onReconnect={reconnect}
            onApprove={handleApproval}
            isApproving={isApproving}
            onReplan={handleReplanTask}
            isReplanning={isReplanning}
          />
        </div>

        <RightSidebar
          isOpen={isRightSidebarOpen}
          dialogs={dialogs}
          currentDialogId={currentDialogId}
          onSendMessage={handleSendMessage}
          onNewDialog={createAnotherDialog}
          onSelectDialog={selectDialog}
          isConnected={wsConnected && !isSendingMessage}
        />
      </div>

      <SettingsModal
        isOpen={isSettingsOpen}
        approvalMode={approvalMode}
        isSaving={isSavingSettings}
        onClose={() => setIsSettingsOpen(false)}
        onChangeApprovalMode={updateApprovalMode}
      />
    </main>
  );
}