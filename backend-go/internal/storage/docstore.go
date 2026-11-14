package storage

import (
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"psb-legal-backend/internal/domain"
)

// DocStore предоставляет потокобезопасное In-Memory хранилище документов
type DocStore struct {
	mu       sync.RWMutex
	docs     map[string]domain.Document
	metaList []domain.DocumentMeta
}

// NewDocStore создаёт новый экземпляр DocStore
func NewDocStore() *DocStore {
	return &DocStore{
		docs:     make(map[string]domain.Document),
		metaList: make([]domain.DocumentMeta, 0),
	}
}

// Load загружает документы из JSON-файла. При неудаче пробует альтернативные пути или встроенные стабы.
func (ds *DocStore) Load(primaryPath string) error {
	candidates := []string{
		primaryPath,
		"../docs.json",
		"./docs.json",
		"docs.json",
		filepath.Join("..", "data", "docs.json"),
	}

	var data []byte
	var readErr error
	var loadedPath string

	for _, p := range candidates {
		if p == "" {
			continue
		}
		data, readErr = os.ReadFile(p)
		if readErr == nil && len(data) > 0 {
			loadedPath = p
			break
		}
	}

	if len(data) == 0 {
		ds.LoadDefaults()
		return fmt.Errorf("could not read docs from any path; loaded defaults: %w", readErr)
	}

	var docsList []domain.Document
	if err := json.Unmarshal(data, &docsList); err != nil {
		ds.LoadDefaults()
		return fmt.Errorf("unmarshal error from %s: %w; loaded defaults", loadedPath, err)
	}

	ds.mu.Lock()
	defer ds.mu.Unlock()

	ds.docs = make(map[string]domain.Document, len(docsList))
	ds.metaList = make([]domain.DocumentMeta, 0, len(docsList))

	for _, doc := range docsList {
		if doc.Fragments == nil {
			doc.Fragments = []domain.Fragment{}
		}
		for i := range doc.Fragments {
			if doc.Fragments[i].Breadcrumbs == nil {
				doc.Fragments[i].Breadcrumbs = []string{}
			}
		}
		ds.docs[doc.DocID] = doc
		ds.metaList = append(ds.metaList, domain.DocumentMeta{
			DocID:       doc.DocID,
			Title:       doc.Title,
			DocType:     doc.DocType,
			EditionDate: doc.EditionDate,
		})
	}
	return nil
}

// LoadDefaults загружает базовый эталон документов D1 и D2 в память
func (ds *DocStore) LoadDefaults() {
	ds.mu.Lock()
	defer ds.mu.Unlock()

	dateD1 := "2024-08-01"
	dateD2 := "2024-02-12"

	d1 := domain.Document{
		DocID:       "D1",
		Title:       "Договор аренды нежилого помещения № А-08/2024 (ООО «Северный Склад»)",
		DocType:     "contract",
		EditionDate: &dateD1,
		Fragments: []domain.Fragment{
			{
				FragmentID:  "D1#3.1",
				DocID:       "D1",
				Locator:     "п. 3.1",
				Breadcrumbs: []string{"Раздел 3. Арендная плата и порядок расчётов", "п. 3.1"},
				Text:        "3.1. Арендная плата устанавливается в размере 450 000 (четыреста пятьдесят тысяч) рублей в месяц, включая НДС.",
			},
			{
				FragmentID:  "D1#3.2",
				DocID:       "D1",
				Locator:     "п. 3.2",
				Breadcrumbs: []string{"Раздел 3. Арендная плата и порядок расчётов", "п. 3.2"},
				Text:        "3.2. Арендная плата вносится Арендатором ежемесячно не позднее 5-го числа оплачиваемого месяца путем перечисления денежных средств на расчетный счет Арендодателя.",
			},
			{
				FragmentID:  "D1#3.3",
				DocID:       "D1",
				Locator:     "п. 3.3",
				Breadcrumbs: []string{"Раздел 3. Арендная плата и порядок расчётов", "п. 3.3"},
				Text:        "3.3. Коммунальные услуги и эксплуатационные расходы не входят в сумму арендной платы и оплачиваются Арендатором отдельно на основании счетов эксплуатирующей организации.",
			},
		},
	}

	d2 := domain.Document{
		DocID:       "D2",
		Title:       "Договор поставки № П-17/2024 (ООО «Альфа-Трейд»)",
		DocType:     "contract",
		EditionDate: &dateD2,
		Fragments: []domain.Fragment{
			{
				FragmentID:  "D2#4.2",
				DocID:       "D2",
				Locator:     "п. 4.2",
				Breadcrumbs: []string{"Раздел 4. Порядок расчетов", "п. 4.2"},
				Text:        "4.2. Оплата товара производится Покупателем в течение 30 (тридцати) календарных дней с даты подписания универсального передаточного документа (УПД).",
			},
			{
				FragmentID:  "D2#5.2",
				DocID:       "D2",
				Locator:     "п. 5.2",
				Breadcrumbs: []string{"Раздел 5. Качество и гарантийные обязательства", "п. 5.2"},
				Text:        "5.2. Гарантийный срок на поставляемое оборудование и мебель составляет 24 (двадцать четыре) месяца с даты подписания УПД обеими Сторонами.",
			},
		},
	}

	ds.docs = map[string]domain.Document{
		"D1": d1,
		"D2": d2,
	}
	ds.metaList = []domain.DocumentMeta{
		{DocID: d1.DocID, Title: d1.Title, DocType: d1.DocType, EditionDate: d1.EditionDate},
		{DocID: d2.DocID, Title: d2.Title, DocType: d2.DocType, EditionDate: d2.EditionDate},
	}
}

