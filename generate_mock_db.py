import os
import json
import re

KB_DIR = r"C:\Users\Denis\Desktop\Hacaton_PSB\Всё подряд\knowledge-base"
OUT_FILE = r"C:\Users\Denis\Desktop\Hacaton_PSB\JuridicalAssistent\frontend\src\api\documentsData.json"

DOC_META = {
    "документы компании__Договор аренды А-08-2024 Северный Склад.txt": {
        "doc_id": "D1",
        "title": "Договор аренды нежилого помещения № А-08/2024",
        "doc_type": "contract",
        "edition_date": "2024-08-01",
        "status_badge": "Действует",
        "counterparty": "ООО «Северный Склад»",
        "number": "А-08/2024"
    },
    "документы компании__Договор поставки П-17-2024 Альфа-Трейд.txt": {
        "doc_id": "D2",
        "title": "Договор поставки мебели и оборудования № П-17/2024",
        "doc_type": "contract",
        "edition_date": "2024-02-12",
        "status_badge": "Действует до 31.12.2026",
        "counterparty": "ООО «Альфа-Трейд»",
        "number": "П-17/2024"
    },
    "документы компании__Договор поставки ПТ-05-2023 Альфа-Трейдинг.txt": {
        "doc_id": "D3",
        "title": "Договор поставки компьютерной техники № ПТ-05/2023",
        "doc_type": "contract",
        "edition_date": "2023-06-20",
        "status_badge": "Действует (автопродление)",
        "counterparty": "ООО «Альфа-Трейдинг»",
        "number": "ПТ-05/2023"
    },
    "документы компании__Доп соглашение 1 к договору П-17-2024.txt": {
        "doc_id": "D4",
        "title": "Дополнительное соглашение № 1 к договору № П-17/2024",
        "doc_type": "amendment",
        "edition_date": "2024-09-03",
        "status_badge": "Действует с 01.10.2024",
        "counterparty": "ООО «Альфа-Трейд»",
        "number": "Доп. соглашение № 1"
    },
    "документы компании__Письмо комплаенс-службы К-12 от 15.04.2025.txt": {
        "doc_id": "D5",
        "title": "Письмо службы комплаенс № К-12 от 15.04.2025",
        "doc_type": "letter",
        "edition_date": "2025-04-15",
        "status_badge": "Действует с 21.04.2025",
        "counterparty": "Служба комплаенс ООО «Меридиан»",
        "number": "К-12"
    },
    "документы компании__Регламент согласования договоров ред 2023 (утратил силу).txt": {
        "doc_id": "D6",
        "title": "Регламент согласования договоров (ред. 10.01.2023)",
        "doc_type": "regulation",
        "edition_date": "2023-01-10",
        "status_badge": "Утратил силу с 01.03.2025",
        "counterparty": "ООО «Меридиан»",
        "number": "Регламент-2023"
    },
    "документы компании__Регламент согласования договоров ред 2025.txt": {
        "doc_id": "D7",
        "title": "Регламент согласования договоров (ред. 01.03.2025)",
        "doc_type": "regulation",
        "edition_date": "2025-03-01",
        "status_badge": "Действует",
        "counterparty": "ООО «Меридиан»",
        "number": "Регламент-2025"
    },
    "документы компании__Служебная записка об архиве договоров.txt": {
        "doc_id": "D8",
        "title": "Служебная записка № ЮО-7 об архиве договоров",
        "doc_type": "memo",
        "edition_date": "2025-05-12",
        "status_badge": "Действует",
        "counterparty": "Юридический отдел ООО «Меридиан»",
        "number": "ЮО-7"
    },
    "законы__152ФЗ_ст9_действующая.txt": {
        "doc_id": "L6",
        "title": "152-ФЗ «О персональных данных», ст. 9 (Согласие субъекта)",
        "doc_type": "law",
        "edition_date": "2026-10-10",
        "status_badge": "Действующая ред.",
        "counterparty": "Российская Федерация",
        "number": "152-ФЗ ст. 9"
    },
    "законы__КоАП_ст13.11_действующая.txt": {
        "doc_id": "L7",
        "title": "КоАП РФ, ст. 13.11 (Нарушение законодательства в области ПДн)",
        "doc_type": "law",
        "edition_date": "2026-10-10",
        "status_badge": "Действующая ред.",
        "counterparty": "Российская Федерация",
        "number": "КоАП ст. 13.11"
    },
    "законы__МРОТ_ст1_действующая.txt": {
        "doc_id": "L5",
        "title": "82-ФЗ «О минимальном размере оплаты труда», ст. 1 (МРОТ)",
        "doc_type": "law",
        "edition_date": "2026-10-10",
        "status_badge": "Действующая ред. (с 01.01.2026)",
        "counterparty": "Российская Федерация",
        "number": "82-ФЗ ст. 1"
    },
    "законы__НК_ст112_действующая.txt": {
        "doc_id": "L8",
        "title": "НК РФ, ст. 112 (Смягчающие и отягчающие обстоятельства)",
        "doc_type": "law",
        "edition_date": "2026-10-10",
        "status_badge": "Действующая ред.",
        "counterparty": "Российская Федерация",
        "number": "НК РФ ст. 112"
    },
    "законы__НК_ст114_действующая.txt": {
        "doc_id": "L9",
        "title": "НК РФ, ст. 114 (Налоговые санкции)",
        "doc_type": "law",
        "edition_date": "2026-10-10",
        "status_badge": "Действующая ред.",
        "counterparty": "Российская Федерация",
        "number": "НК РФ ст. 114"
    },
    "законы__НК_ст145_действующая.txt": {
        "doc_id": "L10",
        "title": "НК РФ, ст. 145 (Освобождение от уплаты НДС)",
        "doc_type": "law",
        "edition_date": "2026-10-10",
        "status_badge": "Действующая ред.",
        "counterparty": "Российская Федерация",
        "number": "НК РФ ст. 145"
    },
    "законы__НК_ст164_действующая.txt": {
        "doc_id": "L11",
        "title": "НК РФ, ст. 164 (Налоговые ставки НДС)",
        "doc_type": "law",
        "edition_date": "2026-10-10",
        "status_badge": "Действующая ред. (22% с 2026 г.)",
        "counterparty": "Российская Федерация",
        "number": "НК РФ ст. 164"
    },
    "законы__НК_ст224_действующая.txt": {
        "doc_id": "L12",
        "title": "НК РФ, ст. 224 (Налоговые ставки НДФЛ)",
        "doc_type": "law",
        "edition_date": "2026-10-10",
        "status_badge": "Действующая ред. (прогрессивная шкала)",
        "counterparty": "Российская Федерация",
        "number": "НК РФ ст. 224"
    },
    "законы__НК_ст284_действующая.txt": {
        "doc_id": "L13",
        "title": "НК РФ, ст. 284 (Налоговые ставки по налогу на прибыль)",
        "doc_type": "law",
        "edition_date": "2026-10-10",
        "status_badge": "Действующая ред. (25%)",
        "counterparty": "Российская Федерация",
        "number": "НК РФ ст. 284"
    },
    "законы__ТК_ст59_действующая.txt": {
        "doc_id": "L1",
        "title": "ТК РФ, ст. 59 (Срочный трудовой договор)",
        "doc_type": "law",
        "edition_date": "2026-10-10",
        "status_badge": "Действующая ред.",
        "counterparty": "Российская Федерация",
        "number": "ТК РФ ст. 59"
    },
    "законы__ТК_ст70_действующая.txt": {
        "doc_id": "L2",
        "title": "ТК РФ, ст. 70 (Испытание при приеме на работу)",
        "doc_type": "law",
        "edition_date": "2026-10-10",
        "status_badge": "Действующая ред.",
        "counterparty": "Российская Федерация",
        "number": "ТК РФ ст. 70"
    },
    "законы__ТК_ст99_действующая.txt": {
        "doc_id": "L3",
        "title": "ТК РФ, ст. 99 (Сверхурочная работа)",
        "doc_type": "law",
        "edition_date": "2026-10-10",
        "status_badge": "Действующая ред.",
        "counterparty": "Российская Федерация",
        "number": "ТК РФ ст. 99"
    },
    "законы__ТК_ст152_действующая.txt": {
        "doc_id": "L4",
        "title": "ТК РФ, ст. 152 (Оплата сверхурочной работы)",
        "doc_type": "law",
        "edition_date": "2026-10-10",
        "status_badge": "Действующая ред.",
        "counterparty": "Российская Федерация",
        "number": "ТК РФ ст. 152"
    }
}

