import requests
from google.oauth2.credentials import Credentials
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta

db_config = {
    'user': 'api',
    'password': '123456',
    'host': '8.217.85.94',
    'port': 3306,
    'database': 'api'
}
# 设置查询日期为全局变量
QUERY_DATE = '2024-07-07'

# 替换为你的信息
CLIENT_ID = '569002121483-ug18a0cdvbutaiepco9dkidbvmpe3mn9.apps.googleusercontent.com'
CLIENT_SECRET = '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'
REFRESH_TOKEN = '1//04R6NlPMD5cP6CgYIARAAGAQSNwF-L9IrV2q27PjZlTxNXy3Lpl84oU5hZzyWyFF-sZ4W-deWzYC0ymZREoJ3jrTyNgzPpV5yCwY'
DEVELOPER_TOKEN = 'badist6aJKKtiaEMy-nlOA'
LOGIN_CUSTOMER_ID = '4181460386'
TARGET_CUSTOMER_ID = '5542937178'  # 目标子账户ID


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


def get_general_metrics(client, customer_id):
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
                segments.date = '{QUERY_DATE}'
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
                segments.date = '{QUERY_DATE}'
                AND segments.conversion_action_name = 'Purchase'
        """

        response_conversions = ga_service.search(customer_id=customer_id, query=query_conversions)

        total_conversions_value = 0
        total_conversions = 0

        for row in response_conversions:
            total_conversions_value += row.metrics.conversions_value
            total_conversions += row.metrics.conversions

        # print(f"Total clicks on {QUERY_DATE}: {clicks}")
        # print(f"Total cost on {QUERY_DATE}: {cost}")
        # print(f"Total revenue on {QUERY_DATE}: {total_conversions_value}")
        # print(f"Total conversions (purchases) on {QUERY_DATE}: {total_conversions}")

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
        delete_query = "DELETE FROM google WHERE date = %s"
        cursor.execute(delete_query, (date,))
        query = "INSERT INTO google (date, clicks, CPC, amount, CPA, spend, income, ROAS) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        cursor.execute(query, (date, clicks, CPC, purchase_conversions, CPA, cost, purchase_conversions_value, ROAS))

        connection.commit()
        cursor.close()
    except Error as e:
        print(f"Error inserting data: {e}")


def loops(YY, MM, DD):
    try:
        connection = mysql.connector.connect(**db_config)
        while DD <= 30:
            date = f'{YY}-{MM:02d}-{DD:02d}'
            global QUERY_DATE
            QUERY_DATE = date

            clicks, cost, purchase_conversions_value, purchase_conversions = get_general_metrics(client,
                                                                                                 TARGET_CUSTOMER_ID)

            if clicks is None or cost is None or purchase_conversions_value is None or purchase_conversions is None:
                print(f"Error fetching data for {date}, skipping.")
                DD += 1
                continue

            CPC = cost / clicks if clicks else 0
            CPA = cost / purchase_conversions if purchase_conversions else 0
            ROAS = purchase_conversions_value / cost if cost else 0
            ROAS = round(ROAS, 2)

            store_data(connection, date, clicks, CPC, purchase_conversions, CPA, cost, purchase_conversions_value, ROAS)

            DD += 1
        connection.close()
    except Error as e:
        print(f"Error connecting to MySQL: {e}")


if __name__ == "__main__":
    access_token = refresh_access_token(REFRESH_TOKEN)

    if access_token:
        client = get_google_ads_client(access_token)

        print(f"\nCustomer ID: {TARGET_CUSTOMER_ID}")
        loops(2024, 6, 1)
