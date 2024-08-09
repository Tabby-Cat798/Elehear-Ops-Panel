from flask import Flask, request, render_template, jsonify, session, redirect, flash, url_for, send_file
import mysql.connector
from mysql.connector import Error
import pandas as pd
import io


app = Flask(__name__)


app.secret_key = 'elevoc_ops'

users = {
    'elehear': 'ops'
}

# 替换为您的MySQL数据库连接信息
db_config = {
    'user': 'api',
    'password': '123456',
    'host': '8.217.85.94',
    'port': 3306,
    'database': 'api'
}


def get_data_from_db(table_name, month=None):
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        if month and month != 'all':
            start_date = f"{month}-01"
            query = f"SELECT * FROM {table_name} WHERE date >= %s AND date <= LAST_DAY(%s)"
            cursor.execute(query, (start_date, start_date))
            result = cursor.fetchall()
        else:
            query = f"SELECT * FROM {table_name}"
            cursor.execute(query)
            result = cursor.fetchall()
    except Error as e:
        print(f"Error: {e}")
        result = []
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
    return result


def calculate_column_sums(data, month):
    if not data:
        return []

    column_sums = [0] * (len(data[0]) - 1)  # 不计算日期列
    column_names = list(data[0].keys())
    ads_spend_index = column_names.index("ads_spend")
    ads_income_index = column_names.index("ads_income")
    roas_index = column_names.index("ROAS")

    for row in data:
        for i, (key, value) in enumerate(row.items()):
            if i == 0:
                continue  # 跳过日期列
            if isinstance(value, (int, float)):
                column_sums[i - 1] += value

    # 计算ROAS
    ads_spend_sum = column_sums[ads_spend_index - 1]
    ads_income_sum = column_sums[ads_income_index - 1]
    roas_value = ads_income_sum / ads_spend_sum if ads_spend_sum != 0 else 0
    column_sums[roas_index - 1] = round(roas_value, 2)
    if column_sums[9] == 0:
        rate = 0
    else:
        rate: float = column_sums[4] / column_sums[9]
    rate2 = round(rate, 4)
    conversion_rate = f"{rate2:.2%}"
    column_sums.append(conversion_rate)

    # 保留两位小数
    column_sums[:-1] = [round(sum, 2) for sum in column_sums[:-1]]
    return [month] + column_sums


def calculate_meta_sums(data, month):
    if not data:
        return []

    column_sums = [0] * (len(data[0]) - 1)  # 不计算日期列
    column_names = list(data[0].keys())
    ads_spend_index = column_names.index("spend")
    ads_income_index = column_names.index("income")
    ads_clicks_index = column_names.index("clicks")
    ads_amount_index = column_names.index("amount")
    roas_index = column_names.index("ROAS")
    cpc_index = column_names.index("CPC")
    cpa_index = column_names.index("CPA")

    for row in data:
        for i, (key, value) in enumerate(row.items()):
            if i == 0:
                continue  # 跳过日期列
            if isinstance(value, (int, float)):
                column_sums[i - 1] += value

    # 计算ROAS
    ads_spend_sum = column_sums[ads_spend_index - 1]
    ads_income_sum = column_sums[ads_income_index - 1]
    ads_clicks_sum = column_sums[ads_clicks_index - 1]
    ads_amount_sum = column_sums[ads_amount_index - 1]
    roas_value = ads_income_sum / ads_spend_sum if ads_spend_sum != 0 else 0
    cpc_value = ads_spend_sum / ads_clicks_sum if ads_clicks_sum != 0 else 0
    cpa_value = ads_spend_sum / ads_amount_sum if ads_amount_sum != 0 else 0
    column_sums[roas_index - 1] = round(roas_value, 2)
    column_sums[cpc_index - 1] = round(cpc_value, 2)
    column_sums[cpa_index - 1] = round(cpa_value, 2)

    column_sums[0] = ''  # 设置第一个元素为空字符串

    # 保留两位小数，但跳过第一个元素
    ads_sums = [round(sum, 2) if isinstance(sum, (int, float)) else sum for sum in column_sums]
    return [month] + ads_sums


