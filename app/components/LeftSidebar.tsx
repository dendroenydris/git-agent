import { useState } from 'react';
import { FaGithub, FaCodeBranch, FaTimes } from 'react-icons/fa';
import { MdEdit } from 'react-icons/md';
import type { Task, TaskStatus } from '../lib/api';
import { formatWorkflowStatus, getTaskStatusBadgeClass, getWorkflowStatusIcon } from '../lib/task-status';

interface LeftSidebarProps {
  isOpen: boolean;
  currentBranch: string;
  repoName: string;
  tasks: Task[];
  selectedTaskId: string;
  onTaskSelect: (taskId: string, dialogId?: string) => void;
  onRepoChange?: (newRepo: string) => void;
  isConnected?: boolean;
}

export default function LeftSidebar({
  isOpen,
  currentBranch,
  repoName,
  tasks,
  selectedTaskId,
  onTaskSelect,
  onRepoChange,
  isConnected = false,
}: LeftSidebarProps) {
  const [isRepoModalOpen, setIsRepoModalOpen] = useState(false);
  const [newRepoName, setNewRepoName] = useState('');

  const handleRepoSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newRepoName.trim() && onRepoChange) {
      onRepoChange(newRepoName.trim());
      setNewRepoName('');
      setIsRepoModalOpen(false);
    }
  };

  return (
    <>
      <div
        className={`fixed top-12 left-0 h-[calc(100vh-3rem)] w-64 bg-white border-r border-mac-border transition-transform duration-300 ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="p-4 border-b border-mac-border">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center space-x-2">
              <FaGithub className="w-5 h-5 text-gray-700" />
              <button
                onClick={() => setIsRepoModalOpen(true)}
                className="text-sm font-medium text-gray-800 hover:text-blue-600 flex items-center space-x-1"
              >
                <span>{repoName}</span>
                <MdEdit className="w-4 h-4" />
              </button>
            </div>
          </div>
          <div className="flex items-center space-x-2 text-sm text-gray-600">
            <FaCodeBranch className="w-4 h-4" />
            <span>{currentBranch}</span>
          </div>
        </div>

        <div className="p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Task History</h2>
          <div className="space-y-2">
            {tasks.map((task) => (
              <button
                key={task.id}
                onClick={() => onTaskSelect(task.id, task.dialog_id)}
                className={`w-full text-left p-3 rounded-lg text-sm transition-colors border ${
                  selectedTaskId === task.id
                    ? 'bg-blue-50 border-blue-200'
                    : 'hover:bg-gray-50 border-transparent'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-gray-900 line-clamp-2">
                    {task.user_message || 'Task'}
                  </span>
                  <span className="text-xs text-gray-500">#{task.id.slice(-6)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <div className={`flex items-center space-x-1.5 px-2 py-1 rounded-full text-xs border ${getTaskStatusBadgeClass(task.status)}`}>
                    {getWorkflowStatusIcon(task.status)}
                    <span className="capitalize">{formatWorkflowStatus(task.status)}</span>
                  </div>
                  <span className="text-xs text-gray-500">{new Date(task.created_at).toLocaleTimeString()}</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {isRepoModalOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-96 p-6">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-semibold text-gray-800">Change Repository</h2>
              <button
                onClick={() => setIsRepoModalOpen(false)}
                className="text-gray-500 hover:text-gray-700"
              >
                <FaTimes className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleRepoSubmit}>
              <div className="mb-4">
                <label htmlFor="repoName" className="block text-sm font-medium text-gray-700 mb-2">
                  GitHub Repository (owner/repo)
                </label>
                <input
                  type="text"
                  id="repoName"
                  value={newRepoName}
                  onChange={(e) => setNewRepoName(e.target.value)}
                  placeholder="e.g., ultralytics/yolov5"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
              <div className="flex justify-end space-x-3">
                <button
                  type="button"
                  onClick={() => setIsRepoModalOpen(false)}
                  className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-gray-500"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  Change
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
} 