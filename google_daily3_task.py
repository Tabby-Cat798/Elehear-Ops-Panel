import requests
from google.oauth2.credentials import Credentials
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta
from pytz import timezone
from redis import Redis
import json
import time

# MySQL 数据库连接信息
db_config = {
    'user': 'api',
    'password': '123456',
    'host': '8.217.85.94',
    'port': 3306,
    'database': 'api'
}

# Google Ads API 凭据
CLIENT_ID = '569002121483-ug18a0cdvbutaiepco9dkidbvmpe3mn9.apps.googleusercontent.com'
CLIENT_SECRET = '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'
REFRESH_TOKEN = '1//04R6NlPMD5cP6CgYIARAAGAQSNwF-L9IrV2q27PjZlTxNXy3Lpl84oU5hZzyWyFF-sZ4W-deWzYC0ymZREoJ3jrTyNgzPpV5yCwY'
DEVELOPER_TOKEN = 'badist6aJKKtiaEMy-nlOA'
LOGIN_CUSTOMER_ID = '4181460386'
TARGET_CUSTOMER_ID = '5542937178'  # 目标子账户ID

# 设置 Redis 连接
redis_client = Redis(host='localhost', port=6379, db=0, password='elevoc')

# 最大重试次数
MAX_RETRIES = 3
RETRY_DELAY = 5  # 重试间隔时间，单位为秒

def refresh_access_token(refresh_token):
    token_url = 'https://oauth2.googleapis.com/token'
    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
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

def get_google_ads_client(access_token):
    credentials = Credentials(
        token=access_token,
        refresh_token=REFRESH_TOKEN,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    )

    client = GoogleAdsClient(
        credentials=credentials,
        developer_token=DEVELOPER_TOKEN,
        login_customer_id=LOGIN_CUSTOMER_ID,
    )
    return client

def get_general_metrics(client, customer_id, start_date, end_date):
    try:
        ga_service = client.get_service("GoogleAdsService", version="v17")

        # 查询点击和成本
        query_clicks_cost = f"""
            SELECT 
                metrics.clicks,
                metrics.cost_micros
            FROM 
                customer 
            WHERE 
                segments.date BETWEEN '{start_date}' AND '{end_date}'
        """

        response_clicks_cost = ga_service.search(customer_id=customer_id, query=query_clicks_cost)

        clicks = 0
        total_cost_micros = 0

        for row in response_clicks_cost:
            clicks += row.metrics.clicks
            total_cost_micros += row.metrics.cost_micros

        cost = total_cost_micros / 1_000_000

        # 查询购买的转换数据
        query_conversions = f"""
            SELECT 
                segments.conversion_action_name,
                metrics.conversions_value,
                metrics.conversions
            FROM 
                customer 
            WHERE 
                segments.date BETWEEN '{start_date}' AND '{end_date}'
                AND segments.conversion_action_name = 'Purchase'
        """

        response_conversions = ga_service.search(customer_id=customer_id, query=query_conversions)

        total_conversions_value = 0
        total_conversions = 0

        for row in response_conversions:
            total_conversions_value += row.metrics.conversions_value
            total_conversions += row.metrics.conversions

        print(f"Total clicks from {start_date} to {end_date}: {clicks}")
        print(f"Total cost from {start_date} to {end_date}: {cost}")
        print(f"Total revenue from {start_date} to {end_date}: {total_conversions_value}")
        print(f"Total conversions (purchases) from {start_date} to {end_date}: {total_conversions}")
       
        return clicks, cost, total_conversions_value, total_conversions

    except GoogleAdsException as ex:
        print(f"Request failed with status {ex.error.code().name}")
        for error in ex.failure.errors:
            print(f"Error: {error.error_code} - {error.message}")
            if error.location:
                for field_path_element in error.location.field_path_elements:
                    print(f"  On field: {field_path_element.field_name}")
        return None, None, None, None

