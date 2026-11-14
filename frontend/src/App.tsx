import { useState } from 'react';
import { Header } from './components/Header';
import { ChatPanel } from './components/ChatPanel';
import { DocumentViewer } from './components/DocumentViewer';
import { GoldenScenariosModal } from './components/GoldenScenariosModal';
import type { UIHistoryItem, ChatMessage } from './types';
import { sendChatMessage } from './api/client';

export function App() {
  const [history, setHistory] = useState<UIHistoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isScenariosOpen, setIsScenariosOpen] = useState(false);

  // Стейт выбранного документа и целевого фрагмента для подсветки
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [targetFragmentId, setTargetFragmentId] = useState<string | null>(null);

  // Таб на мобильных экранах: 'chat' | 'docs'
  const [activeTab, setActiveTab] = useState<'chat' | 'docs'>('chat');

  const handleNewChat = () => {
    setHistory([]);
    setSelectedDocId(null);
    setTargetFragmentId(null);
  };

  const handleSendMessage = async (userPrompt: string) => {
    const userMsgId = `usr-${Date.now()}`;
    const userItem: UIHistoryItem = {
      id: userMsgId,
      role: 'user',
      content: userPrompt,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setHistory(prev => [...prev, userItem]);
    setIsLoading(true);

    const apiMessages: ChatMessage[] = [
      ...history.map(h => ({ role: h.role, content: h.content })),
      { role: 'user', content: userPrompt }
    ];

    try {
      const response = await sendChatMessage(apiMessages);

      const assistantMsgId = `ast-${Date.now()}`;
      const assistantItem: UIHistoryItem = {
        id: assistantMsgId,
        role: 'assistant',
        content: response.answer,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        responseMeta: {
          status: response.status,
          query_type: response.query_type,
          citations: response.citations || [],
          missing_info: response.missing_info,
          steps: response.steps,
          latency_ms: response.latency_ms
        }
      };

      setHistory(prev => [...prev, assistantItem]);

      if (response.citations && response.citations.length > 0) {
        const firstCit = response.citations[0];
        setSelectedDocId(firstCit.doc_id);
        setTargetFragmentId(firstCit.fragment_id);
      }
    } catch (err: any) {
      console.error('Failed to get answer:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCitationClick = (docId: string, fragmentId: string) => {
    setSelectedDocId(docId);
    setTargetFragmentId(fragmentId);
    setActiveTab('docs');
  };

  const handleSelectQuickPrompt = (prompt: string) => {
    handleSendMessage(prompt);
  };

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-slate-100 font-sans">
      
      {/* Верхняя панель (Header) */}
      <Header
        onNewChat={handleNewChat}
        onOpenScenarios={() => setIsScenariosOpen(true)}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
      />

      {/* Основная двухпанельная область (Split-Screen) */}
      <main className="flex-1 flex overflow-hidden">
        
        {/* Левая панель: Чат (55% на десктопе) */}
        <div className={`h-full flex flex-col transition-all duration-300 ${
          activeTab === 'chat' ? 'w-full lg:w-[55%]' : 'hidden lg:flex lg:w-[55%]'
        }`}>
          <ChatPanel
            history={history}
            onSendMessage={handleSendMessage}
            isLoading={isLoading}
            onCitationClick={handleCitationClick}
            onSelectQuickPrompt={handleSelectQuickPrompt}
          />
        </div>

        {/* Правая панель: Просмотр документов базы знаний (45% на десктопе) */}
        <div className={`h-full flex flex-col transition-all duration-300 ${
          activeTab === 'docs' ? 'w-full lg:w-[45%]' : 'hidden lg:flex lg:w-[45%]'
        }`}>
          <DocumentViewer
            selectedDocId={selectedDocId}
            targetFragmentId={targetFragmentId}
            onSelectDoc={(id) => {
              setSelectedDocId(id);
              setTargetFragmentId(null);
            }}
            onClearTargetFragment={() => setTargetFragmentId(null)}
          />
        </div>

      </main>

      {/* Модальное окно со сценариями */}
      <GoldenScenariosModal
        isOpen={isScenariosOpen}
        onClose={() => setIsScenariosOpen(false)}
        onSelectScenario={handleSelectQuickPrompt}
      />

    </div>
  );
}

export default App;
