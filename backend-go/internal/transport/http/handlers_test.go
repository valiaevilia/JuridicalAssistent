package http

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"psb-legal-backend/internal/domain"
	"psb-legal-backend/internal/storage"
	"psb-legal-backend/internal/worker"
)

func setupTestRouter(pyWorkerURL string) http.Handler {
	store := storage.NewDocStore()
	store.LoadDefaults()
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	wClient := worker.NewClient(pyWorkerURL, 5*time.Second, logger)
	h := NewHandler(store, wClient, logger)
	return NewRouter(h, logger)
}

func TestHealth(t *testing.T) {
	router := setupTestRouter("http://127.0.0.1:9999")

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rec := httptest.NewRecorder()

	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}

	var res map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &res); err != nil {
		t.Fatalf("invalid json: %v", err)
	}
	if res["status"] != "ok" {
		t.Errorf("expected status ok, got %s", res["status"])
	}
}

func TestGetDocuments(t *testing.T) {
	router := setupTestRouter("http://127.0.0.1:9999")

	req := httptest.NewRequest(http.MethodGet, "/api/documents", nil)
	rec := httptest.NewRecorder()

	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}

	var docs []domain.DocumentMeta
	if err := json.Unmarshal(rec.Body.Bytes(), &docs); err != nil {
		t.Fatalf("invalid json: %v", err)
	}
	if len(docs) < 2 {
		t.Errorf("expected at least 2 docs, got %d", len(docs))
	}
}

func TestGetDocumentByID(t *testing.T) {
	router := setupTestRouter("http://127.0.0.1:9999")

	// 1. Успешный запрос D1
	req := httptest.NewRequest(http.MethodGet, "/api/documents/D1", nil)
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}

	var doc domain.Document
	if err := json.Unmarshal(rec.Body.Bytes(), &doc); err != nil {
		t.Fatalf("invalid json: %v", err)
	}
	if doc.DocID != "D1" {
		t.Errorf("expected D1, got %s", doc.DocID)
	}
	if len(doc.Fragments) == 0 {
		t.Errorf("expected fragments for D1, got 0")
	}

	// 2. 404 для неизвестного документа
	req404 := httptest.NewRequest(http.MethodGet, "/api/documents/UNKNOWN_99", nil)
	rec404 := httptest.NewRecorder()
	router.ServeHTTP(rec404, req404)

	if rec404.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", rec404.Code)
	}
}

func TestGetFragment(t *testing.T) {
	router := setupTestRouter("http://127.0.0.1:9999")

	// 1. Поиск по прямому ID с %23 и context=1
	req := httptest.NewRequest(http.MethodGet, "/api/documents/D1/fragments/D1%233.2?context=1", nil)
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d (body: %s)", rec.Code, rec.Body.String())
	}

	var fragResp domain.FragmentContextResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &fragResp); err != nil {
		t.Fatalf("invalid json: %v", err)
	}
	if fragResp.Fragment.FragmentID != "D1#3.2" {
		t.Errorf("expected D1#3.2, got %s", fragResp.Fragment.FragmentID)
	}
	if len(fragResp.Before) != 1 || fragResp.Before[0].FragmentID != "D1#3.1" {
		t.Errorf("expected before to contain D1#3.1, got %+v", fragResp.Before)
	}
	if len(fragResp.After) != 1 || fragResp.After[0].FragmentID != "D1#3.3" {
		t.Errorf("expected after to contain D1#3.3, got %+v", fragResp.After)
	}

	// 2. Поиск с нотацией __ (D1__3.1)
	req2 := httptest.NewRequest(http.MethodGet, "/api/documents/D1/fragments/D1__3.1?context=0", nil)
	rec2 := httptest.NewRecorder()
	router.ServeHTTP(rec2, req2)

	if rec2.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec2.Code)
	}
	var fragResp2 domain.FragmentContextResponse
	json.Unmarshal(rec2.Body.Bytes(), &fragResp2)
	if fragResp2.Fragment.FragmentID != "D1#3.1" {
		t.Errorf("expected D1#3.1, got %s", fragResp2.Fragment.FragmentID)
	}
	if len(fragResp2.Before) != 0 || len(fragResp2.After) != 0 {
		t.Errorf("expected 0 before/after with context=0, got %d/%d", len(fragResp2.Before), len(fragResp2.After))
	}

	// 3. Поиск по короткому номеру пункта (3.1)
	req3 := httptest.NewRequest(http.MethodGet, "/api/documents/D1/fragments/3.1", nil)
	rec3 := httptest.NewRecorder()
	router.ServeHTTP(rec3, req3)

	if rec3.Code != http.StatusOK {
		t.Fatalf("expected 200 for locator 3.1, got %d", rec3.Code)
	}

	// 4. Ошибка валидации context (422)
	req422 := httptest.NewRequest(http.MethodGet, "/api/documents/D1/fragments/3.1?context=99", nil)
	rec422 := httptest.NewRecorder()
	router.ServeHTTP(rec422, req422)
	if rec422.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected 422 for context=99, got %d", rec422.Code)
	}

	// 5. 404 для неизвестного фрагмента
	req404 := httptest.NewRequest(http.MethodGet, "/api/documents/D1/fragments/UNKNOWN", nil)
	rec404 := httptest.NewRecorder()
	router.ServeHTTP(rec404, req404)
	if rec404.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", rec404.Code)
	}
}

