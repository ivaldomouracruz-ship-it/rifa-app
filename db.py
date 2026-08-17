import os
import sqlite3
import requests

TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL", "")  # ex: libsql://seu-banco.turso.io
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")

LOCAL_DB_PATH = os.path.join(os.path.dirname(__file__), "rifa_local.db")


def _usando_turso():
    return bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)


def _turso_http_url():
    # libsql://banco.turso.io  ->  https://banco.turso.io
    url = TURSO_DATABASE_URL
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    return url.rstrip("/") + "/v2/pipeline"


def _valor_turso(a):
    """Converte um valor Python para o formato de argumento esperado pela API do Turso.
    Importante: 'integer' vai como string, mas 'float' vai como número mesmo — misturar
    os dois formatos faz o Turso rejeitar o pedido e devolver erro 500."""
    if a is None:
        return {"type": "null"}
    if isinstance(a, bool):
        return {"type": "integer", "value": str(int(a))}
    if isinstance(a, int):
        return {"type": "integer", "value": str(a)}
    if isinstance(a, float):
        return {"type": "float", "value": a}
    return {"type": "text", "value": str(a)}


def _run_turso(sql, args=None):
    """Executa um único statement via API HTTP do Turso (compatível com o plano free do PythonAnywhere,
    que bloqueia conexões nativas libsql e só libera HTTP/HTTPS)."""
    args = args or []
    turso_args = [_valor_turso(a) for a in args]
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": turso_args}},
            {"type": "close"},
        ]
    }
    headers = {
        "Authorization": f"Bearer {TURSO_AUTH_TOKEN}",
        "Content-Type": "application/json",
    }
    resp = requests.post(_turso_http_url(), json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    result_block = data["results"][0]
    if result_block["type"] == "error":
        raise RuntimeError(result_block.get("error", {}).get("message", "Erro desconhecido no Turso"))

    result = result_block["response"]["result"]
    cols = [c["name"] for c in result.get("cols", [])]
    rows = []
    for raw_row in result.get("rows", []):
        row = {}
        for col, cell in zip(cols, raw_row):
            row[col] = cell.get("value") if cell else None
        rows.append(row)
    return rows


def _run_local(sql, args=None):
    args = args or []
    con = sqlite3.connect(LOCAL_DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(sql, args)
    if sql.strip().upper().startswith("SELECT"):
        rows = [dict(r) for r in cur.fetchall()]
    else:
        rows = []
        con.commit()
    con.close()
    return rows


def run(sql, args=None):
    if _usando_turso():
        return _run_turso(sql, args)
    return _run_local(sql, args)


def inicializar_banco():
    run("""
        CREATE TABLE IF NOT EXISTS rifa (
            id INTEGER PRIMARY KEY,
            titulo TEXT NOT NULL,
            finalidade TEXT,
            valor_numero REAL NOT NULL,
            qtd_numeros INTEGER NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            criado_em TEXT NOT NULL,
            sorteado_em TEXT,
            numero_sorteado INTEGER
        )
    """)
    run("""
        CREATE TABLE IF NOT EXISTS numero (
            id INTEGER PRIMARY KEY,
            rifa_id INTEGER NOT NULL,
            numero INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'disponivel',
            nome_comprador TEXT,
            telefone_comprador TEXT,
            reservado_em TEXT
        )
    """)