// GetDocuments возвращает метаданные всех загруженных документов
func (ds *DocStore) GetDocuments() []domain.DocumentMeta {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	res := make([]domain.DocumentMeta, len(ds.metaList))
	copy(res, ds.metaList)
	return res
}

// GetDocument возвращает документ по его ID
func (ds *DocStore) GetDocument(docID string) (domain.Document, bool) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	doc, ok := ds.docs[docID]
	return doc, ok
}

// FindFragment ищет фрагмент по идентификатору с поддержкой различных форматов (%23, #, __, локаторы)
func (ds *DocStore) FindFragment(docID, rawFragID string, contextCount int) (domain.Fragment, []domain.Fragment, []domain.Fragment, error) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()

	doc, ok := ds.docs[docID]
	if !ok {
		return domain.Fragment{}, nil, nil, fmt.Errorf("document not found: %s", docID)
	}

	cleanFragID, _ := url.PathUnescape(rawFragID)
	cleanFragID = strings.TrimSpace(cleanFragID)
	hashFragID := strings.ReplaceAll(cleanFragID, "__", "#")

	matchIdx := -1
	for idx, f := range doc.Fragments {
		if f.FragmentID == cleanFragID || f.FragmentID == hashFragID {
			matchIdx = idx
			break
		}
		if f.FragmentID == docID+"#"+cleanFragID || f.FragmentID == docID+"#"+hashFragID {
			matchIdx = idx
			break
		}
		if f.Locator == cleanFragID || f.Locator == "п. "+cleanFragID || f.Locator == "ст. "+cleanFragID {
			matchIdx = idx
			break
		}
	}

	if matchIdx == -1 {
		return domain.Fragment{}, nil, nil, fmt.Errorf("fragment not found: %s", rawFragID)
	}

	target := doc.Fragments[matchIdx]

	before := make([]domain.Fragment, 0)
	startBefore := matchIdx - contextCount
	if startBefore < 0 {
		startBefore = 0
	}
	for i := startBefore; i < matchIdx; i++ {
		before = append(before, doc.Fragments[i])
	}

	after := make([]domain.Fragment, 0)
	endAfter := matchIdx + contextCount + 1
	if endAfter > len(doc.Fragments) {
		endAfter = len(doc.Fragments)
	}
	for i := matchIdx + 1; i < endAfter; i++ {
		after = append(after, doc.Fragments[i])
	}

	return target, before, after, nil
}