func TestChatValidation(t *testing.T) {
	router := setupTestRouter("http://127.0.0.1:9999")

	// 1. Пустой массив messages -> 422
	bodyEmpty, _ := json.Marshal(domain.ChatRequest{Messages: []domain.Message{}})
	req1 := httptest.NewRequest(http.MethodPost, "/api/chat", bytes.NewReader(bodyEmpty))
	rec1 := httptest.NewRecorder()
	router.ServeHTTP(rec1, req1)
	if rec1.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected 422 for empty messages, got %d", rec1.Code)
	}

	// 2. Последнее сообщение от assistant -> 422
	bodyAssistantLast, _ := json.Marshal(domain.ChatRequest{
		Messages: []domain.Message{
			{Role: "user", Content: "Вопрос"},
			{Role: "assistant", Content: "Ответ"},
		},
	})
	req2 := httptest.NewRequest(http.MethodPost, "/api/chat", bytes.NewReader(bodyAssistantLast))
	rec2 := httptest.NewRecorder()
	router.ServeHTTP(rec2, req2)
	if rec2.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected 422 when last message is assistant, got %d", rec2.Code)
	}

	// 3. Неверная роль -> 422
	bodyInvalidRole, _ := json.Marshal(map[string]interface{}{
		"messages": []map[string]string{
			{"role": "admin", "content": "hello"},
		},
	})
	req3 := httptest.NewRequest(http.MethodPost, "/api/chat", bytes.NewReader(bodyInvalidRole))
	rec3 := httptest.NewRecorder()
	router.ServeHTTP(rec3, req3)
	if rec3.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected 422 for invalid role, got %d", rec3.Code)
	}
}

func TestChatAutonomousFallback(t *testing.T) {
	// Python воркер выключен -> проверяем автономный Go-фоллбэк
	router := setupTestRouter("http://127.0.0.1:9999")

	body, _ := json.Marshal(domain.ChatRequest{
		Messages: []domain.Message{
			{Role: "user", Content: "Какова арендная плата склада в Химках?"},
		},
	})
	req := httptest.NewRequest(http.MethodPost, "/api/chat", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d (body: %s)", rec.Code, rec.Body.String())
	}

	var chatResp domain.ChatResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &chatResp); err != nil {
		t.Fatalf("invalid json: %v", err)
	}

	if chatResp.Status != "answered" {
		t.Errorf("expected status 'answered', got '%s'", chatResp.Status)
	}
	if len(chatResp.Citations) == 0 {
		t.Errorf("expected citations in fallback response, got 0")
	}
	if chatResp.Citations[0].DocID != "D1" {
		t.Errorf("expected doc_id D1, got %s", chatResp.Citations[0].DocID)
	}
}

