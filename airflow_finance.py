# Required Imports
import pandas as pd
import yfinance as yf
import pyodbc
from datetime import datetime, timedelta

# Airflow imports
from airflow import DAG
from airflow.operators.python_operator import PythonOperator

# ------------- Database Connection Functions -------------

def create_connection():
    conn_str = (
        r"DRIVER={SQL Server};"
        r"SERVER=DESKTOP-ES6509R;"  
        r"DATABASE=BikeStores;"
        r"UID=sa;"  
        r"PWD=alvi110@;"    
    )
    try:
        conn = pyodbc.connect(conn_str)
        print("✅ Connected to SQL Server successfully!")
        return conn
    except Exception as e:
        print(f"❌ Error connecting to SQL Server: {e}")
        return None

def create_table_if_not_exists(table_name):
    conn = create_connection()
    if not conn:
        return

    cursor = conn.cursor()
    create_table_query = f"""
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='{table_name}' and xtype='U')
    CREATE TABLE {table_name} (
        trade_date DATETIME,
        close_price FLOAT,
        high_price FLOAT,
        low_price FLOAT,
        open_price FLOAT,
        volume BIGINT,
        symbol VARCHAR(10),
        close_change FLOAT,
        close_pct_change FLOAT
    )
    """
    try:
        cursor.execute(create_table_query)
        conn.commit()
        print(f"✅ Table ensured: {table_name}")
    except Exception as e:
        print(f"❌ Error creating table: {e}")
    finally:
        cursor.close()
        conn.close()

def insert_data_to_db(table_name, values):
    conn = create_connection()
    if not conn:
        return

    cursor = conn.cursor()
    insert_query = f"""
    INSERT INTO {table_name} (
        trade_date, close_price, high_price, low_price, open_price,
        volume, symbol, close_change, close_pct_change
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""

    try:
        cursor.executemany(insert_query, values)
        conn.commit()
        print(f"✅ Inserted {len(values)} rows into {table_name}")
    except Exception as e:
        print(f"❌ Error inserting data: {e}")
    finally:
        cursor.close()
        conn.close()

# ------------- Finance Data Functions -------------

def get_sp500_symbols():
    sp_500_url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    tables = pd.read_html(sp_500_url)
    sp_500 = tables[0]
    return sp_500['Symbol'].tolist()

def get_finance_data(symbols, start_date, end_date, interval):
    result = {}
    for symbol in symbols:
        data = yf.download(tickers=symbol, start=start_date, end=end_date, interval=interval)
        if not data.empty:
            result[symbol] = data
    return result

def transform_data(data, symbol):
    data.columns = [col[0] if isinstance(col, tuple) else col for col in data.columns]
    data = data.reset_index()
    data["symbol"] = symbol
    data['close_change'] = data['Close'].diff().fillna(0)
    data['close_pct_change'] = data['Close'].pct_change().fillna(0) * 100
    return data[['Date', 'Close', 'High', 'Low', 'Open', 'Volume', 'symbol', 'close_change', 'close_pct_change']]

def ingest_yfinance_data(symbols, table_name, interval):
    values = []
    start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    for symbol in symbols:
        try:
            data_dict = get_finance_data([symbol], start_date, end_date, interval)
            if symbol in data_dict:
                data = transform_data(data_dict[symbol], symbol)
                if not data.empty:
                    values.extend([tuple(x) for x in data.to_numpy()])
        except Exception as e:
            print(f"❌ Error processing {symbol}: {e}")
    
    if values:
        insert_data_to_db(table_name, values)

# ------------- Airflow DAG -------------

default_args = {
    'owner': 'zain',
    'depends_on_past': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    dag_id='yfinance_sp500_ingestion',
    default_args=default_args,
    description='Ingest S&P 500 stock prices into SQL Server',
    schedule_interval='@daily',  # Run daily
    start_date=datetime(2025, 4, 26),
    catchup=True,
    tags=['stock', 'finance', 'yfinance'],
) as dag:

    def run_ingestion():
        table_name = 'stock_prices'
        interval = '1d'  # Daily interval
        
        symbols = get_sp500_symbols()
        
        print(f"✅ Total symbols fetched: {len(symbols)}")

        create_table_if_not_exists(table_name)

        # Optional: only take a few during testing
        # symbols = symbols[:10]

        ingest_yfinance_data(symbols, table_name, interval)

    ingestion_task = PythonOperator(
        task_id='ingest_sp500_data',
        python_callable=run_ingestion,
    )

    ingestion_task