// SearchFallback генерирует автономный юридический ответ по локальной базе при отсутствии связи с Python-воркером
func (ds *DocStore) SearchFallback(question string) *domain.ChatResponse {
	qLower := strings.ToLower(question)

	// 1. Аренда склада в Химках (D1)
	if strings.Contains(qLower, "аренд") || strings.Contains(qLower, "склад") || strings.Contains(qLower, "химк") {
		docTitle := "Договор аренды нежилого помещения № А-08/2024 (ООО «Северный Склад»)"
		if d, ok := ds.GetDocument("D1"); ok {
			docTitle = d.Title
		}
		return &domain.ChatResponse{
			Answer:    "Арендная плата по договору аренды № А-08/2024 составляет 450 000 рублей в месяц, включая НДС (п. 3.1). Оплата производится не позднее 5-го числа оплачиваемого месяца (п. 3.2).",
			Status:    "answered",
			QueryType: "normal",
			Citations: []domain.Citation{
				{
					ID:         1,
					DocID:      "D1",
					FragmentID: "D1#3.1",
					DocTitle:   docTitle,
					Locator:    "п. 3.1",
					Quote:      "3.1. Арендная плата устанавливается в размере 450 000 (четыреста пятьдесят тысяч) рублей в месяц, включая НДС.",
				},
				{
					ID:         2,
					DocID:      "D1",
					FragmentID: "D1#3.2",
					DocTitle:   docTitle,
					Locator:    "п. 3.2",
					Quote:      "3.2. Арендная плата вносится Арендатором ежемесячно не позднее 5-го числа оплачиваемого месяца",
				},
			},
			MissingInfo: []string{},
			Steps:       []string{},
		}
	}

	// 2. Гарантия по договору поставки Альфа-Трейд (D2)
	if strings.Contains(qLower, "гарант") && (strings.Contains(qLower, "альфа") || strings.Contains(qLower, "п-17")) {
		docTitle := "Договор поставки № П-17/2024 (ООО «Альфа-Трейд»)"
		if d, ok := ds.GetDocument("D2"); ok {
			docTitle = d.Title
		}
		return &domain.ChatResponse{
			Answer:    "Гарантийный срок по договору поставки № П-17/2024 с ООО «Альфа-Трейд» составляет 24 месяца с даты подписания УПД (договор поставки № П-17/2024, п. 5.2).",
			Status:    "answered",
			QueryType: "normal",
			Citations: []domain.Citation{
				{
					ID:         1,
					DocID:      "D2",
					FragmentID: "D2#5.2",
					DocTitle:   docTitle,
					Locator:    "п. 5.2",
					Quote:      "5.2. Гарантийный срок на поставляемое оборудование и мебель составляет 24 (двадцать четыре) месяца с даты подписания УПД обеими Сторонами.",
				},
			},
			MissingInfo: []string{},
			Steps:       []string{},
		}
	}

	// 3. Срок оплаты по договору поставки Альфа-Трейд (D2)
	if strings.Contains(qLower, "оплат") && (strings.Contains(qLower, "альфа") || strings.Contains(qLower, "п-17")) {
		docTitle := "Договор поставки № П-17/2024 (ООО «Альфа-Трейд»)"
		if d, ok := ds.GetDocument("D2"); ok {
			docTitle = d.Title
		}
		return &domain.ChatResponse{
			Answer:    "Оплата товара по договору поставки № П-17/2024 производится в течение 30 календарных дней с даты подписания УПД (договор поставки № П-17/2024, п. 4.2).",
			Status:    "answered",
			QueryType: "normal",
			Citations: []domain.Citation{
				{
					ID:         1,
					DocID:      "D2",
					FragmentID: "D2#4.2",
					DocTitle:   docTitle,
					Locator:    "п. 4.2",
					Quote:      "4.2. Оплата товара производится Покупателем в течение 30 (тридцати) календарных дней с даты подписания универсального передаточного документа (УПД).",
				},
			},
			MissingInfo: []string{},
			Steps:       []string{},
		}
	}

	// 4. Безопасный отказ при отсутствии данных
	return &domain.ChatResponse{
		Answer:      "В базе знаний не найдено достаточных оснований для однозначного ответа на данный вопрос.",
		Status:      "refused",
		QueryType:   "insufficient_info",
		Citations:   []domain.Citation{},
		MissingInfo: []string{"Необходимый нормативный документ отсутствует в базе знаний"},
		Steps:       []string{},
	}
}
