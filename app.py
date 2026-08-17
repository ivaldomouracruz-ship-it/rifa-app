import os
import random
import secrets
import string
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import quote
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort

import db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "troque-esta-senha")
FUSO_BR = ZoneInfo("America/Sao_Paulo")


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
    linhas = db.run("SELECT * FROM rifa WHERE ativa = 1 ORDER BY id DESC LIMIT 1")
    return linhas[0] if linhas else None


def buscar_todas_rifas():
    return db.run("SELECT * FROM rifa ORDER BY id DESC")


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


def formatar_data_br(data_iso):
    if not data_iso:
        return None
    for formato_entrada, formato_saida in (
        ("%Y-%m-%dT%H:%M", "%d/%m/%Y às %Hh%M"),
        ("%Y-%m-%d", "%d/%m/%Y"),
    ):
        try:
            return datetime.strptime(data_iso, formato_entrada).strftime(formato_saida)
        except ValueError:
            continue
    return data_iso


def agora_br():
    return datetime.now(FUSO_BR).replace(tzinfo=None)


def data_sorteio_dt(rifa):
    """Converte o campo data_sorteio (texto) da rifa em datetime, ou None se ausente/ inválido."""
    valor = rifa.get("data_sorteio")
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def pode_sortear(rifa, numeros):
    if rifa.get("numero_sorteado"):
        return False
    dt = data_sorteio_dt(rifa)
    if dt is None or agora_br() < dt:
        return False
    return any(n["status"] == "pago" for n in numeros)


def buscar_ganhador(rifa, numeros):
    if not rifa.get("numero_sorteado"):
        return None
    vencedor = next((n for n in numeros if n["numero"] == rifa["numero_sorteado"]), None)
    if not vencedor:
        return None
    return {"numero": vencedor["numero"], "nome": vencedor["nome_comprador"]}


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
    return render_template(
        "rifa_publica.html", rifa=rifa, numeros=numeros, stats=stats,
        data_sorteio_br=formatar_data_br(rifa.get("data_sorteio")),
        ganhador=buscar_ganhador(rifa, numeros),
    )


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
    if rifa.get("numero_sorteado"):
        return jsonify({"ok": False, "erro": "Esta rifa já foi sorteada e não aceita mais reservas."}), 403

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

    mensagem_whatsapp = (
        f"🎟️ *{rifa['titulo']}*\n"
        f"{rifa['finalidade'] or ''}\n"
        f"Cada número: R$ {rifa['valor_numero']:.2f}".replace(".", ",") + "\n\n"
        f"Escolha seu número aqui: {link_publico}"
    )
    link_whatsapp = "https://wa.me/?text=" + quote(mensagem_whatsapp)

    outras_rifas = [r for r in buscar_todas_rifas() if r["id"] != rifa["id"]]

    return render_template(
        "admin_dashboard.html", rifa=rifa, numeros=numeros, stats=stats,
        link_publico=link_publico, link_whatsapp=link_whatsapp,
        data_sorteio_br=formatar_data_br(rifa.get("data_sorteio")),
        pode_sortear=pode_sortear(rifa, numeros),
        ganhador=buscar_ganhador(rifa, numeros),
        outras_rifas=outras_rifas,
    )


@app.route("/admin/criar", methods=["GET", "POST"])
@login_obrigatorio
def admin_criar():
    erro = None
    if request.method == "POST":
        titulo = (request.form.get("titulo") or "").strip()
        finalidade = (request.form.get("finalidade") or "").strip()
        chave_pix = (request.form.get("chave_pix") or "").strip()
        data_sorteio = (request.form.get("data_sorteio") or "").strip()
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
            try:
                db.run("UPDATE rifa SET ativa = 0")
                db.run(
                    """INSERT INTO rifa (titulo, finalidade, valor_numero, qtd_numeros, chave_pix, data_sorteio, slug, criado_em, ativa)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    [titulo, finalidade, valor_numero, qtd_numeros, chave_pix, data_sorteio, slug, datetime.now(timezone.utc).isoformat()],
                )
                rifa = buscar_rifa_por_slug(slug)
                for i in range(1, qtd_numeros + 1):
                    db.run(
                        "INSERT INTO numero (rifa_id, numero, status) VALUES (?, ?, 'disponivel')",
                        [rifa["id"], i],
                    )
                return redirect(url_for("admin_dashboard"))
            except Exception as e:
                erro = f"Não foi possível salvar no banco de dados: {e}"

    return render_template("admin_criar.html", erro=erro)


@app.route("/admin/numero/<int:numero_id>/marcar-pago", methods=["POST"])
@login_obrigatorio
def marcar_pago(numero_id):
    db.run("UPDATE numero SET status = 'pago' WHERE id = ?", [numero_id])
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/pix", methods=["POST"])
@login_obrigatorio
def definir_pix():
    rifa = buscar_rifa_ativa()
    if rifa:
        chave_pix = (request.form.get("chave_pix") or "").strip()
        db.run("UPDATE rifa SET chave_pix = ? WHERE id = ?", [chave_pix, rifa["id"]])
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/sorteio", methods=["POST"])
@login_obrigatorio
def definir_sorteio():
    rifa = buscar_rifa_ativa()
    if rifa:
        data_sorteio = (request.form.get("data_sorteio") or "").strip()
        db.run("UPDATE rifa SET data_sorteio = ? WHERE id = ?", [data_sorteio, rifa["id"]])
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/sortear", methods=["POST"])
@login_obrigatorio
def sortear():
    rifa = buscar_rifa_ativa()
    if not rifa:
        return redirect(url_for("admin_criar"))
    numeros = buscar_numeros(rifa["id"])
    if not pode_sortear(rifa, numeros):
        # Botão só fica habilitado quando as condições são satisfeitas; se chegou aqui
        # mesmo assim (ex.: F5 tardio), ignora silenciosamente e volta pro painel.
        return redirect(url_for("admin_dashboard"))

    pagos = [n for n in numeros if n["status"] == "pago"]
    sorteado = random.choice(pagos)
    db.run(
        "UPDATE rifa SET numero_sorteado = ?, sorteado_em = ? WHERE id = ?",
        [sorteado["numero"], datetime.now(timezone.utc).isoformat(), rifa["id"]],
    )
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


@app.route("/admin/ativar/<int:rifa_id>", methods=["POST"])
@login_obrigatorio
def ativar_rifa(rifa_id):
    db.run("UPDATE rifa SET ativa = 0")
    db.run("UPDATE rifa SET ativa = 1 WHERE id = ?", [rifa_id])
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
