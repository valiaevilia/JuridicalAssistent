# Stage 1: Builder
FROM golang:1.22-alpine AS builder

WORKDIR /build

COPY go.mod ./
RUN go mod download

COPY . .

RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /build/api ./cmd/api

# Stage 2: Minimal runner
FROM alpine:3.19

WORKDIR /app

RUN apk --no-cache add ca-certificates tzdata

COPY --from=builder /build/api /app/api

EXPOSE 8000

ENV PORT=:8000 \
    PY_WORKER_URL=http://py-worker:8001

ENTRYPOINT ["/app/api"]
