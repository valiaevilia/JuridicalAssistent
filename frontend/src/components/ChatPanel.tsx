import React, { useState, useRef, useEffect } from 'react';
import { 
  Send, 
  Bot, 
  User, 
  CheckCircle2, 
  AlertTriangle, 
  HelpCircle, 
  Clock, 
  Copy, 
  Check, 
  BookOpen, 
  ExternalLink,
  ChevronRight,
  ListOrdered,
  ThumbsUp,
  ThumbsDown
} from 'lucide-react';
import type { UIHistoryItem, ResponseStatus, Citation } from '../types';

interface ChatPanelProps {
  history: UIHistoryItem[];
  onSendMessage: (text: string) => void;
  isLoading: boolean;
  onCitationClick: (docId: string, fragmentId: string) => void;
  onSelectQuickPrompt: (prompt: string) => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({
  history,
  onSendMessage,
  isLoading,
  onCitationClick,
  onSelectQuickPrompt
}) => {
  const [inputText, setInputText] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [feedbackState, setFeedbackState] = useState<{ [id: string]: 'up' | 'down' }>({});
  const [loadingStep, setLoadingStep] = useState(0);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [history, isLoading]);

  useEffect(() => {
    if (!isLoading) {
      setLoadingStep(0);
      return;
    }
    const steps = [
      'Поиск по базе нормативных документов...',
      'Анализ применимых положений и редакций...',
      'Формирование ответа со ссылками на первоисточники...'
    ];
    let cur = 0;
    const interval = setInterval(() => {
      cur = (cur + 1) % steps.length;
      setLoadingStep(cur);
    }, 450);
    return () => clearInterval(interval);
  }, [isLoading]);

