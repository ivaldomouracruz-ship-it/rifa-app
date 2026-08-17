import os
import secrets
import string
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort

import db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "troque-esta-senha")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def login_obrigatorio(f):
    @wraps(f)
    def decorado(*args, **kwargs):
        if not session.get("admin_logado"):
            return redirect(url_for("login", proximo=request.path))
        return f(*args, **kwargs)
    return decorado


def gerar_slug():
    alfabeto = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(8))


def buscar_rifa_ativa():
    linhas = db.run("SELECT * FROM rifa ORDER BY id DESC LIMIT 1")
    return linhas[0] if linhas else None


def buscar_rifa_por_slug(slug):
    linhas = db.run("SELECT * FROM rifa WHERE slug = ?", [slug])
    return linhas[0] if linhas else None


def buscar_numeros(rifa_id):
    return db.run(
        "SELECT * FROM numero WHERE rifa_id = ? ORDER BY numero ASC", [rifa_id]
    )


def estatisticas(rifa, numeros):
    total = len(numeros)
    pagos = [n for n in numeros if n["status"] == "pago"]
    reservados = [n for n in numeros if n["status"] == "reservado"]
    disponiveis = [n for n in numeros if n["status"] == "disponivel"]
    valor = float(rifa["valor_numero"])
    return {
        "total": total,
        "pagos": len(pagos),
        "reservados": len(reservados),
        "disponiveis": len(disponiveis),
        "arrecadado": len(pagos) * valor,
        "potencial": total * valor,
    }


# ---------------------------------------------------------------------------
# Rotas públicas
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    rifa = buscar_rifa_ativa()
    if not rifa:
        return redirect(url_for("login"))
    return redirect(url_for("rifa_publica", slug=rifa["slug"]))


@app.route("/r/<slug>")
def rifa_publica(slug):
    rifa = buscar_rifa_por_slug(slug)
    if not rifa:
        abort(404)
    numeros = buscar_numeros(rifa["id"])
    stats = estatisticas(rifa, numeros)
    return render_template("rifa_publica.html", rifa=rifa, numeros=numeros, stats=stats)


@app.route("/api/r/<slug>/status")
def api_status(slug):
    rifa = buscar_rifa_por_slug(slug)
    if not rifa:
        abort(404)
    numeros = buscar_numeros(rifa["id"])
    return jsonify({
        "numeros": [
            {"numero": n["numero"], "status": n["status"]} for n in numeros
        ],
        "stats": estatisticas(rifa, numeros),
    })


@app.route("/api/r/<slug>/reservar", methods=["POST"])
def api_reservar(slug):
    rifa = buscar_rifa_por_slug(slug)
    if not rifa:
        abort(404)

    dados = request.get_json(force=True, silent=True) or {}
    numero = dados.get("numero")
    nome = (dados.get("nome") or "").strip()
    telefone = (dados.get("telefone") or "").strip()

    if not numero or not nome or not telefone:
        return jsonify({"ok": False, "erro": "Preencha nome, telefone e escolha um número."}), 400

    linhas = db.run(
        "SELECT * FROM numero WHERE rifa_id = ? AND numero = ?", [rifa["id"], numero]
    )
    if not linhas:
        return jsonify({"ok": False, "erro": "Número inválido."}), 404

    alvo = linhas[0]
    if alvo["status"] != "disponivel":
        return jsonify({"ok": False, "erro": "Esse número já foi escolhido. Atualize a página."}), 409

    db.run(
        """UPDATE numero SET status = 'reservado', nome_comprador = ?,
           telefone_comprador = ?, reservado_em = ? WHERE id = ?""",
        [nome, telefone, datetime.now(timezone.utc).isoformat(), alvo["id"]],
    )
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Rotas admin
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        senha = request.form.get("senha", "")
        if secrets.compare_digest(senha, ADMIN_PASSWORD):
            session["admin_logado"] = True
            proximo = request.args.get("proximo") or url_for("admin_dashboard")
            return redirect(proximo)
        erro = "Senha incorreta."
    return render_template("login.html", erro=erro)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin")
@login_obrigatorio
def admin_dashboard():
    rifa = buscar_rifa_ativa()
    if not rifa:
        return redirect(url_for("admin_criar"))
    numeros = buscar_numeros(rifa["id"])
    stats = estatisticas(rifa, numeros)
    link_publico = url_for("rifa_publica", slug=rifa["slug"], _external=True)
    return render_template(
        "admin_dashboard.html", rifa=rifa, numeros=numeros, stats=stats, link_publico=link_publico
    )


@app.route("/admin/criar", methods=["GET", "POST"])
@login_obrigatorio
def admin_criar():
    erro = None
    if request.method == "POST":
        titulo = (request.form.get("titulo") or "").strip()
        finalidade = (request.form.get("finalidade") or "").strip()
        valor_numero = request.form.get("valor_numero", "").replace(",", ".")
        qtd_numeros = request.form.get("qtd_numeros", "")

        try:
            valor_numero = float(valor_numero)
            qtd_numeros = int(qtd_numeros)
            if valor_numero <= 0 or qtd_numeros <= 0 or qtd_numeros > 5000:
                raise ValueError
        except ValueError:
            erro = "Verifique o valor por número e a quantidade de números."

        if not titulo:
            erro = "Informe o título da rifa."

        if not erro:
            slug = gerar_slug()
            db.run(
                """INSERT INTO rifa (titulo, finalidade, valor_numero, qtd_numeros, slug, criado_em)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [titulo, finalidade, valor_numero, qtd_numeros, slug, datetime.now(timezone.utc).isoformat()],
            )
            rifa = buscar_rifa_por_slug(slug)
            for i in range(1, qtd_numeros + 1):
                db.run(
                    "INSERT INTO numero (rifa_id, numero, status) VALUES (?, ?, 'disponivel')",
                    [rifa["id"], i],
                )
            return redirect(url_for("admin_dashboard"))

    return render_template("admin_criar.html", erro=erro)


@app.route("/admin/numero/<int:numero_id>/marcar-pago", methods=["POST"])
@login_obrigatorio
def marcar_pago(numero_id):
    db.run("UPDATE numero SET status = 'pago' WHERE id = ?", [numero_id])
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/numero/<int:numero_id>/liberar", methods=["POST"])
@login_obrigatorio
def liberar_numero(numero_id):
    db.run(
        """UPDATE numero SET status = 'disponivel', nome_comprador = NULL,
           telefone_comprador = NULL, reservado_em = NULL WHERE id = ?""",
        [numero_id],
    )
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/encerrar", methods=["POST"])
@login_obrigatorio
def encerrar_rifa():
    rifa = buscar_rifa_ativa()
    if rifa:
        db.run("DELETE FROM numero WHERE rifa_id = ?", [rifa["id"]])
        db.run("DELETE FROM rifa WHERE id = ?", [rifa["id"]])
    return redirect(url_for("admin_criar"))


# ---------------------------------------------------------------------------

with app.app_context():
    db.inicializar_banco()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
