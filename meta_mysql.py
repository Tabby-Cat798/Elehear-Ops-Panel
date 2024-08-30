import mysql.connector
from mysql.connector import Error
import json
import requests
from datetime import datetime, timedelta
from pytz import timezone, utc

# 数据库配置
db_config = {
    'user': '******',
    'password': '******',
    'host': '******',
    'port': 3306,
    'database': '******'
}

# 你的访问令牌
access_token = '********************************************************************'
# 你的广告账户ID
ad_account_id = '********************************************************************'
# 定义API端点
url = f"https://graph.facebook.com/v20.0/{ad_account_id}/insights"

def store_sales_data(connection, date, cpm, clicks, CPC, amount, CPA, spend, income, ROAS):
    try:
        cursor = connection.cursor()
        delete_query = "DELETE FROM meta WHERE date = %s"
        cursor.execute(delete_query, (date,))

        # 插入数据的SQL语句
        query = "INSERT INTO meta (date, cpm, clicks, CPC, amount, CPA, spend, income, ROAS) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        cursor.execute(query, (date, cpm, clicks, CPC, amount, CPA, spend, income, ROAS))

        connection.commit()
        cursor.close()
    except Error as e:
        print(f"Error inserting data: {e}")

def get_data(YY, MM, DD):
    try:
        connection = mysql.connector.connect(**db_config)
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return

    while DD <= 30:
        start_date = f'{YY}-{MM:02d}-{DD:02d}'
        end_date = f'{YY}-{MM:02d}-{DD:02d}'
        # 定义查询参数
        params = {
            'fields': 'spend,clicks,actions,action_values,cpm',
            'time_range': json.dumps({'since': start_date, 'until': end_date}),
            'level': 'account',
            'access_token': access_token
        }

        # 发送GET请求
        response = requests.get(url, params=params)

        # 解析响应数据
        if response.status_code == 200:
            data = response.json()
            insights = data.get('data', [])

            if not insights:
                spend = clicks = cpm = CPC = amount = CPA = spend = income = ROAS = 0
                print(f"No data found for {start_date}")
            else:
                spend = float(insights[0].get('spend', 0))
                clicks = int(insights[0].get('clicks', 0))
                cpm = float(insights[0].get('cpm', 0))

                amount = 0
                income = 0.0

                actions = insights[0].get('actions', [])
                action_values = insights[0].get('action_values', [])

                for action in actions:
                    if action['action_type'] == 'purchase':
                        amount = int(action.get('value', 0))

                for action_value in action_values:
                    if action_value['action_type'] == 'purchase':
                        income = float(action_value.get('value', 0))

                if clicks == 0:
                    CPC = 0
                else:
                    CPC = spend / clicks

                if amount == 0:
                    CPA = 0
                else:
                    CPA = spend / amount

                if spend == 0:
                    ROAS = 0
                else:
                    ROAS = income / spend
                CPC = round(CPC, 2)
                CPA = round(CPA, 2)
                ROAS = round(ROAS, 2)
                cpm = round(cpm, 2)

        else:
            spend = clicks = cpm = CPC = amount = CPA = spend = income = ROAS = 0
            print(f"Error fetching data for {start_date}: {response.status_code}")

        # 存储数据
        store_sales_data(connection, start_date, cpm, clicks, CPC, amount, CPA, spend, income, ROAS)
        DD += 1

    connection.close()

# 调用函数
get_data(2024, 8, 1)
