import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta
from pytz import timezone
from redis import Redis
import requests
import json
import time

# 替换为您的MySQL数据库连接信息
db_config = {
    'user': 'api',
    'password': '123456',
    'host': '8.217.85.94',
    'port': 3306,
    'database': 'api'
}

access_token = 'EAAMq3IRpPlsBO3zceqWxfEEU8XfMccLDuUN3VLWNTfABZA22yY1gqkQpCY5FPjAxWaDdkolC1wBqSGOL4xlLY7yig0b25Xy0E8RoXGXZCeGK5nnQiq06ZCe2tdXVZCCo9J4MIaUWhzaUsNZCOKct8T35ZBsZBvzNJeFVZAy70r7S9SzCH0foNOGoxr2F0YsFqnC8UVZAwJfmGLNB1xdRHHDiM2s3Q'
# 你的广告账户ID
ad_account_id = 'act_249116311346514'
# 定义API端点
url = f"https://graph.facebook.com/v20.0/{ad_account_id}/insights"

# 设定时区
us_eastern_tz = timezone('America/New_York')
beijing_tz = timezone('Asia/Shanghai')

# 设置 Redis 连接
redis_client = Redis(host='localhost', port=6379, db=0, password='elevoc')

# 最大重试次数
MAX_RETRIES = 3
RETRY_DELAY = 5  # 重试间隔时间，单位为秒

def perform_daily_task():
    # 尝试获取 Redis 锁，设置锁的过期时间为 60 秒
    if redis_client.set('meta_daily_task_lock', 'locked', ex=60, nx=True):
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

                    print(f"Fetching data from {start_date} to {end_date} (US Eastern Time)")

                    params = {
                        'fields': 'spend,clicks,actions,action_values,cpm',
                        'time_range': json.dumps({'since': start_date, 'until': end_date}),
                        'time_zone': 'America/New_York',
                        'level': 'account',
                        'access_token': access_token
                    }

                    # 检查缓存中是否已有数据
                    cache_key = f'meta_data_{start_date}'
                    cached_data = redis_client.get(cache_key)

                    if cached_data:
                        print("Using cached data")
                        data = json.loads(cached_data)
                    else:
                        response = requests.get(url, params=params)
                        # 解析响应数据
                        if response.status_code == 200:
                            data = response.json()
                            redis_client.setex(cache_key, timedelta(minutes=10), json.dumps(data))  # 缓存数据10分钟
                        else:
                            raise Exception(f"Error fetching data for {start_date}: {response.status_code}")

                    insights = data.get('data', [])
                    if not insights:
                        spend = clicks = cpm = CPC = amount = CPA = income = ROAS = 0
                        print(f"No data found for {start_date}")
                    else:
                        spend = float(insights[0].get('spend', 0))
                        clicks = int(insights[0].get('clicks', 0))
                        cpm = float(insights[0].get('cpm', 0))
                        cpm = round(cpm, 2)

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

                        CPC = 0 if clicks == 0 else spend / clicks
                        CPA = 0 if amount == 0 else spend / amount
                        ROAS = 0 if spend == 0 else income / spend
                        CPC = round(CPC, 2)
                        CPA = round(CPA, 2)
                        ROAS = round(ROAS, 2)

                    # 删除现有当天数据
                    delete_query = "DELETE FROM meta WHERE date = %s"
                    cursor.execute(delete_query, (start_date,))

                    # 插入数据到数据库
                    query = "INSERT INTO meta (date, CPM, clicks, CPC, amount, CPA, spend, income, ROAS) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    cursor.execute(query, (start_date, cpm, clicks, CPC, amount, CPA, spend, income, ROAS))

                    connection.commit()
                    cursor.close()
                    connection.close()

                    print(f"Data for {start_date} inserted successfully.")
                    break  # 成功执行后退出重试循环

                except Error as e:
                    print(f"Error performing daily task: {e}")
                    retries += 1
                    time.sleep(RETRY_DELAY)  # 等待一段时间后重试

        finally:
            # 释放锁
            redis_client.delete('meta_daily_task_lock')
    else:
        print("Could not acquire lock, another instance may be running.")

if __name__ == "__main__":
    perform_daily_task()