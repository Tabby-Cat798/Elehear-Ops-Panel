import requests
from datetime import datetime, timedelta
from pytz import timezone, utc
import mysql.connector
from mysql.connector import Error
import redis
import json
import time
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest

# MySQL数据库配置
db_config = {
    'user': 'api',
    'password': '123456',
    'host': '8.217.85.94',
    'port': 3306,
    'database': 'api'
}

# Redis配置
redis_host = 'localhost'
redis_port = 6379
redis_password = 'elevoc'

# Shopify API 配置
ACCESS_TOKEN = "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"
API_KEY = "06c7b3414081441a3b83c15cc78ac421"
PASSWORD = "fe5a9f46c6d60bcc781af8059bcda5e7"
SHOP_NAME = "elehear-store"
GRAPHQL_URL = f'https://{API_KEY}:{PASSWORD}@{SHOP_NAME}.myshopify.com/admin/api/2023-07/graphql.json'

# Google OAuth 2.0配置
CLIENT_ID = '569002121483-ug18a0cdvbutaiepco9dkidbvmpe3mn9.apps.googleusercontent.com'
CLIENT_SECRET = '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'
REFRESH_TOKEN = '1//04R6NlPMD5cP6CgYIARAAGAQSNwF-L9IrV2q27PjZlTxNXy3Lpl84oU5hZzyWyFF-sZ4W-deWzYC0ymZREoJ3jrTyNgzPpV5yCwY'
TOKEN_URI = 'https://oauth2.googleapis.com/token'
PROPERTY_ID = '402334651'  # 替换为你的GA4 Property ID

# 设定时区
us_eastern_tz = timezone('America/New_York')
beijing_tz = timezone('Asia/Shanghai')
utc_tz = utc

# 最大重试次数
MAX_RETRIES = 3
RETRY_DELAY = 5  # 重试间隔时间，单位为秒

def refresh_access_token(client_id, client_secret, refresh_token):
    token_url = TOKEN_URI
    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    }

    response = requests.post(token_url, data=data)

    if response.status_code == 200:
        token_info = response.json()
        access_token = token_info['access_token']
        expires_in = token_info['expires_in']
        print(f"New Access Token: {access_token}")
        print(f"Expires in: {expires_in} seconds")
        return access_token
    else:
        print(f"Failed to refresh access token: {response.status_code}")
        print(response.json())
        return None

def fetch_shopify_data(start_date_utc, end_date_utc):
    # GraphQL 查询
    query = f"""
    {{
      orders(query: "created_at:>={start_date_utc} created_at:<={end_date_utc} financial_status:paid OR financial_status:partially_refunded OR financial_status:refunded", first: 100) {{
        edges {{
          node {{
            id
            currentTotalPriceSet {{
              shopMoney {{
                amount
              }}
            }}
            lineItems(first: 100) {{
              edges {{
                node {{
                  title
                  quantity
                }}
              }}
            }}
            refunds {{
              refundLineItems(first: 100) {{
                edges {{
                  node {{
                    subtotalSet {{
                      shopMoney {{
                        amount
                      }}
                    }}
                    quantity
                  }}
                }}
              }}
            }}
          }}
        }}
      }}
    }}
    """

    # 发送请求
    headers = {
        'Content-Type': 'application/json',
        'X-Shopify-Access-Token': ACCESS_TOKEN
    }

    response = requests.post(GRAPHQL_URL, json={'query': query}, headers=headers)

    if response.status_code == 200:
        data = response.json()
        return data
    else:
        print(f"Query failed to run by returning code of {response.status_code}. {response.text}")
        return None

