from flask import Flask, render_template, redirect, url_for, request, session, flash, make_response
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from io import BytesIO
import qrcode
import base64
from datetime import datetime, timedelta
import crcmod

load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)

app.permanent_session_lifetime = timedelta(days=1)

def get_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"), cursor_factory=RealDictCursor)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/presentes')
def index_presentes():
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM presentes')
    presentes = c.fetchall()
    conn.close()
    return render_template('listapresentes.html', presentes=presentes)

@app.route('/confirmar-presenca', methods=['GET', 'POST'])
def confirmar_presenca():
    if request.method == 'POST':
        nome = request.form['nome']
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            INSERT INTO confirmacoes (nome, data)
            VALUES (%s, %s)
        ''', (nome, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        flash('✅ Presença confirmada com sucesso! Obrigado ❤️')
        return redirect(url_for('index'))
    return render_template('confirmar_presenca.html')

@app.route('/informacoes-gerais')
def informacoes_gerais():
    return render_template('informacoes_gerais.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        senha = request.form['senha']
        if senha == os.getenv("ADMIN_PASSWORD"):
            session.permanent = True
            session['logado'] = True
            return redirect(url_for('painel_admin'))
        else:
            flash('Senha incorreta!')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/admin/logout')
def logout():
    session.pop('logado', None)
    return redirect(url_for('index'))

@app.route('/admin/painel')
def painel_admin():
    if not session.get('logado'):
        return redirect(url_for('login'))
    return render_template('painel_admin.html')

@app.route('/admin/confirmacoes')
def ver_confirmacoes():
    if not session.get('logado'):
        return redirect(url_for('login'))
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM confirmacoes ORDER BY data DESC')
    confirmacoes = c.fetchall()
    conn.close()
    return render_template('confirmacoes.html', confirmacoes=confirmacoes)

@app.route('/admin/delete/<int:item_id>', methods=['POST'])
def deletar_presente(item_id):
    if not session.get('logado'):
        return redirect(url_for('login'))
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM contribuicoes WHERE presente_id = %s', (item_id,))
        total = c.fetchone()['count']
        if total > 0:
            flash('❌ Este presente já recebeu contribuições e não pode ser excluído.')
        else:
            c.execute('DELETE FROM presentes WHERE id = %s', (item_id,))
            flash('✅ Presente excluído com sucesso!')
        conn.commit()
        conn.close()
    except Exception as e:
        print("Erro:", e)
        flash('⚠️ Erro ao acessar o banco de dados.')
    return redirect(url_for('index_presentes'))

@app.route('/admin/deletar-confirmacao/<int:id>', methods=['POST'])
def deletar_confirmacao(id):
    if not session.get('logado'):
        return redirect(url_for('login'))
    conn = get_connection()
    c = conn.cursor()
    c.execute('DELETE FROM confirmacoes WHERE id = %s', (id,))
    conn.commit()
    conn.close()
    flash("❌ Confirmação excluída com sucesso!")
    return redirect(url_for('ver_confirmacoes'))

@app.route('/admin/add', methods=['GET', 'POST'])
def add_presente():
    if not session.get('logado'):
        flash("Você precisa estar logado como admin para acessar essa página.")
        return redirect(url_for('login'))
    if request.method == 'POST':
        nome = request.form['nome']
        valor_total = float(request.form['valor_total'])
        valor_cota = float(request.form['valor_cota'])
        cotas_total = int(valor_total / valor_cota)
        imagem_url = request.form.get('imagem_url')
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            INSERT INTO presentes (nome, valor_total, valor_cota, cotas_total, cotas_restantes, imagem_url)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (nome, valor_total, valor_cota, cotas_total, cotas_total, imagem_url))
        conn.commit()
        conn.close()
        flash('✅ Presente adicionado com sucesso!')
        return redirect(url_for('index_presentes'))
    return render_template('add.html')

@app.route('/contribuir/<int:item_id>', methods=['GET', 'POST'])
def contribuir(item_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM presentes WHERE id = %s', (item_id,))
    presente = c.fetchone()
    if request.method == 'POST':
        nome_convidado = request.form.get('nome_convidado', 'Anônimo')
        cotas_compradas = int(request.form['cotas'])
        novas_cotas = presente['cotas_restantes'] - cotas_compradas
        valor_total = cotas_compradas * presente['valor_cota']
        if novas_cotas >= 0:
            c.execute('UPDATE presentes SET cotas_restantes = %s WHERE id = %s', (novas_cotas, item_id))
            c.execute('''
                INSERT INTO contribuicoes (presente_id, nome_convidado, cotas, valor_total, data)
                VALUES (%s, %s, %s, %s, %s)
            ''', (item_id, nome_convidado, cotas_compradas, valor_total, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
        payload_pix = gerar_payload_pix(valor_total)
        qr = qrcode.make(payload_pix)
        buffer = BytesIO()
        qr.save(buffer, format="PNG")
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        conn.close()
        return render_template(
            'agradecimento.html',
            presente=presente,
            nome_convidado=nome_convidado,
            cotas=cotas_compradas,
            valor_pix=valor_total,
            img_base64=img_base64,
            payload_pix=payload_pix
        )
    conn.close()
    return render_template('contribuir.html', presente=presente)

def gerar_payload_pix(valor: float) -> str:
    pix_key = "43130257829"
    nome = "LUCAS HENRIQUE R RAUGI"
    cidade = "MATAO"
    valor_str = f"{valor:.2f}"
    gui = "BR.GOV.BCB.PIX"
    gui_field = f"00{len(gui):02d}{gui}"
    key_field = f"01{len(pix_key):02d}{pix_key}"
    merchant_account_info = f"{gui_field}{key_field}"
    mai_field = f"26{len(merchant_account_info):02d}{merchant_account_info}"
    nome = nome.strip()[:25]
    cidade = cidade.strip()[:15]
    payload_sem_crc = (
        "000201"
        + mai_field
        + "52040000"
        + "5303986"
        + f"54{len(valor_str):02d}{valor_str}"
        + "5802BR"
        + f"59{len(nome):02d}{nome}"
        + f"60{len(cidade):02d}{cidade}"
        + "62070503***"
        + "6304"
    )
    crc16 = crcmod.predefined.mkCrcFun('crc-ccitt-false')
    crc = format(crc16(payload_sem_crc.encode('utf-8')), '04X')
    return payload_sem_crc + crc

# Criação automática de tabelas no primeiro deploy
def criar_tabelas_postgres():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS presentes (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            valor_total REAL NOT NULL,
            valor_cota REAL NOT NULL,
            cotas_total INTEGER NOT NULL,
            cotas_restantes INTEGER NOT NULL,
            imagem_url TEXT
        );
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS contribuicoes (
            id SERIAL PRIMARY KEY,
            nome_convidado TEXT,
            presente_id INTEGER REFERENCES presentes(id),
            cotas INTEGER,
            valor_total REAL,
            data TEXT
        );
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS confirmacoes (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            data TEXT
        );
    ''')
    conn.commit()
    conn.close()

if __name__ == '__main__':
    criar_tabelas_postgres()  # Executa apenas uma vez no primeiro deploy
    app.run(debug=True)