  const handleSend = () => {
    if (!inputText.trim() || isLoading) return;
    onSendMessage(inputText.trim());
    setInputText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleFeedback = (msgId: string, type: 'up' | 'down') => {
    setFeedbackState(prev => ({ ...prev, [msgId]: type }));
  };

  const renderStatusBadge = (status?: ResponseStatus) => {
    switch (status) {
      case 'answered':
        return (
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 px-2.5 py-0.5 rounded-full">
            <CheckCircle2 className="w-3 h-3 text-emerald-600" />
            Подтверждено документами
          </span>
        );
      case 'partial':
        return (
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200 px-2.5 py-0.5 rounded-full">
            <AlertTriangle className="w-3 h-3 text-amber-600" />
            Частично подтверждено
          </span>
        );
      case 'refused':
        return (
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold bg-slate-100 text-slate-700 border border-slate-300 px-2.5 py-0.5 rounded-full">
            <HelpCircle className="w-3 h-3 text-slate-500" />
            Недостаточно данных в базе
          </span>
        );
      case 'out_of_scope':
        return (
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold bg-purple-50 text-purple-700 border border-purple-200 px-2.5 py-0.5 rounded-full">
            <HelpCircle className="w-3 h-3 text-purple-600" />
            Вне компетенции
          </span>
        );
      default:
        return null;
    }
  };

  const renderMessageContent = (content: string, citations?: Citation[]) => {
    if (!citations || citations.length === 0) {
      return <span>{content}</span>;
    }

    const parts = content.split(/(\[\d+\])/g);
    return (
      <>
        {parts.map((part, index) => {
          const match = part.match(/\[(\d+)\]/);
          if (match) {
            const citId = parseInt(match[1], 10);
            const cit = citations.find(c => c.id === citId);
            if (cit) {
              return (
                <button
                  key={index}
                  onClick={() => onCitationClick(cit.doc_id, cit.fragment_id)}
                  title={`${cit.doc_title} (${cit.locator}): «${cit.quote}»`}
                  className="inline-flex items-center justify-center mx-1 px-1.5 py-0.2 rounded-md font-mono text-[11px] font-bold bg-blue-100 hover:bg-blue-600 text-blue-800 hover:text-white border border-blue-300 transition-all cursor-pointer align-baseline"
                >
                  [{citId}]
                </button>
              );
            }
          }
          return <span key={index}>{part}</span>;
        })}
      </>
    );
  };

  const quickPrompts = [
    {
      title: 'Аренда склада в Химках',
      desc: 'Арендная плата и срок внесения (А-08/2024)',
      text: 'Какая арендная плата по договору с ООО «Северный Склад» и до какого числа её нужно вносить?'
    },
    {
      title: 'Договоры с Альфой',
      desc: 'Различие «Альфа-Трейд» (мебель) и «Альфа-Трейдинг» (ПК)',
      text: 'Какой гарантийный срок установлен по договору с Альфой?'
    },
    {
      title: 'Одобрение гендиректором',
      desc: 'Смена редакций: порог 10 млн (2024) vs 15 млн (2025)',
      text: 'Договор на 12 млн рублей заключали в августе 2024 года. Нужно ли было одобрение генерального директора?'
    },
    {
      title: 'Отзыв согласия на ПДн',
      desc: '152-ФЗ ст. 9 (отсутствие обязательного удаления всех данных)',
      text: 'Человек отозвал согласие на обработку данных. Значит, мы обязаны сразу удалить вообще всё?'
    },
    {
      title: 'Срок оплаты мебели',
      desc: 'Договор поставки мебели П-17/2024',
      text: 'По договору с ООО «Альфа-Трейд» какой срок оплаты мебели?'
    }
  ];

  return (
    <div className="flex-1 flex flex-col h-full bg-slate-100 overflow-hidden">
      
      {/* Лента сообщений */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4">
        
        {history.length === 0 ? (
          /* Стартовый экран */
          <div className="max-w-2xl mx-auto py-8 space-y-6">
            <div className="text-center space-y-2">
              <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-blue-700 text-white shadow-lg shadow-blue-700/20 mb-1">
                <Bot className="w-7 h-7" />
              </div>
              <h2 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">
                Юридический ассистент ПСБ
              </h2>
              <p className="text-xs sm:text-sm text-slate-600 max-w-lg mx-auto leading-relaxed">
                Поиск нормативных оснований и проверка условий договоров по базе знаний банка и законодательству РФ.
              </p>
            </div>

            {/* Быстрые примеры вопросов */}
            <div className="space-y-2 pt-2">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider block px-1">
                Примеры запросов:
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                {quickPrompts.map((p, idx) => (
                  <button
                    key={idx}
                    onClick={() => onSelectQuickPrompt(p.text)}
                    className="text-left p-3 rounded-xl bg-white hover:bg-blue-50/70 border border-slate-200 hover:border-blue-400 transition-all shadow-xs group cursor-pointer"
                  >
                    <div className="flex items-center justify-between text-xs font-bold text-slate-800 group-hover:text-blue-700">
                      <span>{p.title}</span>
                      <ChevronRight className="w-3.5 h-3.5 text-slate-400 group-hover:text-blue-600 group-hover:translate-x-0.5 transition" />
                    </div>
                    <div className="text-[11px] text-slate-500 mt-1 line-clamp-1">
                      {p.desc}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          /* Список сообщений диалога */
          history.map((msg) => (
            <div
              key={msg.id}
              className={`flex gap-3 max-w-3xl mx-auto ${
                msg.role === 'user' ? 'justify-end' : 'justify-start'
              }`}
            >
              {msg.role === 'assistant' && (
                <div className="w-8 h-8 rounded-xl bg-blue-800 text-white flex items-center justify-center shrink-0 shadow-md">
                  <Bot className="w-4 h-4" />
                </div>
              )}

              <div
                className={`max-w-[88%] rounded-2xl p-4 shadow-xs space-y-3 ${
                  msg.role === 'user'
                    ? 'bg-blue-700 text-white ml-10 rounded-br-xs'
                    : 'bg-white text-slate-900 border border-slate-200 rounded-bl-xs'
                }`}
              >
                {/* Шапка сообщения ассистента */}
                {msg.role === 'assistant' && (
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-2">
                    <div className="flex items-center gap-2">
                      {renderStatusBadge(msg.responseMeta?.status)}
                    </div>
                    {msg.responseMeta?.latency_ms && (
                      <span className="flex items-center gap-1 text-[11px] text-slate-400 font-mono">
                        <Clock className="w-3 h-3" />
                        {msg.responseMeta.latency_ms} мс
                      </span>
                    )}
                  </div>
                )}

                {/* Текст ответа с интерактивными кнопками цитат */}
                <div className={`text-xs sm:text-sm leading-relaxed whitespace-pre-wrap ${
                  msg.role === 'user' ? 'text-white' : 'text-slate-800'
                }`}>
                  {msg.role === 'assistant'
                    ? renderMessageContent(msg.content, msg.responseMeta?.citations)
                    : msg.content}
                </div>

                {/* Недостающая информация (при partial или refused) */}
                {msg.responseMeta?.missing_info && msg.responseMeta.missing_info.length > 0 && (
                  <div className="p-3 bg-amber-50/70 border border-amber-200 rounded-xl text-xs space-y-1.5">
                    <div className="font-semibold text-amber-900 flex items-center gap-1.5">
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
                      Для полного ответа в базе знаний отсутствуют:
                    </div>
                    <ul className="list-disc list-inside text-amber-800 space-y-0.5 text-[11px]">
                      {msg.responseMeta.missing_info.map((item, i) => (
                        <li key={i}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Рекомендуемые шаги */}
                {msg.responseMeta?.steps && msg.responseMeta.steps.length > 0 && (
                  <div className="p-3 bg-blue-50/60 border border-blue-200 rounded-xl text-xs space-y-1.5">
                    <div className="font-semibold text-blue-900 flex items-center gap-1.5">
                      <ListOrdered className="w-3.5 h-3.5 text-blue-700" />
                      Рекомендуемые действия:
                    </div>
                    <ol className="list-decimal list-inside text-blue-800 space-y-0.5 text-[11px]">
                      {msg.responseMeta.steps.map((step, i) => (
                        <li key={i}>{step}</li>
                      ))}
                    </ol>
                  </div>
                )}

                {/* Карточки цитат / первоисточников */}
                {msg.responseMeta?.citations && msg.responseMeta.citations.length > 0 && (
                  <div className="space-y-2 pt-2 border-t border-slate-100">
                    <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-1">
                      <BookOpen className="w-3 h-3 text-blue-600" />
                      Подтверждающие положения (клик для перехода к документу):
                    </div>
                    <div className="grid grid-cols-1 gap-1.5">
                      {msg.responseMeta.citations.map((c) => (
                        <button
                          key={c.id}
                          onClick={() => onCitationClick(c.doc_id, c.fragment_id)}
                          className="text-left p-2.5 rounded-lg bg-slate-50 hover:bg-blue-50/80 border border-slate-200 hover:border-blue-400 transition-all flex items-start justify-between gap-2 group cursor-pointer"
                        >
                          <div className="space-y-0.5">
                            <div className="flex items-center gap-1.5">
                              <span className="font-bold text-[10px] px-1.5 py-0.2 rounded bg-blue-100 text-blue-800 font-mono">
                                [{c.id}]
                              </span>
                              <span className="font-semibold text-xs text-slate-900 group-hover:text-blue-700">
                                {c.doc_title}
                              </span>
                              <span className="text-[11px] font-mono text-slate-500">
                                · {c.locator}
                              </span>
                            </div>
                            <p className="text-[11px] text-slate-600 italic line-clamp-2">
                              «{c.quote}»
                            </p>
                          </div>
                          <ExternalLink className="w-3.5 h-3.5 text-slate-400 group-hover:text-blue-600 shrink-0 mt-0.5" />
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Подвал сообщения: Копирование и Фидбек (👍 / 👎) */}
                {msg.role === 'assistant' && (
                  <div className="flex items-center justify-between pt-1 text-[11px] text-slate-500 border-t border-slate-100">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => handleFeedback(msg.id, 'up')}
                        className={`p-1 rounded hover:bg-slate-100 transition cursor-pointer ${
                          feedbackState[msg.id] === 'up' ? 'text-emerald-600 font-bold' : ''
                        }`}
                        title="Ответ точен и полезен"
                      >
                        <ThumbsUp className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => handleFeedback(msg.id, 'down')}
                        className={`p-1 rounded hover:bg-slate-100 transition cursor-pointer ${
                          feedbackState[msg.id] === 'down' ? 'text-rose-600 font-bold' : ''
                        }`}
                        title="Есть замечание к ответу"
                      >
                        <ThumbsDown className="w-3.5 h-3.5" />
                      </button>
                      {feedbackState[msg.id] && (
                        <span className="text-[10px] text-slate-400 ml-1">
                          Спасибо за оценку!
                        </span>
                      )}
                    </div>

                    <button
                      onClick={() => handleCopy(msg.content, msg.id)}
                      className="inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-800 transition py-0.5 px-2 rounded-md hover:bg-slate-100 cursor-pointer"
                      title="Скопировать юридический ответ со ссылками"
                    >
                      {copiedId === msg.id ? (
                        <>
                          <Check className="w-3 h-3 text-emerald-600" />
                          <span className="text-emerald-700 font-medium">Скопировано</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3 h-3" />
                          <span>Копировать</span>
                        </>
                      )}
                    </button>
                  </div>
                )}

              </div>

              {msg.role === 'user' && (
                <div className="w-8 h-8 rounded-xl bg-slate-800 text-white flex items-center justify-center shrink-0 shadow-md">
                  <User className="w-4 h-4" />
                </div>
              )}
            </div>
          ))
        )}

        {/* Индикатор ожидания ответа */}
        {isLoading && (
          <div className="flex gap-3 max-w-3xl mx-auto items-start">
            <div className="w-8 h-8 rounded-xl bg-blue-800 text-white flex items-center justify-center shrink-0 animate-pulse shadow-md">
              <Bot className="w-4 h-4" />
            </div>
            <div className="bg-white rounded-2xl p-4 border border-blue-200 shadow-sm space-y-2 max-w-[80%]">
              <div className="flex items-center gap-2">
                <div className="flex gap-1">
                  <span className="w-2 h-2 rounded-full bg-blue-600 animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-2 h-2 rounded-full bg-blue-600 animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-2 h-2 rounded-full bg-blue-600 animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
                <span className="text-xs font-semibold text-blue-900">
                  Поиск в базе знаний...
                </span>
              </div>
              <p className="text-[11px] text-slate-500 font-medium animate-pulse">
                {[
                  'Поиск по базе нормативных документов...',
                  'Анализ применимых положений и редакций...',
                  'Формирование ответа со ссылками на первоисточники...'
                ][loadingStep]}
              </p>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Панель ввода вопроса (прижата к нижнему краю, без лишнего подвала) */}
      <div className="p-3 bg-white border-t border-slate-200 shrink-0 space-y-2">
        
        {/* Компактные быстрые примеры над строкой ввода */}
        <div className="max-w-3xl mx-auto flex items-center gap-1.5 overflow-x-auto pb-0.5 text-[11px] text-slate-600 no-scrollbar">
          <span className="text-slate-400 shrink-0 font-medium">
            Примеры:
          </span>
          <button
            onClick={() => onSelectQuickPrompt('Какая арендная плата по договору с ООО «Северный Склад» и до какого числа её нужно вносить?')}
            className="px-2.5 py-1 rounded-full bg-slate-100 hover:bg-blue-100 text-slate-700 hover:text-blue-800 transition whitespace-nowrap cursor-pointer shrink-0 border border-slate-200"
          >
            Аренда Химки (А-08/2024)
          </button>
          <button
            onClick={() => onSelectQuickPrompt('Какой гарантийный срок установлен по договору с Альфой?')}
            className="px-2.5 py-1 rounded-full bg-slate-100 hover:bg-blue-100 text-slate-700 hover:text-blue-800 transition whitespace-nowrap cursor-pointer shrink-0 border border-slate-200"
          >
            Альфа-Трейд vs Трейдинг
          </button>
          <button
            onClick={() => onSelectQuickPrompt('Договор на 12 млн рублей заключали в августе 2024 года. Нужно ли было одобрение генерального директора?')}
            className="px-2.5 py-1 rounded-full bg-slate-100 hover:bg-blue-100 text-slate-700 hover:text-blue-800 transition whitespace-nowrap cursor-pointer shrink-0 border border-slate-200"
          >
            Лимит гендиректора (2024 vs 2025)
          </button>
          <button
            onClick={() => onSelectQuickPrompt('Человек отозвал согласие на обработку данных. Значит, мы обязаны сразу удалить вообще всё?')}
            className="px-2.5 py-1 rounded-full bg-slate-100 hover:bg-blue-100 text-slate-700 hover:text-blue-800 transition whitespace-nowrap cursor-pointer shrink-0 border border-slate-200"
          >
            Отзыв ПДн (152-ФЗ ст. 9)
          </button>
          <button
            onClick={() => onSelectQuickPrompt('По договору с ООО «Альфа-Трейд» какой срок оплаты мебели?')}
            className="px-2.5 py-1 rounded-full bg-slate-100 hover:bg-blue-100 text-slate-700 hover:text-blue-800 transition whitespace-nowrap cursor-pointer shrink-0 border border-slate-200"
          >
            Срок оплаты (П-17/2024)
          </button>
        </div>

        <div className="max-w-3xl mx-auto">
          <div className="relative flex items-end gap-2 bg-slate-50 rounded-2xl border border-slate-300 focus-within:border-blue-600 focus-within:ring-2 focus-within:ring-blue-600/20 p-1.5 transition shadow-inner">
            <textarea
              ref={textareaRef}
              rows={1}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Задайте вопрос по договорам или законодательству..."
              disabled={isLoading}
              className="flex-1 max-h-32 bg-transparent text-xs sm:text-sm text-slate-800 placeholder-slate-400 resize-none focus:outline-none p-1.5 leading-relaxed"
            />
            <button
              onClick={handleSend}
              disabled={!inputText.trim() || isLoading}
              className={`p-2 rounded-xl transition shadow-sm shrink-0 ${
                inputText.trim() && !isLoading
                  ? 'bg-blue-700 hover:bg-blue-800 text-white cursor-pointer'
                  : 'bg-slate-200 text-slate-400 cursor-not-allowed'
              }`}
              title="Отправить вопрос"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>

      </div>

    </div>
  );
};
