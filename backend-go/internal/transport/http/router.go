package http

import (
	"log/slog"
	"net/http"
)

// NewRouter регистрирует маршруты openapi.yaml и оборачивает их в цепочку middleware
func NewRouter(h *Handler, logger *slog.Logger) http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /health", h.HealthHandler)
	mux.HandleFunc("POST /api/chat", h.ChatHandler)
	mux.HandleFunc("GET /api/documents", h.GetDocumentsHandler)
	mux.HandleFunc("GET /api/documents/{doc_id}", h.GetDocumentByIDHandler)
	mux.HandleFunc("GET /api/documents/{doc_id}/fragments/{fragment_id...}", h.GetFragmentHandler)

	// Цепочка middleware: CORS -> Recoverer -> Logging
	var handler http.Handler = mux
	handler = CORS(handler)
	handler = Recoverer(logger)(handler)
	handler = Logging(logger)(handler)

	return handler
}
