import { FaCheckCircle, FaClock, FaExclamationTriangle, FaSpinner, FaTimesCircle } from 'react-icons/fa';

import type { StepStatus, TaskStatus } from './api';

type WorkflowStatus = TaskStatus | StepStatus;

export function getWorkflowStatusIcon(status: WorkflowStatus) {
  switch (status) {
    case 'completed':
      return <FaCheckCircle className="h-4 w-4 text-green-500" />;
    case 'running':
      return <FaSpinner className="h-4 w-4 animate-spin text-blue-500" />;
    case 'waiting_for_human':
      return <FaExclamationTriangle className="h-4 w-4 text-amber-500" />;
    case 'failed':
    case 'cancelled':
      return <FaTimesCircle className="h-4 w-4 text-red-500" />;
    case 'queued':
      return <FaClock className="h-4 w-4 text-gray-400" />;
    case 'pending':
    default:
      return <div className="h-4 w-4 rounded-full border-2 border-gray-300" />;
  }
}

export function getTaskStatusBadgeClass(status: TaskStatus) {
  switch (status) {
    case 'completed':
      return 'bg-green-50 text-green-700 border-green-200';
    case 'running':
      return 'bg-blue-50 text-blue-700 border-blue-200';
    case 'waiting_for_human':
      return 'bg-amber-50 text-amber-700 border-amber-200';
    case 'failed':
    case 'cancelled':
      return 'bg-red-50 text-red-700 border-red-200';
    case 'queued':
    default:
      return 'bg-gray-50 text-gray-700 border-gray-200';
  }
}

export function formatWorkflowStatus(status: WorkflowStatus) {
  return status.replaceAll('_', ' ');
}
