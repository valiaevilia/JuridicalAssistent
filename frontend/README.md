# Фронтенд — Юридический ассистент ПСБ

Веб-интерфейс рабочего места юриста банка с поддержкой двухпанельного режима (Split-Screen), просмотра базы знаний и интерактивной подсветки первоисточников.

## Стек технологий
- **React 18** + **TypeScript**
- **Vite**
- **Tailwind CSS**
- **Lucide Icons**

## Локальный запуск в режиме разработки
```bash
cd frontend
npm install
npm run dev
```
Интерфейс откроется по адресу: `http://localhost:5173`

## Сборка для production
```bash
npm run build
```
Собранные статические файлы будут в каталоге `dist/`.

## Запуск в Docker
Фронтенд упакован в Docker-образ с nginx:
```bash
docker build -t juridical-assistant-frontend .
docker run -p 80:80 juridical-assistant-frontend
```

## Соответствие API
Фронтенд взаимодействует с бэкендом по спецификации `openapi.yaml`:
- `POST /api/chat`
- `GET /api/documents`
- `GET /api/documents/{doc_id}`
- `GET /api/documents/{doc_id}/fragments/{fragment_id}`
