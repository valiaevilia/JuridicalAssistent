import type { ChatMessage, ChatResponse, DocumentDetail, DocumentMeta, Fragment } from '../types';
import { mockDocuments, findMockResponse } from './mockData';

const BASE_URL = import.meta.env.VITE_BACKEND_URL || '';

export async function fetchDocuments(): Promise<DocumentMeta[]> {
  try {
    const res = await fetch(`${BASE_URL}/api/documents`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    // Если бэкенд ещё не запущен, отдаем локальный каталог документов
    return mockDocuments.map(({ doc_id, title, doc_type, edition_date, status_badge, counterparty, number }) => ({
      doc_id,
      title,
      doc_type,
      edition_date,
      status_badge,
      counterparty,
      number
    }));
  }
}

export async function fetchDocumentDetail(docId: string): Promise<DocumentDetail | null> {
  try {
    const res = await fetch(`${BASE_URL}/api/documents/${docId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    // Фоллбэк на локальный документ, пока бэкенд в разработке
    return mockDocuments.find(d => d.doc_id === docId) || null;
  }
}

export async function fetchFragment(docId: string, fragmentId: string, context = 1): Promise<{
  fragment: Fragment;
  before: Fragment[];
  after: Fragment[];
} | null> {
  try {
    const res = await fetch(`${BASE_URL}/api/documents/${docId}/fragments/${fragmentId}?context=${context}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    const doc = mockDocuments.find(d => d.doc_id === docId);
    if (!doc) return null;
    const idx = doc.fragments.findIndex(f => f.fragment_id === fragmentId);
    if (idx === -1) return null;

    const start = Math.max(0, idx - context);
    const end = Math.min(doc.fragments.length, idx + context + 1);

    return {
      fragment: doc.fragments[idx],
      before: doc.fragments.slice(start, idx),
      after: doc.fragments.slice(idx + 1, end)
    };
  }
}

export async function sendChatMessage(messages: ChatMessage[]): Promise<ChatResponse> {
  const lastUserMsg = messages[messages.length - 1]?.content || '';

  try {
    const res = await fetch(`${BASE_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages })
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Server error: ${res.status}`);
    }

    return await res.json();
  } catch (err: any) {
    // Фоллбэк на эталонный ответ, пока бэкенд не запущен
    await new Promise(r => setTimeout(r, 400));
    return findMockResponse(lastUserMsg);
  }
}