def process_shopify_data(data):
    if 'data' in data:
        total_sales = 0.0
        alpha_pro_sales = 0.0
        total_quantity = 0
        total_order_count = 0
        total_refund_quantity = 0

        accessory_titles = [
            "Dry Box for ELEHEAR Alpha Series",
            "Single-layer Closed Ear Domes/Caps for ELEHEAR Alpha Series",
            "Double-layer Closed Ear Domes/Caps for ELEHEAR Alpha Series",
            "Wax Cap Tool for ELEHEAR Alpha Series *4",
            "Wireless Charger for ELEHEAR Alpha Series"
        ]
        accessory_quantities = {title: 0 for title in accessory_titles}
        product_order_counts = {}

        for edge in data['data']['orders']['edges']:
            order = edge['node']
            
            # 跳过包含"Shipping Fee"的订单
            contains_shipping_fee = any(item['node']['title'] == 'Shipping Fee' for item in order['lineItems']['edges'])
            if contains_shipping_fee:
                continue
            
            total_order_count += 1

            current_total_price = float(order['currentTotalPriceSet']['shopMoney']['amount'])
            refund_total = 0.0
            if order['refunds']:
                for refund in order['refunds']:
                    for refund_edge in refund['refundLineItems']['edges']:
                        refund_node = refund_edge['node']
                        refund_total += float(refund_node['subtotalSet']['shopMoney']['amount'])
                        if 'quantity' in refund_node:
                            total_refund_quantity += int(refund_node['quantity'])

            net_sale = current_total_price
            total_sales += net_sale

            for item in order['lineItems']['edges']:
                title = item['node']['title']
                quantity = int(item['node']['quantity'])
                if title == 'Alpha Pro' or title == 'Alpha Pro Ultimate Kit' or title == 'Alpha':
                    total_quantity += quantity
                    alpha_pro_sales += net_sale  # 根据支付金额计算 Alpha Pro 销售额
                if title in accessory_titles:
                    accessory_quantities[title] += quantity
                if title in product_order_counts:
                    product_order_counts[title] += 1
                else:
                    product_order_counts[title] = 1

        return {
            'total_sales': total_sales,
            'alpha_pro_sales': alpha_pro_sales,
            'total_quantity': total_quantity,
            'total_order_count': total_order_count,
            'total_refund_quantity': total_refund_quantity,
            'accessory_quantities': accessory_quantities,
            'product_order_counts': product_order_counts
        }
    else:
        print("The 'data' field is missing in the response.")
        return None

def fetch_traffic_data(credentials, start_date, end_date):
    client = BetaAnalyticsDataClient(credentials=credentials)

    # 构建请求体并获取数据
    request = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        date_ranges=[{"start_date": start_date, "end_date": end_date}],
        dimensions=[{"name": "sourceMedium"}],  # 增加sourceMedium维度以便进行筛选
        metrics=[{"name": "activeUsers"}]
    )
    response = client.run_report(request)

    total_active_users = 0

    for row in response.rows:
        source_medium = row.dimension_values[0].value
        active_users = int(row.metric_values[0].value)
        # 筛选掉"not set"的来源
        # if source_medium != "(not set)":
        # if source_medium != "google / cpc":
        total_active_users += active_users

    return total_active_users

def fetch_ads_data(connection, date):
    try:
        cursor = connection.cursor()

        # 获取meta表中的数据
        cursor.execute("SELECT spend, income, amount FROM meta WHERE date = %s", (date,))
        meta_data = cursor.fetchone()
        meta_spend = meta_data[0] if meta_data else 0
        meta_income = meta_data[1] if meta_data else 0
        meta_amount = meta_data[2] if meta_data else 0

        # 获取google表中的数据
        cursor.execute("SELECT spend, income, amount FROM google WHERE date = %s", (date,))
        google_data = cursor.fetchone()
        google_spend = google_data[0] if google_data else 0
        google_income = google_data[1] if google_data else 0
        google_amount = google_data[2] if google_data else 0

        ads_spend = meta_spend + google_spend
        ads_income = meta_income + google_income
        ads_amount = meta_amount + google_amount
        ROAS = ads_income / ads_spend if ads_spend != 0 else 0
        ROAS = round(ROAS, 2)

        return ads_spend, ads_income, ads_amount, ROAS
    except Error as e:
        print(f"Error fetching ads data: {e}")
        return 0, 0, 0, 0