func TestChatWithMockPythonWorker(t *testing.T) {
	// Мок-сервер Python-воркера
	mockPyWorker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/answer" {
			http.NotFound(w, r)
			return
		}

		body, _ := io.ReadAll(r.Body)
		var req map[string]string
		json.Unmarshal(body, &req)

		// Возвращаем ответ со статусом "partial", который Go должен смаппить в "answered"
		pyAnswer := map[string]interface{}{
			"text":       "Подтверждено положение статьи 9 (п. 2), но статей 6 и 10 нет в базе.",
			"status":     "partial",
			"query_type": "insufficient_info",
			"claims": []map[string]interface{}{
				{
					"doc_id":   "D1",
					"chunk_id": "D1#3.1",
					"locator":  "п. 3.1",
					"quote":    "3.1. Арендная плата...",
				},
			},
			"missing": []string{"Статьи 6, 10 152-ФЗ"},
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(pyAnswer)
	}))
	defer mockPyWorker.Close()

	router := setupTestRouter(mockPyWorker.URL)

	body, _ := json.Marshal(domain.ChatRequest{
		Messages: []domain.Message{
			{Role: "user", Content: "История вопроса 1"},
			{Role: "assistant", Content: "Ответ 1"},
			{Role: "user", Content: "Можно ли продолжить обработку ПДн?"},
		},
	})
	req := httptest.NewRequest(http.MethodPost, "/api/chat", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d (body: %s)", rec.Code, rec.Body.String())
	}

	var chatResp domain.ChatResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &chatResp); err != nil {
		t.Fatalf("invalid json: %v", err)
	}

	// Проверяем маппинг "partial" -> "answered"
	if chatResp.Status != "answered" {
		t.Errorf("expected status 'answered' (mapped from partial), got '%s'", chatResp.Status)
	}
	if len(chatResp.MissingInfo) != 1 || chatResp.MissingInfo[0] != "Статьи 6, 10 152-ФЗ" {
		t.Errorf("expected missing_info to be preserved, got %+v", chatResp.MissingInfo)
	}
	if len(chatResp.Citations) != 1 || chatResp.Citations[0].FragmentID != "D1#3.1" {
		t.Errorf("expected citation D1#3.1, got %+v", chatResp.Citations)
	}
}

func TestSyncDocumentsFromWorker(t *testing.T) {
	mockPyWorker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/documents" {
			http.NotFound(w, r)
			return
		}

		resp := map[string]interface{}{
			"documents": []domain.Document{
				{
					DocID:   "D21",
					Title:   "Федеральный закон № 152-ФЗ",
					DocType: "law",
					Fragments: []domain.Fragment{
						{
							FragmentID:  "D21#1",
							DocID:       "D21",
							Locator:     "ст. 1",
							Breadcrumbs: []string{"Статья 1"},
							Text:        "Сфера действия настоящего Федерального закона.",
						},
					},
				},
			},
			"total": 1,
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	}))
	defer mockPyWorker.Close()

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	store := storage.NewDocStore()
	store.LoadDefaults()
	wClient := worker.NewClient(mockPyWorker.URL, 5*time.Second, logger)

	// До синка - дефолтные документы (D1, D2)
	if !store.IsDefaultOnly() {
		t.Fatalf("expected store to be default only initially")
	}

	// Синхронизируем напрямую
	err := store.SyncFromWorker(context.Background(), wClient)
	if err != nil {
		t.Fatalf("SyncFromWorker failed: %v", err)
	}

	docs := store.GetDocuments()
	if len(docs) != 1 || docs[0].DocID != "D21" {
		t.Fatalf("expected 1 doc (D21) after sync, got %+v", docs)
	}
	if store.IsDefaultOnly() {
		t.Fatalf("expected store not to be default only after syncing D21")
	}
}
