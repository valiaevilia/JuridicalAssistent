package config

import (
	"os"
	"strings"
	"time"
)

// Config хранит конфигурацию Go API Gateway
type Config struct {
	Port          string
	PyWorkerURL   string
	DocsJSONPath  string
	ReadTimeout   time.Duration
	WriteTimeout  time.Duration
	IdleTimeout   time.Duration
	ClientTimeout time.Duration
}

// Load считывает переменные окружения с безопасными значениями по умолчанию
func Load() *Config {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8000"
	}
	if !strings.HasPrefix(port, ":") {
		port = ":" + port
	}

	pyWorkerURL := os.Getenv("PY_WORKER_URL")
	if pyWorkerURL == "" {
		pyWorkerURL = "http://127.0.0.1:8001"
	}
	pyWorkerURL = strings.TrimRight(pyWorkerURL, "/")

	docsPath := os.Getenv("DOCS_JSON_PATH")
	if docsPath == "" {
		docsPath = "../docs.json"
	}

	return &Config{
		Port:          port,
		PyWorkerURL:   pyWorkerURL,
		DocsJSONPath:  docsPath,
		ReadTimeout:   30 * time.Second,
		WriteTimeout:  90 * time.Second,
		IdleTimeout:   120 * time.Second,
		ClientTimeout: 60 * time.Second,
	}
}