def store_sales_data(connection, start_date, date, total_sales, alpha_pro_sales, alpha_pro_orders, accessory_orders, total_orders, total_traffic, ads_spend, ads_income, ads_amount, ROAS):
    try:
        cursor = connection.cursor()
        delete_query = "DELETE FROM shopify_new WHERE date = %s"
        cursor.execute(delete_query, (start_date,))
        query = "INSERT INTO shopify_new (date, total_sales, AlphaPro_sales, AlphaPro_orders, Accessory_orders, total_orders, total_traffic, ads_spend, ads_income, ads_amount, ROAS) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        cursor.execute(query, (date, total_sales, alpha_pro_sales, alpha_pro_orders, accessory_orders, total_orders, total_traffic, ads_spend, ads_income, ads_amount, ROAS))
        connection.commit()
        cursor.close()
    except Error as e:
        print(f"Error inserting data: {e}")

def fetch_and_store_data():
    # 连接Redis
    redis_client = redis.StrictRedis(host=redis_host, port=redis_port, password=redis_password, decode_responses=True)

    # 获取锁，防止多次运行任务
    if redis_client.set('shopify_daily_task_lock', 'locked', ex=60, nx=True):
        try:
            retries = 0
            while retries < MAX_RETRIES:
                try:
                    connection = mysql.connector.connect(**db_config)
                    cursor = connection.cursor()

                    # 获取当前北京时间并转换为当天的美国东部时间
                    now_beijing = datetime.now(beijing_tz)
                    current_day_us = now_beijing.astimezone(us_eastern_tz)

                    # 获取当天的起始时间和结束时间
                    start_date_us = current_day_us.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date_us = current_day_us.replace(hour=23, minute=59, second=59, microsecond=999999)

                    # 转换为字符串格式
                    start_date = start_date_us.strftime('%Y-%m-%d')
                    end_date = end_date_us.strftime('%Y-%m-%d')
                    
                    # 转换为 UTC 格式
                    start_date_utc = start_date_us.astimezone(utc_tz).isoformat()
                    end_date_utc = end_date_us.astimezone(utc_tz).isoformat()

                    print(f"Fetching data from {start_date} to {end_date} (US Eastern Time)")

                    # 检查缓存中是否已有数据
                    cache_key = f'shopify_data_{start_date}'
                    cached_data = redis_client.get(cache_key)

                    if cached_data:
                        print("Using cached data")
                        data = json.loads(cached_data)
                    else:
                        data = fetch_shopify_data(start_date_utc, end_date_utc)
                        if data:
                            redis_client.setex(cache_key, timedelta(minutes=10), json.dumps(data))  # 缓存数据10分钟
                        else:
                            raise Exception("Failed to fetch Shopify data")

                    processed_data = process_shopify_data(data)
                    if processed_data:
                        access_token = refresh_access_token(CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)
                        if not access_token:
                            raise Exception("Failed to obtain access token")

                        credentials = Credentials(
                            token=access_token,
                            refresh_token=REFRESH_TOKEN,
                            token_uri=TOKEN_URI,
                            client_id=CLIENT_ID,
                            client_secret=CLIENT_SECRET
                        )

                        total_traffic = fetch_traffic_data(credentials, start_date, end_date)
                        ads_spend, ads_income, ads_amount, ROAS = fetch_ads_data(connection, start_date)
                        
                        date = f'{start_date_us.year}-{start_date_us.month:02d}-{start_date_us.day:02d}'
                        store_sales_data(connection, start_date, date, processed_data['total_sales'], processed_data['alpha_pro_sales'],
                                         processed_data['total_quantity'], sum(processed_data['accessory_quantities'].values()),
                                         processed_data['total_order_count'], total_traffic, ads_spend, ads_income, ads_amount, ROAS)

                        print(f"Data for {date} inserted successfully.")
                        break  # 成功执行后退出重试循环

                except (Error, Exception) as e:
                    print(f"Error performing daily task: {e}")
                    retries += 1
                    time.sleep(RETRY_DELAY)  # 等待一段时间后重试

        finally:
            # 释放锁
            redis_client.delete('shopify_daily_task_lock')
    else:
        print("Could not acquire lock, another instance may be running.")

if __name__ == "__main__":
    fetch_and_store_data()
