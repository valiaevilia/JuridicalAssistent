package http

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"psb-legal-backend/internal/domain"
	"psb-legal-backend/internal/storage"
	"psb-legal-backend/internal/worker"
)

// Handler содержит зависимости для обработки HTTP-запросов
type Handler struct {
	store  *storage.DocStore
	worker *worker.Client
	logger *slog.Logger
}

// NewHandler создаёт новый экземпляр Handler
func NewHandler(store *storage.DocStore, workerClient *worker.Client, logger *slog.Logger) *Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return &Handler{
		store:  store,
		worker: workerClient,
		logger: logger,
	}
}

func (h *Handler) sendJSON(w http.ResponseWriter, status int, payload interface{}) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(payload); err != nil {
		h.logger.Error("Failed to encode response JSON", "error", err)
	}
}

// HealthHandler обрабатывает GET /health
func (h *Handler) HealthHandler(w http.ResponseWriter, r *http.Request) {
	h.sendJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// GetDocumentsHandler обрабатывает GET /api/documents
func (h *Handler) GetDocumentsHandler(w http.ResponseWriter, r *http.Request) {
	if h.store.IsDefaultOnly() && h.worker != nil {
		syncCtx, syncCancel := context.WithTimeout(r.Context(), 1500*time.Millisecond)
		if err := h.store.SyncFromWorker(syncCtx, h.worker); err == nil {
			h.logger.Info("Synchronized documents from Python worker on demand", "count", len(h.store.GetDocuments()))
		}
		syncCancel()
	}

	docs := h.store.GetDocuments()
	if docs == nil {
		docs = []domain.DocumentMeta{}
	}
	h.sendJSON(w, http.StatusOK, docs)
}

// GetDocumentByIDHandler обрабатывает GET /api/documents/{doc_id}
func (h *Handler) GetDocumentByIDHandler(w http.ResponseWriter, r *http.Request) {
	docID := r.PathValue("doc_id")
	doc, ok := h.store.GetDocument(docID)
	if !ok {
		h.sendJSON(w, http.StatusNotFound, domain.ErrorResponse{
			Detail: "Документ не найден",
		})
		return
	}
	h.sendJSON(w, http.StatusOK, doc)
}

// GetFragmentHandler обрабатывает GET /api/documents/{doc_id}/fragments/{fragment_id...}
func (h *Handler) GetFragmentHandler(w http.ResponseWriter, r *http.Request) {
	docID := r.PathValue("doc_id")
	fragmentID := r.PathValue("fragment_id")

	contextCount := 1
	if rawCtx := r.URL.Query().Get("context"); rawCtx != "" {
		parsed, err := strconv.Atoi(rawCtx)
		if err != nil || parsed < 0 || parsed > 5 {
			h.sendJSON(w, http.StatusUnprocessableEntity, domain.ErrorResponse{
				Detail: "Параметр context должен быть целым числом от 0 до 5",
			})
			return
		}
		contextCount = parsed
	}

	frag, before, after, err := h.store.FindFragment(docID, fragmentID, contextCount)
	if err != nil {
		if strings.Contains(err.Error(), "document not found") {
			h.sendJSON(w, http.StatusNotFound, domain.ErrorResponse{Detail: "Документ не найден"})
			return
		}
		h.sendJSON(w, http.StatusNotFound, domain.ErrorResponse{Detail: "Фрагмент не найден"})
		return
	}

	if before == nil {
		before = []domain.Fragment{}
	}
	if after == nil {
		after = []domain.Fragment{}
	}

	h.sendJSON(w, http.StatusOK, domain.FragmentContextResponse{
		Fragment: frag,
		Before:   before,
		After:    after,
	})
}

// ChatHandler обрабатывает POST /api/chat
func (h *Handler) ChatHandler(w http.ResponseWriter, r *http.Request) {
	start := time.Now()

	var req domain.ChatRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		h.sendJSON(w, http.StatusUnprocessableEntity, domain.ErrorResponse{
			Detail: fmt.Sprintf("Невалидный JSON тела запроса: %v", err),
		})
		return
	}

	// 1. Проверка на непустой массив messages
	if len(req.Messages) == 0 {
		h.sendJSON(w, http.StatusUnprocessableEntity, domain.ErrorResponse{
			Detail: "Массив messages не может быть пустым",
		})
		return
	}

	// 2. Проверка ролей сообщений
	for i, m := range req.Messages {
		if m.Role != "user" && m.Role != "assistant" {
			h.sendJSON(w, http.StatusUnprocessableEntity, domain.ErrorResponse{
				Detail: fmt.Sprintf("Недопустимая роль '%s' в сообщении %d (допустимы user, assistant)", m.Role, i),
			})
			return
		}
	}

	// 3. Последнее сообщение обязательно должно быть от user
	lastMsg := req.Messages[len(req.Messages)-1]
	if lastMsg.Role != "user" {
		h.sendJSON(w, http.StatusUnprocessableEntity, domain.ErrorResponse{
			Detail: "Последнее сообщение в диалоге должно быть от пользователя (role: user)",
		})
		return
	}

	// 4. Склейка истории реплик
	formattedQuestion := worker.FormatMessages(req.Messages)

	// 5. Запрос к воркеру с fallback на автономный Go-стор
	resp, err := h.worker.Ask(r.Context(), formattedQuestion, h.store)
	if err != nil {
		h.logger.Warn("Python worker unavailable; using autonomous Go fallback", "error", err)
		resp = h.store.SearchFallback(formattedQuestion)
	}

	resp.LatencyMs = int(time.Since(start).Milliseconds())
	h.sendJSON(w, http.StatusOK, resp)
}
