import { useState, useRef, useEffect } from 'react';
import { FaPaperPlane, FaPlus, FaComment } from 'react-icons/fa';
import ReactMarkdown from 'react-markdown';

import type { Dialog, GitHubRepo } from '../lib/api';

interface RightSidebarProps {
  isOpen: boolean;
  dialogs: Dialog[];
  currentDialogId: string;
  onSendMessage: (message: string) => void;
  onNewDialog: () => void;
  onSelectDialog: (dialogId: string) => void;
  isConnected?: boolean;
  currentRepo?: GitHubRepo;
}

export default function RightSidebar({
  isOpen,
  dialogs,
  currentDialogId,
  onSendMessage,
  onNewDialog,
  onSelectDialog,
  isConnected = false,
  currentRepo,
}: RightSidebarProps) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [isDialogListOpen, setIsDialogListOpen] = useState(false);

  const currentDialog = dialogs.find(d => d.id === currentDialogId);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [currentDialog?.messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim()) {
      onSendMessage(input.trim());
      setInput('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="w-80 bg-white border-l border-mac-border h-[calc(100vh-3rem)] mt-12 fixed right-0 top-0 flex flex-col">
      <div className="border-b border-mac-border p-4 flex items-center justify-between">
        <button
          onClick={() => setIsDialogListOpen(!isDialogListOpen)}
          className="flex items-center gap-2 text-sm font-medium text-gray-700 hover:text-gray-900"
        >
          <FaComment className="w-4 h-4" />
          {currentDialog?.title || 'New Dialog'}
        </button>
        <button
          onClick={onNewDialog}
          className="mac-button w-8 h-8 flex items-center justify-center"
          title="New Dialog"
        >
          <FaPlus className="w-3 h-3" />
        </button>
      </div>

      {isDialogListOpen && (
        <div className="absolute top-16 left-0 right-0 bg-white border-b border-mac-border max-h-64 overflow-y-auto z-10">
          {dialogs.map((dialog) => (
            <button
              key={dialog.id}
              onClick={() => {
                onSelectDialog(dialog.id);
                setIsDialogListOpen(false);
              }}
              className={`w-full text-left p-3 hover:bg-gray-50 transition-colors
                ${dialog.id === currentDialogId ? 'bg-mac-gray' : ''}`}
            >
              <div className="text-sm font-medium text-gray-800 truncate">
                {dialog.title}
              </div>
              <div className="text-xs text-gray-500">{new Date(dialog.created_at).toLocaleString()}</div>
            </button>
          ))}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4">
        {currentDialog?.messages.map((message) => (
          <div
            key={message.id}
            className={message.type === 'user' ? 'user-bubble' : 'agent-bubble'}
          >
            <div className="text-sm whitespace-pre-wrap break-words">
              <ReactMarkdown>{message.content}</ReactMarkdown>
            </div>
            {message.type === 'agent' && message.summary && (
              <div className="text-xs bg-white/50 mt-2 p-2 rounded">
                <span className="font-medium">Summary:</span> {message.summary}
                {message.task_id && (
                  <span className="ml-2 text-mac-hover">Task #{message.task_id}</span>
                )}
              </div>
            )}
            <div className="text-xs opacity-70 mt-1">{new Date(message.created_at).toLocaleString()}</div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="border-t border-mac-border p-4">
        <form onSubmit={handleSubmit} className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your message..."
            className="flex-1 resize-none rounded-lg border border-mac-border p-3 focus:outline-none focus:ring-2 focus:ring-mac-hover focus:ring-opacity-50 text-sm min-h-[80px]"
            rows={3}
          />
          <button
            type="submit"
            disabled={!input.trim()}
            className="mac-button h-10 w-10 flex items-center justify-center disabled:opacity-50"
          >
            <FaPaperPlane className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
} 