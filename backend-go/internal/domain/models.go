package domain

// Message представляет реплику в истории диалога
type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// ChatRequest представляет запрос к /api/chat
type ChatRequest struct {
	Messages []Message `json:"messages"`
}

// Citation представляет ссылку на подтверждающий фрагмент
type Citation struct {
	ID         int    `json:"id"`
	DocID      string `json:"doc_id"`
	FragmentID string `json:"fragment_id"`
	DocTitle   string `json:"doc_title"`
	Locator    string `json:"locator"`
	Quote      string `json:"quote"`
}

// ChatResponse представляет ответ ассистента по openapi.yaml
type ChatResponse struct {
	Answer      string     `json:"answer"`
	Status      string     `json:"status"`
	QueryType   string     `json:"query_type,omitempty"`
	Citations   []Citation `json:"citations"`
	MissingInfo []string   `json:"missing_info"`
	Steps       []string   `json:"steps,omitempty"`
	LatencyMs   int        `json:"latency_ms,omitempty"`
}

// DocumentMeta представляет метаданные документа
type DocumentMeta struct {
	DocID       string  `json:"doc_id"`
	Title       string  `json:"title"`
	DocType     string  `json:"doc_type,omitempty"`
	EditionDate *string `json:"edition_date,omitempty"`
}

// Fragment представляет отдельный пункт/статью документа
type Fragment struct {
	FragmentID  string   `json:"fragment_id"`
	DocID       string   `json:"doc_id"`
	Locator     string   `json:"locator"`
	Breadcrumbs []string `json:"breadcrumbs,omitempty"`
	Text        string   `json:"text"`
}

// Document представляет полный документ с фрагментами
type Document struct {
	DocID       string     `json:"doc_id"`
	Title       string     `json:"title"`
	DocType     string     `json:"doc_type,omitempty"`
	EditionDate *string    `json:"edition_date,omitempty"`
	Fragments   []Fragment `json:"fragments"`
}

// FragmentContextResponse представляет фрагмент с контекстом соседей
type FragmentContextResponse struct {
	Fragment Fragment   `json:"fragment"`
	Before   []Fragment `json:"before"`
	After    []Fragment `json:"after"`
}

// ErrorResponse представляет тело ошибки по openapi.yaml
type ErrorResponse struct {
	Detail string `json:"detail"`
}
