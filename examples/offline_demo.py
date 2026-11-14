"""python -m examples.offline_demo — ручные демонстрационные данные, без поиска."""

from answer import Metrics, answer, prepare_query
from config import LConfig
from examples.offline_client import ScriptedLLM, query_response, review_ok
from schemas import Chunk, RetrievalResult


def main():
    question = "Какой срок оплаты по договору № П-17/2024?"
    quote = "Покупатель оплачивает Товар в течение 30 (тридцати) календарных дней с даты подписания универсального передаточного документа (УПД) на соответствующую партию."
    chunk = Chunk("D2#4.2", "D2", "Договор поставки № П-17/2024", locator="п. 4.2", text=quote)
    claim_text = "Товар оплачивается в течение 30 календарных дней с даты подписания УПД на соответствующую партию"
    draft = {"status": "answered", "answer": claim_text,
             "claims": [{"text": claim_text, "chunk": "Д1", "quote": quote}],
             "missing": [], "assumptions": [], "calc": []}
    client = ScriptedLLM([query_response(question), draft, review_ok()])
    config = LConfig()
    qinfo = prepare_query(question, client=client, config=config)
    result = answer(qinfo, RetrievalResult([chunk]), client=client, config=config)
    print("OFFLINE-ДЕМО: ручной фрагмент и запрограммированные ответы LLM; поиска по базе нет.")
    print("Вопрос:", question)
    print("Ответ:", result.text)
    print("Статус:", result.status)
    print("Вызовов тестового клиента:", result.debug["llm_calls"])
    metrics = Metrics()
    metrics.add(result)
    metrics.emit()


if __name__ == "__main__":
    main()