def calculate_google_sums(data, month):
    if not data:
        return []

    column_sums = [0] * (len(data[0]) - 1)  # 不计算日期列
    column_names = list(data[0].keys())
    ads_spend_index = column_names.index("spend")
    ads_income_index = column_names.index("income")
    ads_clicks_index = column_names.index("clicks")
    ads_amount_index = column_names.index("amount")
    roas_index = column_names.index("ROAS")
    cpc_index = column_names.index("CPC")
    cpa_index = column_names.index("CPA")

    for row in data:
        for i, (key, value) in enumerate(row.items()):
            if i == 0:
                continue  # 跳过日期列
            if isinstance(value, (int, float)):
                column_sums[i - 1] += value

    # 计算ROAS
    ads_spend_sum = column_sums[ads_spend_index - 1]
    ads_income_sum = column_sums[ads_income_index - 1]
    ads_clicks_sum = column_sums[ads_clicks_index - 1]
    ads_amount_sum = column_sums[ads_amount_index - 1]
    roas_value = ads_income_sum / ads_spend_sum if ads_spend_sum != 0 else 0
    cpc_value = ads_spend_sum / ads_clicks_sum if ads_clicks_sum != 0 else 0
    cpa_value = ads_spend_sum / ads_amount_sum if ads_amount_sum != 0 else 0
    column_sums[roas_index - 1] = round(roas_value, 2)
    column_sums[cpc_index - 1] = round(cpc_value, 2)
    column_sums[cpa_index - 1] = round(cpa_value, 2)

    # 保留两位小数
    ads_sums = [round(sum, 2) for sum in column_sums]
    return [month] + ads_sums


@app.before_request
def before_request():
    protected_routes = ['home', 'index', 'ads_page', 'google_page']
    if 'username' not in session and request.endpoint in protected_routes:
        return redirect(url_for('login'))


@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('index'))
    else:
        return redirect(url_for('login'))


@app.route('/index')
def index():
    return render_template('index.html', username=session.get('username'), table_name='shopify_new')


@app.route('/get_data_by_month', methods=['GET'])
def get_data_by_month():
    month = request.args.get('month', 'all')
    data = get_data_from_db('shopify_new', month)
    column_sums = calculate_column_sums(data, month)
    # 获取列的顺序
    columns = list(data[0].keys()) if data else []
    # 确保数据可以被JSON化
    return jsonify({'data': data, 'column_sums': column_sums, 'columns': columns})


@app.route('/get_data_by_month_ads', methods=['GET'])
def get_data_by_month_ads():
    month = request.args.get('month', 'all')
    meta_data = get_data_from_db('meta', month)
    google_data = get_data_from_db('google', month)
    meta_sums = calculate_meta_sums(meta_data, month)
    google_sums = calculate_google_sums(google_data, month)
    google_columns = [col for col in google_data[0].keys() if col != 'date'] if google_data else []

    return jsonify({
        'meta_data': meta_data,
        'meta_sums': meta_sums,
        'meta_columns': list(meta_data[0].keys()) if meta_data else [],
        'google_data': google_data,
        'google_sums': google_sums,
        'google_columns': google_columns
    })


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users and users[username] == password:
            session['username'] = username
            flash('You were successfully logged in')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials. Please try again.')
    return render_template('login.html')


@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    flash('You were successfully logged out')
    return redirect(url_for('login'))


@app.route('/ads')
def ads_page():
    return render_template('ads.html', username=session.get('username'), table_name1='Meta', table_name2='Google')


@app.route('/google')
def google_page():
    google_data = get_data_from_db('google')
    return render_template('google.html', username=session['username'], data=google_data, table_name='Google')


@app.route('/export_ads_data', methods=['GET'])
def export_ads_data():
    month = request.args.get('month', 'all')

    meta_data = get_data_from_db('meta', month)
    google_data = get_data_from_db('google', month)

    # Convert data to DataFrames
    meta_df = pd.DataFrame(meta_data)
    google_df = pd.DataFrame(google_data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        meta_df.to_excel(writer, index=False, sheet_name='Meta')
        google_df.to_excel(writer, index=False, sheet_name='Google')

    output.seek(0)

    return send_file(output, as_attachment=True, download_name=f'ads_data_{month}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/export_shopify_data')
def export_shopify_data():
    month = request.args.get('month', 'all')
    data = get_data_from_db('shopify_new', month)
    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Shopify')

    output.seek(0)

    return send_file(output, as_attachment=True, download_name=f'shopify_data_{month}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


if __name__ == '__main__':
    # 运行Flask应用
    app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)

