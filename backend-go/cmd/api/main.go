package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"psb-legal-backend/internal/config"
	"psb-legal-backend/internal/storage"
	httptransport "psb-legal-backend/internal/transport/http"
	"psb-legal-backend/internal/worker"
)

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	cfg := config.Load()

	store := storage.NewDocStore()
	if err := store.Load(cfg.DocsJSONPath); err != nil {
		logger.Warn("Notice loading doc store", "error", err)
	}

	wClient := worker.NewClient(cfg.PyWorkerURL, cfg.ClientTimeout, logger)
	handler := httptransport.NewHandler(store, wClient, logger)
	router := httptransport.NewRouter(handler, logger)

	httpServer := &http.Server{
		Addr:         cfg.Port,
		Handler:      router,
		ReadTimeout:  cfg.ReadTimeout,
		WriteTimeout: cfg.WriteTimeout,
		IdleTimeout:  cfg.IdleTimeout,
	}

	stopChan := make(chan os.Signal, 1)
	signal.Notify(stopChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		logger.Info("Starting PSB Legal Assistant Go API Gateway",
			"addr", cfg.Port,
			"python_worker", cfg.PyWorkerURL,
			"documents_loaded", len(store.GetDocuments()),
		)
		if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("HTTP Server fatal error", "error", err)
			os.Exit(1)
		}
	}()

	<-stopChan
	logger.Info("Received shutdown signal. Commencing graceful shutdown...")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := httpServer.Shutdown(ctx); err != nil {
		logger.Error("Graceful shutdown failed", "error", err)
	} else {
		logger.Info("Server stopped cleanly")
	}
}
