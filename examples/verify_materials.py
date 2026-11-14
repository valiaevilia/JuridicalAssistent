"""Проверка происхождения ручных фикстур; исходные материалы только читаются.

python -m examples.verify_materials --data-dir <папка организаторов>
Это не индексатор R и не оценка качества LLM.
"""

import argparse
import csv
import json
import zipfile
from pathlib import Path

from guard import exact_quote, parse_dialogue
from tests.fixtures import FILES, INJECTION, SAMPLES


DEMO_EVIDENCE = {
    '1': ['rent', 'rent_due'], '2': ['trial'], '3': [], '4': ['rent', 'rent_growth'],
    '5': ['old_approval'], '6': ['quality'], '7': ['access'], '8': ['claim'],
    '9': ['advance'], '10': ['initiator'], '11': ['archive'], '12': ['labor_rules'],
    '13': ['consent'], '14': ['season'], '15': ['return'], '16': ['included'],
    '17': ['manufacturer'], '18': ['original'],
}


def verify(data_dir):
    data_dir = Path(data_dir)
    with zipfile.ZipFile(data_dir / 'knowledge-base.zip') as archive:
        docs = {name: archive.read(name).decode('utf-8-sig') for name in archive.namelist() if name.endswith('.txt')}
    for name, c in SAMPLES.items():
        candidates = [text for filename, text in docs.items() if FILES[c.doc_id] in filename]
        if len(candidates) != 1 or exact_quote(c.text, candidates[0]) is None:
            raise AssertionError('Фикстура не совпадает с исходником: ' + name)
    if not any(INJECTION in text for text in docs.values()):
        raise AssertionError('Ожидаемая тестовая инъекция не найдена в исходной базе')
    for filename in ('demo_questions.csv', 'demo_output.csv'):
        with (data_dir / filename).open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        if set(row['id'] for row in rows) != set(DEMO_EVIDENCE):
            raise AssertionError('Изменился набор демо: ' + filename)
        if filename == 'demo_questions.csv':
            for row in rows:
                if not parse_dialogue(row['question']).last_user:
                    raise AssertionError('Не разобран демо-диалог: ' + row['id'])
    return {'source_documents': len(docs), 'verified_manual_fragments': len(SAMPLES),
            'demo_questions_parsed': len(DEMO_EVIDENCE), 'known_injection_confirmed': True,
            'tk_152_present': any('ТК_ст152' in name for name in docs),
            'scope': 'provenance_and_input_format_only; no_live_llm_evaluation'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.data_dir), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
