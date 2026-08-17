# App de Rifa Online

App Flask para gerenciar uma rifa: você define o título, a finalidade, a quantidade
de números e o valor de cada um. O app gera um link público para você mandar aos
seus contatos, com a cartela de números que se atualiza sozinha (a cada 5s) conforme
as pessoas vão escolhendo.

## Como funciona

- **Você (organizador)** faz login em `/login` com a senha definida em `ADMIN_PASSWORD`.
- Em `/admin/criar` você cria a rifa (título, finalidade, valor por número, quantidade).
- O painel `/admin` mostra o link público para compartilhar, estatísticas
  (disponíveis / reservados / pagos / valor arrecadado) e a lista de quem reservou
  cada número, com telefone.
- **Quem recebe o link** (`/r/<slug>`) vê a cartela, clica num número disponível,
  informa nome e telefone, e o número fica "reservado" (amarelo) na hora — para
  todo mundo que estiver com a página aberta, em até 5 segundos.
- Você confirma o pagamento (Pix, dinheiro, o que for) por fora do app e clica em
  **"Marcar pago"** no painel — o número fica "pago" (cinza) pra todo mundo.
- Se alguém reservar e não pagar, você pode **"Liberar"** o número de volta.
- **"Encerrar esta rifa"** apaga a rifa atual e libera a tela para criar a próxima
  (o app trabalha com uma rifa ativa por vez).

> Pagamento é confirmado manualmente pelo organizador — não há integração com
> gateway de pagamento nesta versão. Se depois você quiser automatizar via Pix,
> dá para adicionar.

## Rodando localmente

```bash
pip install -r requirements.txt
cp .env.example .env   # edite ADMIN_PASSWORD e SECRET_KEY
python app.py
```

Sem `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` definidos, o app usa automaticamente
um arquivo SQLite local (`rifa_local.db`) — bom para testar antes de subir pra produção.

## Deploy (mesmo padrão do app da LF / ExcellenceOS)

1. **Criar o banco no Turso** pelo painel web (app.turso.tech) — crie um banco novo
   e exclusivo para a rifa, pegue a `Database URL` e gere um `Auth Token`.
2. **Subir o código pro GitHub** (repositório novo, ex.: `rifa-app`).
3. **PythonAnywhere**: criar (ou usar) uma conta, ir em *Web → Add a new web app →
   Flask*, clonar o repositório via console Bash, e apontar o WSGI para `app.py`.
4. Como o plano grátis do PythonAnywhere bloqueia conexão nativa com o Turso,
   este app já fala com o Turso **pela API HTTP** (`db.py`, via `requests`) — não
   precisa da lib `libsql`, então não tem o problema de compatibilidade com
   Python 3.14 que apareceu no projeto da LF.
5. Como o plano grátis não tem a aba "Environment variables", crie um arquivo
   `.env`-like manualmente ou defina as variáveis direto no início do WSGI file
   do PythonAnywhere (os.environ["ADMIN_PASSWORD"] = "..." etc.), com:
   - `ADMIN_PASSWORD`
   - `SECRET_KEY`
   - `TURSO_DATABASE_URL`
   - `TURSO_AUTH_TOKEN`
6. Recarregar o app (botão **Reload** na aba Web do PythonAnywhere).

## Estrutura

```
app.py                  # rotas Flask (públicas + admin)
db.py                   # acesso ao banco (Turso via HTTP, ou sqlite local)
templates/               # telas (rifa pública, login, criar, painel admin)
static/style.css         # visual
```
