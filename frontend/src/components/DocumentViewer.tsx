import React, { useState, useEffect, useRef } from 'react';
import { 
  Search, 
  ChevronLeft, 
  ShieldAlert, 
  Calendar, 
  Building2, 
  BookOpen
} from 'lucide-react';
import type { DocumentDetail, DocumentMeta } from '../types';
import { fetchDocuments, fetchDocumentDetail } from '../api/client';

interface DocumentViewerProps {
  selectedDocId: string | null;
  targetFragmentId: string | null;
  onSelectDoc: (docId: string | null) => void;
  onClearTargetFragment: () => void;
}

export const DocumentViewer: React.FC<DocumentViewerProps> = ({
  selectedDocId,
  targetFragmentId,
  onSelectDoc
}) => {
  const [documents, setDocuments] = useState<DocumentMeta[]>([]);
  const [currentDoc, setCurrentDoc] = useState<DocumentDetail | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<'all' | 'contract' | 'regulation' | 'law'>('all');
  const [loading, setLoading] = useState(false);

  const fragmentRefs = useRef<{ [key: string]: HTMLDivElement | null }>({});

  useEffect(() => {
    fetchDocuments().then(setDocuments);
  }, []);

  useEffect(() => {
    if (!selectedDocId) {
      setCurrentDoc(null);
      return;
    }
    setLoading(true);
    fetchDocumentDetail(selectedDocId).then(doc => {
      setCurrentDoc(doc);
      setLoading(false);
    });
  }, [selectedDocId]);

  useEffect(() => {
    if (targetFragmentId && currentDoc) {
      const el = fragmentRefs.current[targetFragmentId];
      if (el) {
        setTimeout(() => {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          el.classList.remove('fragment-highlighted');
          void el.offsetWidth;
          el.classList.add('fragment-highlighted');
        }, 100);
      }
    }
  }, [targetFragmentId, currentDoc]);

  const filteredDocs = documents.filter(doc => {
    const matchesSearch = 
      doc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (doc.counterparty && doc.counterparty.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (doc.number && doc.number.toLowerCase().includes(searchQuery.toLowerCase()));

    if (!matchesSearch) return false;

    if (categoryFilter === 'all') return true;
    if (categoryFilter === 'contract') return doc.doc_type === 'contract' || doc.doc_type === 'amendment';
    if (categoryFilter === 'regulation') return doc.doc_type === 'regulation' || doc.doc_type === 'memo' || doc.doc_type === 'letter';
    if (categoryFilter === 'law') return doc.doc_type === 'law';
    return true;
  });

  return (
    <div className="h-full flex flex-col bg-white border-l border-slate-200 overflow-hidden shadow-inner">
      
      {/* Шапка правой панели */}
      <div className="bg-slate-50 border-b border-slate-200 px-4 py-2.5 shrink-0 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {currentDoc ? (
            <button
              onClick={() => onSelectDoc(null)}
              className="inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-2.5 py-1.5 rounded-md transition cursor-pointer"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              Ко всем документам
            </button>
          ) : (
            <div className="flex items-center gap-2 text-slate-800 font-semibold text-sm">
              <BookOpen className="w-4 h-4 text-blue-700" />
              База знаний
            </div>
          )}
        </div>

        {currentDoc && (
          <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full border ${
            currentDoc.status_badge?.includes('Утратил')
              ? 'bg-red-50 text-red-700 border-red-200'
              : 'bg-emerald-50 text-emerald-700 border-emerald-200'
          }`}>
            {currentDoc.status_badge || 'Действует'}
          </span>
        )}
      </div>

      {/* Контент */}
      {!currentDoc ? (
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Поиск и фильтры */}
          <div className="p-3 bg-slate-50 border-b border-slate-200 space-y-2">
            <div className="relative">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
              <input
                type="text"
                placeholder="Поиск по номеру, названию или контрагенту..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 text-xs bg-white border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent"
              />
            </div>
            
            {/* Кнопки-фильтры */}
            <div className="flex items-center gap-1.5 text-xs">
              <button
                onClick={() => setCategoryFilter('all')}
                className={`px-2.5 py-1 rounded-md transition font-medium cursor-pointer ${
                  categoryFilter === 'all'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white text-slate-600 hover:bg-slate-200 border border-slate-200'
                }`}
              >
                Все
              </button>
              <button
                onClick={() => setCategoryFilter('contract')}
                className={`px-2.5 py-1 rounded-md transition font-medium cursor-pointer ${
                  categoryFilter === 'contract'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white text-slate-600 hover:bg-slate-200 border border-slate-200'
                }`}
              >
                Договоры
              </button>
              <button
                onClick={() => setCategoryFilter('regulation')}
                className={`px-2.5 py-1 rounded-md transition font-medium cursor-pointer ${
                  categoryFilter === 'regulation'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white text-slate-600 hover:bg-slate-200 border border-slate-200'
                }`}
              >
                Регламенты
              </button>
              <button
                onClick={() => setCategoryFilter('law')}
                className={`px-2.5 py-1 rounded-md transition font-medium cursor-pointer ${
                  categoryFilter === 'law'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white text-slate-600 hover:bg-slate-200 border border-slate-200'
                }`}
              >
                Законы РФ
              </button>
            </div>
          </div>

          {/* Список документов */}
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {filteredDocs.map(doc => (
              <div
                key={doc.doc_id}
                onClick={() => onSelectDoc(doc.doc_id)}
                className="group p-3 rounded-lg border border-slate-200 hover:border-blue-400 bg-white hover:bg-blue-50/40 transition cursor-pointer shadow-xs flex flex-col gap-1.5"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-[11px] font-bold px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">
                      {doc.doc_id}
                    </span>
                    <h4 className="text-xs font-semibold text-slate-900 group-hover:text-blue-700 transition line-clamp-1">
                      {doc.title}
                    </h4>
                  </div>
                  <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full shrink-0 border ${
                    doc.status_badge?.includes('Утратил')
                      ? 'bg-red-50 text-red-700 border-red-200'
                      : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  }`}>
                    {doc.status_badge}
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
                  {doc.counterparty && (
                    <span className="flex items-center gap-1">
                      <Building2 className="w-3 h-3 text-slate-400" />
                      {doc.counterparty}
                    </span>
                  )}
                  {doc.edition_date && (
                    <span className="flex items-center gap-1">
                      <Calendar className="w-3 h-3 text-slate-400" />
                      {doc.edition_date}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        /* Просмотр выбранного документа */
        <div className="flex-1 flex flex-col overflow-hidden">
          
          {/* Метаданные выбранного документа */}
          <div className="p-4 bg-slate-50 border-b border-slate-200 shrink-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-blue-100 text-blue-800 border border-blue-200">
                {currentDoc.doc_id}
              </span>
              <h3 className="font-bold text-sm text-slate-900 leading-tight">
                {currentDoc.title}
              </h3>
            </div>
            
            <div className="grid grid-cols-2 gap-2 mt-2 pt-2 border-t border-slate-200 text-xs text-slate-600">
              {currentDoc.counterparty && (
                <div><span className="text-slate-400">Стороны:</span> {currentDoc.counterparty}</div>
              )}
              {currentDoc.edition_date && (
                <div><span className="text-slate-400">Дата:</span> {currentDoc.edition_date}</div>
              )}
            </div>
          </div>

          {/* Текст фрагментов документа */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3 font-serif text-sm leading-relaxed text-slate-800 bg-white">
            {loading ? (
              <div className="text-center py-10 text-slate-400 text-xs">Загрузка фрагментов документа...</div>
            ) : (
              currentDoc.fragments?.map((frag, index) => {
                const isTarget = targetFragmentId === frag.fragment_id;
                const isQuarantine = frag.text.includes("ВНИМАНИЕ ДЛЯ ИИ-АССИСТЕНТА");

                return (
                  <div
                    key={frag.fragment_id || index}
                    ref={(el) => {
                      fragmentRefs.current[frag.fragment_id] = el;
                    }}
                    id={`fragment-${frag.fragment_id}`}
                    className={`p-3 rounded-md transition-all border ${
                      isTarget
                        ? 'bg-amber-50/80 border-amber-300 shadow-sm'
                        : isQuarantine
                        ? 'bg-red-50/60 border-red-200 text-red-900'
                        : 'bg-white border-transparent hover:border-slate-200 hover:bg-slate-50/50'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1 font-sans">
                      <span className="text-[11px] font-bold font-mono px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
                        {frag.locator}
                      </span>
                      {isQuarantine && (
                        <span className="flex items-center gap-1 text-[10px] font-semibold text-red-700 bg-red-100 px-2 py-0.5 rounded-full">
                          <ShieldAlert className="w-3 h-3 text-red-600" />
                          Карантин (Попытка инъекции)
                        </span>
                      )}
                    </div>
                    
                    <p className={`text-xs ${isQuarantine ? 'font-mono text-xs line-through opacity-75' : ''}`}>
                      {frag.text}
                    </p>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

    </div>
  );
};
