"""Natural-language -> SQL (Stage 1 of the four-stage pipeline).

Schema + few-shot corpus are injected wholesale into the system prompt.
No vector DB needed at this corpus size.
"""
from __future__ import annotations
import pathlib, re
import anthropic, yaml
from .config import get_settings

S = get_settings()
_SCHEMA_DIR = pathlib.Path(__file__).parent / "schema"

def _load_corpus() -> tuple[str, str]:
    tables = yaml.safe_load((_SCHEMA_DIR / "tables.yaml").read_text())
    examples = yaml.safe_load((_SCHEMA_DIR / "examples.yaml").read_text())
    schema_lines = []
    for t in tables.get("tables", []):
        cols = ", ".join(f"{c['name']} {c['type']}" for c in t.get("columns", []))
        schema_lines.append(f"- {t['name']} ({cols}). {t.get('notes', '')}".strip())
    ex_lines = []
    for ex in examples.get("examples", []):
        ex_lines.append(f"Q: {ex['question']}\nSQL:\n{ex['sql'].strip()}\n")
    return "\n".join(schema_lines), "\n".join(ex_lines)

def _system_prompt() -> str:
    schema_text, examples_text = _load_corpus()
    divisions = ", ".join(f"'{d}'" for d in S.EXCLUDED_DIVISIONS)
    store_types = ", ".join(f"'{t}'" for t in S.EXCLUDED_STORE_TYPES) if S.EXCLUDED_STORE_TYPES else "'Warehouse','FO'"
    return f"""You are a ClickHouse SQL generator for an Indian value-retail chain.
Return ONE ClickHouse SELECT statement only -- no prose, no markdown fences.

Schema:
{schema_text}

Rules:
- Read-only SELECT or WITH only.
- ALWAYS filter DIVISION NOT IN ({divisions}).
- Exclude warehouse/FO: STORE_TYPE NOT IN ({store_types}).
- BILLDATE is IST wall-clock in UTC-typed column -- use toDate(BILLDATE) directly.
- On ClickHouse 26.4+: resolve view columns via subqueries, not direct JOINs.
- Add LIMIT (<= {S.CH_MAX_ROWS}) unless the question is an aggregate total.

Examples:
{examples_text}"""

def _extract_sql(text: str) -> str:
    fenced = re.search(r"```(?:sql)?\s*(.+?)```", text, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else text
    m = re.search(r"\b(with|select)\b.*", candidate, re.DOTALL | re.IGNORECASE)
    return (m.group(0) if m else candidate).strip()

def generate_sql(question: str) -> str:
    client = anthropic.Anthropic(api_key=S.CLAUDE_API_KEY)
    msg = client.messages.create(
        model=S.CLAUDE_MODEL, max_tokens=1024, temperature=0.0,
        system=_system_prompt(),
        messages=[{"role": "user", "content": question}],
    )
    return _extract_sql(msg.content[0].text)
