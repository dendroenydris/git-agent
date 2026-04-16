import type { ApprovalMode } from '../lib/api';

interface SettingsModalProps {
  isOpen: boolean;
  approvalMode: ApprovalMode;
  isSaving?: boolean;
  onClose: () => void;
  onChangeApprovalMode: (mode: ApprovalMode) => void;
}

const OPTIONS: Array<{
  id: ApprovalMode;
  label: string;
  description: string;
}> = [
  {
    id: 'all-allow',
    label: 'all-allow',
    description: 'Allow all steps to execute automatically without approval.',
  },
  {
    id: 'allow-allowlist',
    label: 'allow-allowlist',
    description: 'Require approval only for GitHub write actions and commands outside the allowlist.',
  },
  {
    id: 'no',
    label: 'no',
    description: 'Require approval for every step.',
  },
];

export default function SettingsModal({
  isOpen,
  approvalMode,
  isSaving = false,
  onClose,
  onChangeApprovalMode,
}: SettingsModalProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-xl rounded-xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-mac-border px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Execution Settings</h2>
            <p className="mt-1 text-sm text-gray-500">Choose how aggressively the agent asks for approval.</p>
          </div>
          <button onClick={onClose} className="mac-button text-sm">
            Close
          </button>
        </div>

        <div className="space-y-3 px-6 py-5">
          {OPTIONS.map((option) => {
            const isSelected = option.id === approvalMode;
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => onChangeApprovalMode(option.id)}
                disabled={isSaving}
                className={`w-full rounded-lg border p-4 text-left transition ${
                  isSelected
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-mac-border bg-white hover:border-gray-300'
                } disabled:cursor-not-allowed disabled:opacity-60`}
              >
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="text-sm font-semibold text-gray-900">{option.label}</div>
                    <div className="mt-1 text-sm text-gray-600">{option.description}</div>
                  </div>
                  <div
                    className={`h-4 w-4 rounded-full border ${
                      isSelected ? 'border-blue-500 bg-blue-500' : 'border-gray-300'
                    }`}
                  />
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