def store_data(connection, date, clicks, CPC, purchase_conversions, CPA, cost, purchase_conversions_value, ROAS):
    try:
        cursor = connection.cursor()

        # 将 CPC 和 CPA 保留两位小数
        CPC = round(CPC, 2)
        CPA = round(CPA, 2)
        cost = round(cost, 2)
        purchase_conversions_value = round(purchase_conversions_value, 2)

        query = "INSERT INTO google (date, clicks, CPC, amount, CPA, spend, income, ROAS) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        cursor.execute(query, (date, clicks, CPC, purchase_conversions, CPA, cost, purchase_conversions_value, ROAS))

        connection.commit()
        cursor.close()
    except Error as e:
        print(f"Error inserting data: {e}")

def perform_daily_task():
    # 尝试获取 Redis 锁，设置锁的过期时间为 60 秒
    if redis_client.set('google_daily3_task_lock', 'locked', ex=60, nx=True):
        try:
            retries = 0
            while retries < MAX_RETRIES:
                try:
                    access_token = refresh_access_token(REFRESH_TOKEN)
                    if not access_token:
                        raise Exception("Failed to refresh access token")

                    client = get_google_ads_client(access_token)

                    connection = mysql.connector.connect(**db_config)
                    cursor = connection.cursor()

                    # 获取当前北京时间并转换为美国东部时间
                    now_beijing = datetime.now(timezone('Asia/Shanghai'))
                    current_day_us = now_beijing.astimezone(timezone('America/New_York'))

                    # 获取前三天的起始时间和结束时间
                    for i in range(3, 0, -1):
                        day_us = current_day_us - timedelta(days=i)
                        start_date_us = day_us.replace(hour=0, minute=0, second=0, microsecond=0)
                        end_date_us = day_us.replace(hour=23, minute=59, second=59, microsecond=999999)

                        # 转换为字符串格式
                        start_date = start_date_us.strftime('%Y-%m-%d')
                        end_date = end_date_us.strftime('%Y-%m-%d')

                        print(f"Fetching data from {start_date} to {end_date} (US Eastern Time)")

                        # 检查缓存中是否已有数据
                        cache_key = f'google_data_{start_date}'
                        cached_data = redis_client.get(cache_key)

                        if cached_data:
                            print("Using cached data")
                            data = json.loads(cached_data)
                        else:
                            clicks, cost, purchase_conversions_value, purchase_conversions = get_general_metrics(client, TARGET_CUSTOMER_ID, start_date, end_date)
                            if clicks is None or cost is None or purchase_conversions_value is None or purchase_conversions is None:
                                raise Exception(f"Error fetching data for {start_date}")

                            data = {
                                'clicks': clicks,
                                'cost': cost,
                                'purchase_conversions_value': purchase_conversions_value,
                                'purchase_conversions': purchase_conversions
                            }
                            redis_client.setex(cache_key, timedelta(minutes=10), json.dumps(data))  # 缓存数据10分钟

                        clicks = data['clicks']
                        cost = data['cost']
                        purchase_conversions_value = data['purchase_conversions_value']
                        purchase_conversions = data['purchase_conversions']

                        CPC = 0 if clicks == 0 else cost / clicks
                        CPA = 0 if purchase_conversions == 0 else cost / purchase_conversions
                        ROAS = 0 if cost == 0 else purchase_conversions_value / cost
                        ROAS = round(ROAS, 2)

                        # 删除现有当天数据
                        delete_query = "DELETE FROM google WHERE date = %s"
                        cursor.execute(delete_query, (start_date,))

                        # 插入数据到数据库
                        store_data(connection, start_date, clicks, CPC, purchase_conversions, CPA, cost, purchase_conversions_value, ROAS)

                        print(f"Data for {start_date} inserted successfully.")

                    break  # 成功执行后退出重试循环

                except Exception as e:
                    print(f"Error performing daily task: {e}")
                    retries += 1
                    time.sleep(RETRY_DELAY)  # 等待一段时间后重试

        finally:
            # 释放锁
            redis_client.delete('google_daily_task_lock')
    else:
        print("Could not acquire lock, another instance may be running.")

if __name__ == "__main__":
    perform_daily_task()
