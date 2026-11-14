import React from 'react';
import { Scale, RefreshCw, PlayCircle } from 'lucide-react';

interface HeaderProps {
  onNewChat: () => void;
  onOpenScenarios: () => void;
  activeTab: 'chat' | 'docs';
  setActiveTab: (tab: 'chat' | 'docs') => void;
}

export const Header: React.FC<HeaderProps> = ({
  onNewChat,
  onOpenScenarios,
  activeTab,
  setActiveTab
}) => {
  return (
    <header className="bg-slate-900 text-white border-b border-slate-800 px-4 py-2.5 shrink-0 shadow-xs">
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
        
        {/* Бренд */}
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-blue-700 to-indigo-600 flex items-center justify-center shadow-md">
            <Scale className="h-5 w-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-base tracking-tight text-white">ПСБ</span>
              <span className="text-slate-500 font-light">|</span>
              <span className="font-medium text-slate-200 text-sm">Юридический ассистент</span>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400" />
              <span>База знаний</span>
            </div>
          </div>
        </div>

        {/* Навигационные табы на мобильных экранах */}
        <div className="flex lg:hidden bg-slate-800 p-0.5 rounded-lg border border-slate-700 text-xs">
          <button
            onClick={() => setActiveTab('chat')}
            className={`px-3 py-1.5 rounded-md font-medium transition ${
              activeTab === 'chat' ? 'bg-blue-600 text-white' : 'text-slate-300 hover:text-white'
            }`}
          >
            Чат
          </button>
          <button
            onClick={() => setActiveTab('docs')}
            className={`px-3 py-1.5 rounded-md font-medium transition ${
              activeTab === 'docs' ? 'bg-blue-600 text-white' : 'text-slate-300 hover:text-white'
            }`}
          >
            Документы
          </button>
        </div>

        {/* Действия */}
        <div className="flex items-center gap-2 sm:gap-3">
          
          {/* Сценарии для демо */}
          <button
            onClick={onOpenScenarios}
            className="flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-3 py-1.5 rounded-lg text-xs font-medium transition shadow-xs cursor-pointer"
            title="Примеры сценариев для показа"
          >
            <PlayCircle className="w-3.5 h-3.5 text-blue-400" />
            <span className="hidden sm:inline">Сценарии демо</span>
          </button>

          {/* Новый диалог */}
          <button
            onClick={onNewChat}
            className="flex items-center gap-1.5 bg-blue-700 hover:bg-blue-800 text-white px-3 py-1.5 rounded-lg text-xs font-medium transition shadow-xs cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Новый диалог</span>
          </button>

        </div>
      </div>
    </header>
  );
};