documents = []

for filename, meta in DOC_META.items():
    filepath = os.path.join(KB_DIR, filename)
    if not os.path.exists(filepath):
        continue
    
    with open(filepath, "r", encoding="utf-8-sig", errors="ignore") as f:
        text = f.read()

    doc_id = meta["doc_id"]
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    
    fragments = []
    current_section = ""
    frag_idx = 1
    
    for line in lines:
        # Поиск паттернов пунктов типа 1.1, 2.3, ч. 1, п. 3, ст.
        m = re.match(r"^(\d+\.\d+(\.\d+)?|\d+\.|\bп\.\s*\d+(\.\d+)?|\bч\.\s*\d+|\bСтатья\s*\d+(\.\d+)?)", line)
        if m:
            locator = m.group(1).rstrip(".")
            if not locator.startswith("п.") and not locator.startswith("ч.") and not locator.startswith("Статья"):
                locator = f"п. {locator}"
        else:
            locator = f"фрагмент {frag_idx}"
            
        is_quarantine = "ВНИМАНИЕ ДЛЯ ИИ-АССИСТЕНТА" in line
        
        frag_id = f"{doc_id}-f{frag_idx}"
        fragments.append({
            "fragment_id": frag_id,
            "doc_id": doc_id,
            "locator": locator,
            "breadcrumbs": [meta["title"], locator],
            "text": line,
            "is_quarantine": is_quarantine
        })
        frag_idx += 1

    documents.append({
        **meta,
        "fragments": fragments
    })

os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
with open(OUT_FILE, "w", encoding="utf-8") as f:
    json.dump(documents, f, ensure_ascii=False, indent=2)

print(f"Successfully generated {len(documents)} documents in {OUT_FILE}")
