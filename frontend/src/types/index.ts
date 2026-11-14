export type MessageRole = 'user' | 'assistant';

export interface ChatMessage {
  role: MessageRole;
  content: string;
}

export type ResponseStatus = 'answered' | 'refused' | 'needs_clarification' | 'out_of_scope' | 'partial';

export interface Citation {
  id: number;
  doc_id: string;
  fragment_id: string;
  doc_title: string;
  locator: string;
  quote: string;
}

export interface ChatResponse {
  answer: string;
  status: ResponseStatus;
  query_type?: string;
  citations: Citation[];
  missing_info?: string[];
  steps?: string[];
  latency_ms?: number;
}

export interface DocumentMeta {
  doc_id: string;
  title: string;
  doc_type?: string; // contract | amendment | regulation | letter | memo | law
  edition_date?: string | null;
  status_badge?: string; // "Действует" | "Утратил силу"
  counterparty?: string;
  number?: string;
}

export interface Fragment {
  fragment_id: string;
  doc_id: string;
  locator: string;
  breadcrumbs?: string[];
  text: string;
}

export interface DocumentDetail extends DocumentMeta {
  fragments: Fragment[];
}

export interface UIHistoryItem {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
  responseMeta?: {
    status: ResponseStatus;
    query_type?: string;
    citations: Citation[];
    missing_info?: string[];
    steps?: string[];
    latency_ms?: number;
  };
}
