from flask import Flask, render_template, redirect, url_for, request, session, flash, make_response
import csv
import os
from dotenv import load_dotenv
import sqlite3
from pathlib import Path
import qrcode
import crcmod
from io import BytesIO
import base64
from datetime import datetime

load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)
DATABASE = 'db/presentes.db'

def init_db():
    Path('db').mkdir(exist_ok=True)
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS presentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            valor_total REAL NOT NULL,
            valor_cota REAL NOT NULL,
            cotas_total INTEGER NOT NULL,
            cotas_restantes INTEGER NOT NULL,
            imagem_url TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS contribuicoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_convidado TEXT,
            presente_id INTEGER,
            cotas INTEGER,
            valor_total REAL,
            data TEXT
        )
    ''')
    conn.commit()
    conn.close()

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        senha = request.form['senha']
        if senha == os.getenv("ADMIN_PASSWORD"):
            session['logado'] = True
            return redirect(url_for('ver_contribuicoes'))
        else:
            flash('Senha incorreta!')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/admin/logout')
def logout():
    session.pop('logado', None)
    return redirect(url_for('index'))

@app.route('/admin/delete/<int:item_id>', methods=['POST'])
def deletar_presente(item_id):
    if not session.get('logado'):
        return redirect(url_for('login'))

    try:
        with sqlite3.connect(DATABASE) as conn:
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM contribuicoes WHERE presente_id = ?', (item_id,))
            total = c.fetchone()[0]

            if total > 0:
                flash('❌ Este presente já recebeu contribuições e não pode ser excluído.')
            else:
                c.execute('DELETE FROM presentes WHERE id = ?', (item_id,))
                flash('✅ Presente excluído com sucesso!')

    except sqlite3.OperationalError:
        flash('⚠️ Banco de dados está em uso. Tente novamente em alguns segundos.')

    return redirect(url_for('index'))

@app.route('/')
def index():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT * FROM presentes')
    presentes = c.fetchall()
    conn.close()
    return render_template('index.html', presentes=presentes)

@app.route('/contribuir/<int:item_id>', methods=['GET', 'POST'])
def contribuir(item_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT * FROM presentes WHERE id = ?', (item_id,))
    presente = c.fetchone()

    if request.method == 'POST':
        nome_convidado = request.form.get('nome_convidado', 'Anônimo')
        cotas_compradas = int(request.form['cotas'])
        novas_cotas = presente[5] - cotas_compradas
        valor_total = cotas_compradas * presente[3]

        if novas_cotas >= 0:
            c.execute('UPDATE presentes SET cotas_restantes = ? WHERE id = ?', (novas_cotas, item_id))
            c.execute('''
                INSERT INTO contribuicoes (presente_id, nome_convidado, cotas, valor_total, data)
                VALUES (?, ?, ?, ?, ?)
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


@app.route('/admin/add', methods=['GET', 'POST'])
def add_presente():
    if request.method == 'POST':
        nome = request.form['nome']
        valor_total = float(request.form['valor_total'])
        valor_cota = float(request.form['valor_cota'])
        imagem_url = request.form.get('imagem_url', '')
        cotas_total = int(valor_total / valor_cota)

        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO presentes (nome, valor_total, valor_cota, cotas_total, cotas_restantes, imagem_url)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (nome, valor_total, valor_cota, cotas_total, cotas_total, imagem_url))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))
    return render_template('add.html')

@app.route('/admin/contribuicoes')
def ver_contribuicoes():
    if not session.get('logado'):
        return redirect(url_for('login'))
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    c.execute('''
        SELECT 
            contribuicoes.id,
            contribuicoes.nome_convidado,
            presentes.nome,
            contribuicoes.cotas,
            contribuicoes.valor_total,
            contribuicoes.data
        FROM contribuicoes
        JOIN presentes ON contribuicoes.presente_id = presentes.id
        ORDER BY contribuicoes.data DESC
    ''')

    contribuicoes = c.fetchall()
    conn.close()

    return render_template('contribuicoes.html', contribuicoes=contribuicoes)

@app.route('/admin/exportar')
def exportar_contribuicoes():
    if not session.get('logado'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    c.execute('''
        SELECT 
            contribuicoes.id,
            contribuicoes.nome_convidado,
            presentes.nome,
            contribuicoes.cotas,
            contribuicoes.valor_total,
            contribuicoes.data
        FROM contribuicoes
        JOIN presentes ON contribuicoes.presente_id = presentes.id
        ORDER BY contribuicoes.data DESC
    ''')

    contribuicoes = c.fetchall()
    conn.close()

    output = []
    header = ['ID', 'Convidado', 'Presente', 'Cotas', 'Valor (R$)', 'Data']
    output.append(header)

    for item in contribuicoes:
        output.append([
            item[0],
            item[1] or 'Anônimo',
            item[2],
            item[3],
            f"{item[4]:.2f}".replace('.', ','),
            item[5]
        ])

    response = make_response('\n'.join([','.join(map(str, row)) for row in output]))
    response.headers['Content-Disposition'] = 'attachment; filename=contribuicoes.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response

def gerar_payload_pix(valor: float) -> str:
    from crcmod.predefined import mkCrcFun

    pix_key = "43130257829"
    nome = "LUCAS HENRIQUE R RAUGI"
    cidade = "MATAO"
    valor_str = f"{valor:.2f}"

    # GUI: Banco Central (fixo)
    gui = "BR.GOV.BCB.PIX"
    gui_field = f"00{len(gui):02d}{gui}"
    key_field = f"01{len(pix_key):02d}{pix_key}"
    merchant_account_info = f"{gui_field}{key_field}"
    mai_field = f"26{len(merchant_account_info):02d}{merchant_account_info}"

    nome = nome.strip()[:25]
    cidade = cidade.strip()[:15]

    payload_sem_crc = (
        "000201"          # Payload Format Indicator
        + mai_field       # Merchant Account Info
        + "52040000"      # Merchant Category Code
        + "5303986"       # Currency
        + f"54{len(valor_str):02d}{valor_str}"  # Transaction amount
        + "5802BR"        # Country code
        + f"59{len(nome):02d}{nome}"            # Beneficiary name
        + f"60{len(cidade):02d}{cidade}"        # Beneficiary city
        + "62070503***"   # Additional data field
        + "6304"          # CRC16
    )

    # Calcula o CRC16 (CCITT-FALSE)
    crc16 = mkCrcFun('crc-ccitt-false')
    crc = format(crc16(payload_sem_crc.encode('utf-8')), '04X')

    return payload_sem_crc + crc



if __name__ == '__main__':
    init_db()
    app.run(debug=True)
else:
    init_db()
