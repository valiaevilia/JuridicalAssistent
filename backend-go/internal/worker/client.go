package worker

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"psb-legal-backend/internal/domain"
)

// DocTitleResolver интерфейс для получения заголовка документа по его ID
type DocTitleResolver interface {
	GetDocument(docID string) (domain.Document, bool)
}

// Client выполняет HTTP-запросы к Python-воркеру
type Client struct {
	baseURL    string
	httpClient *http.Client
	logger     *slog.Logger
}

// NewClient создаёт новый экземпляр Client
func NewClient(baseURL string, timeout time.Duration, logger *slog.Logger) *Client {
	if logger == nil {
		logger = slog.Default()
	}
	return &Client{
		baseURL: strings.TrimRight(baseURL, "/"),
		httpClient: &http.Client{
			Timeout: timeout,
		},
		logger: logger,
	}
}

// FormatMessages форматирует массив сообщений в единую строку формата платформы
func FormatMessages(messages []domain.Message) string {
	if len(messages) == 1 {
		return messages[0].Content
	}
	var sb strings.Builder
	for i, m := range messages {
		roleLabel := "Пользователь"
		if m.Role == "assistant" {
			roleLabel = "Ассистент"
		}
		sb.WriteString(fmt.Sprintf("%s: %s", roleLabel, m.Content))
		if i < len(messages)-1 {
			sb.WriteString("\n")
		}
	}
	return sb.String()
}

// RawWorkerResponse структура сырого ответа от Python worker.py
type RawWorkerResponse struct {
	Text      string                   `json:"text"`
	Status    string                   `json:"status"`
	QueryType string                   `json:"query_type"`
	Claims    []map[string]interface{} `json:"claims"`
	Missing   []string                 `json:"missing"`
	Warnings  []string                 `json:"warnings"`
	Debug     map[string]interface{}   `json:"debug"`
}

// Ask отправляет вопрос в Python-воркер и преобразует ответ в доменный ChatResponse
func (c *Client) Ask(ctx context.Context, question string, resolver DocTitleResolver) (*domain.ChatResponse, error) {
	payload, err := json.Marshal(map[string]string{"question": question})
	if err != nil {
		return nil, fmt.Errorf("marshal worker request failed: %w", err)
	}

	url := fmt.Sprintf("%s/internal/answer", c.baseURL)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return nil, fmt.Errorf("create worker request failed: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("worker request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("worker status %d: %s", resp.StatusCode, string(body))
	}

	var raw RawWorkerResponse
	if err := json.NewDecoder(resp.Body).Decode(&raw); err != nil {
		return nil, fmt.Errorf("decode worker response failed: %w", err)
	}

	// Маппинг статусов (внутренний "partial" маппится в "answered" по openapi.yaml)
	status := raw.Status
	if status == "partial" {
		status = "answered"
	}
	switch status {
	case "answered", "refused", "needs_clarification", "out_of_scope":
		// Валидный статус
	default:
		status = "answered"
	}

	queryType := raw.QueryType
	switch queryType {
	case "normal", "insufficient_info", "wrong_premise", "date_edition", "illegal_intent", "manipulation", "off_topic", "needs_clarification":
		// Валидный тип
	default:
		queryType = "normal"
	}

	citations := make([]domain.Citation, 0)
	for i, claim := range raw.Claims {
		docID, _ := claim["doc_id"].(string)
		chunkID, _ := claim["chunk_id"].(string)
		locator, _ := claim["locator"].(string)
		quote, _ := claim["quote"].(string)
		textClaim, _ := claim["text"].(string)

		docTitle := "Документ базы знаний"
		if resolver != nil {
			if doc, ok := resolver.GetDocument(docID); ok && doc.Title != "" {
				docTitle = doc.Title
			}
		}

		if quote == "" {
			quote = textClaim
		}

		citations = append(citations, domain.Citation{
			ID:         i + 1,
			DocID:      docID,
			FragmentID: chunkID,
			DocTitle:   docTitle,
			Locator:    locator,
			Quote:      quote,
		})
	}

	missing := raw.Missing
	if missing == nil {
		missing = []string{}
	}

	return &domain.ChatResponse{
		Answer:      raw.Text,
		Status:      status,
		QueryType:   queryType,
		Citations:   citations,
		MissingInfo: missing,
		Steps:       []string{},
	}, nil
}

// InternalDocsResponse описывает ответ от GET /internal/documents
type InternalDocsResponse struct {
	DocsMap   map[string]domain.Document `json:"docs_map"`
	Documents []domain.Document          `json:"documents"`
	Total     int                        `json:"total"`
}

// FetchDocuments загружает актуальные документы из Python-воркера
func (c *Client) FetchDocuments(ctx context.Context) ([]domain.Document, error) {
	url := fmt.Sprintf("%s/internal/documents", c.baseURL)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("create docs request failed: %w", err)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("fetch docs from worker failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("worker status %d: %s", resp.StatusCode, string(body))
	}

	var res InternalDocsResponse
	if err := json.NewDecoder(resp.Body).Decode(&res); err != nil {
		return nil, fmt.Errorf("decode docs response failed: %w", err)
	}

	if len(res.Documents) > 0 {
		return res.Documents, nil
	}

	docs := make([]domain.Document, 0, len(res.DocsMap))
	for _, d := range res.DocsMap {
		docs = append(docs, d)
	}
	return docs, nil
}
