import { FaTerminal, FaCog } from 'react-icons/fa';
import { MdOutlineKeyboardDoubleArrowLeft, MdOutlineKeyboardDoubleArrowRight } from 'react-icons/md';

interface TopBarProps {
  onToggleLeftSidebar: () => void;
  onToggleRightSidebar: () => void;
  onToggleTerminal: () => void;
  onToggleSettings: () => void;
  isLeftSidebarOpen: boolean;
  isRightSidebarOpen: boolean;
  isTerminalOpen: boolean;
  backendConnected?: boolean;
  wsConnected?: boolean;
  approvalMode?: string;
}

export default function TopBar({
  onToggleLeftSidebar,
  onToggleRightSidebar,
  onToggleTerminal,
  onToggleSettings,
  isLeftSidebarOpen,
  isRightSidebarOpen,
  isTerminalOpen,
  backendConnected = false,
  wsConnected = false,
  approvalMode = 'no',
}: TopBarProps) {
  return (
    <div className="h-12 bg-white border-b border-mac-border flex items-center justify-between px-4 fixed top-0 left-0 right-0 z-50">
      <div className="flex items-center space-x-4">
        <h1 className="text-lg font-semibold text-gray-800">AI DevOps Copilot</h1>
        <div className="flex items-center space-x-2 text-sm">
          <div className="flex items-center space-x-1">
            <div className={`w-2 h-2 rounded-full ${backendConnected ? 'bg-green-500' : 'bg-red-500'}`}></div>
            <span className="text-gray-600">Backend</span>
          </div>
          <div className="flex items-center space-x-1">
            <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-green-500' : 'bg-orange-500'}`}></div>
            <span className="text-gray-600">WebSocket</span>
          </div>
          <div className="rounded-full bg-gray-100 px-2 py-1 text-xs text-gray-600">{approvalMode}</div>
        </div>
      </div>
      
      <div className="flex items-center space-x-2">
        <button
          onClick={onToggleLeftSidebar}
          className="mac-button"
          title={isLeftSidebarOpen ? "Collapse Left Sidebar" : "Expand Left Sidebar"}
        >
          {isLeftSidebarOpen ? (
            <MdOutlineKeyboardDoubleArrowLeft className="w-5 h-5" />
          ) : (
            <MdOutlineKeyboardDoubleArrowRight className="w-5 h-5" />
          )}
        </button>

        <button
          onClick={onToggleRightSidebar}
          className="mac-button"
          title={isRightSidebarOpen ? "Collapse Right Sidebar" : "Expand Right Sidebar"}
        >
          {isRightSidebarOpen ? (
            <MdOutlineKeyboardDoubleArrowRight className="w-5 h-5" />
          ) : (
            <MdOutlineKeyboardDoubleArrowLeft className="w-5 h-5" />
          )}
        </button>

        <button
          onClick={onToggleTerminal}
          className="mac-button"
          title={isTerminalOpen ? "Collapse Terminal" : "Expand Terminal"}
        >
          <FaTerminal className="w-4 h-4" />
        </button>

        <button
          onClick={onToggleSettings}
          className="mac-button"
          title="Settings"
        >
          <FaCog className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
} 