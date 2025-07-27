import os
import sys
import requests
import pandas as pd
import pandasdmx as sdmx
import time
from dotenv import load_dotenv

# --- CONFIGURATION (Copied from the main script) ---
EURO_COUNTRIES = {'DE': 'Germany', 'IT': 'Italy', 'FR': 'France'}
EURO_TENORS = {'Up to 1Y': 'S', '1Y-2Y': 'Y12', '2Y-5Y': 'Y25', '5Y-10Y': 'Y5A', '10Y+': 'YA_'}
EURO_FLOW_ID = 'CSEC'

load_dotenv()
US_BASE_URL = os.getenv("BASE_URL", "https://api.fiscaldata.treasury.gov/services/api/fiscal_service")
US_AUCTION_ENDPOINT = "/v1/accounting/od/auctions_query"
US_AUCTION_CACHE_FILE = 'auctions.pkl'

# ==============================================================================
# --- DATA FETCHING AND PROCESSING FUNCTIONS ---
# ==============================================================================
def get_and_process_euro_data(country_code):
    print(f"\n--- Fetching EURO data for {EURO_COUNTRIES[country_code]} ({country_code}) ---")
    ecb = sdmx.Request('ECB')
    country_data_frames = []
    for tenor_name, tenor_code in EURO_TENORS.items():
        key = f"M.N.{country_code}.W0.S1311.S1.N.LI.F.F3.{tenor_code}._Z.EUR.EUR.M.V.N._T"
        print(f"Fetching tenor: {tenor_name}...")
        try:
            resp = ecb.data(EURO_FLOW_ID, key=key, params={'startPeriod': '2020'})
            series = resp.to_pandas()
            series.name = tenor_name
            country_data_frames.append(series)
        except Exception as e:
            print(f"  -> Could not retrieve data for tenor '{tenor_name}'. Error: {e}")
        time.sleep(0.5)
    
    if not country_data_frames: return None
    final_table = pd.concat(country_data_frames, axis=1)
    
    print("Data fetched. Consolidating for cache...")
    id_vars = final_table.index.names
    df_for_plot = final_table.reset_index()
    df_long = df_for_plot.melt(id_vars=id_vars, var_name='Tenor', value_name='Issuance')
    df_long.dropna(subset=['Issuance'], inplace=True)
    df_long['TIME_PERIOD'] = pd.to_datetime(df_long['TIME_PERIOD'])
    monthly_summary = df_long.groupby([pd.Grouper(key='TIME_PERIOD', freq='M'), 'Tenor'])['Issuance'].sum().unstack(fill_value=0)
    return monthly_summary

def fetch_us_data(base_url, endpoint, api_filter=""):
    all_records = []
    print(f"🚀 Fetching live US data from {endpoint}{api_filter}...")
    try:
        page_number, page_size = 1, 100
        first_page_url = f"{base_url}{endpoint}{api_filter}&page[number]={page_number}&page[size]={page_size}"
        response = requests.get(first_page_url, timeout=60)
        response.raise_for_status()
        data = response.json()
        all_records.extend(data['data'])
        total_pages = data.get('meta', {}).get('total-pages', 1)
        for page_num in range(2, total_pages + 1):
            next_url = f"{base_url}{endpoint}{api_filter}&page[number]={page_num}&page[size]={page_size}"
            response = requests.get(next_url, timeout=30)
            response.raise_for_status()
            all_records.extend(response.json()['data'])
            time.sleep(0.1)
    except requests.exceptions.RequestException as e:
        print(f"\n❌ CRITICAL: Failed to fetch US data from {endpoint}: {e}")
        return None
    print(f"\n✅ US Fetch complete. Records: {len(all_records)}")
    return pd.DataFrame(all_records)

def update_us_cache(start_year=2000):
    print("--- Starting US Data Update ---")
    auction_filter = f"?filter=issue_date:gte:{start_year}-01-01"
    auction_df = fetch_us_data(US_BASE_URL, US_AUCTION_ENDPOINT, auction_filter)
    if auction_df is None:
        print("❌ US data fetch failed. Cache not updated.")
        return
    
    print("⚙️  Processing and preparing US data for cache...")
    auction_df['issue_date'] = pd.to_datetime(auction_df['issue_date'])
    auction_df['maturity_date'] = pd.to_datetime(auction_df['maturity_date'], errors='coerce')
    auction_df['auction_date'] = pd.to_datetime(auction_df['auction_date'], errors='coerce')
    for col in ['total_accepted', 'offering_amt']:
        if col in auction_df.columns:
            auction_df[col] = pd.to_numeric(auction_df[col], errors='coerce').fillna(0)
    auction_df['duration_days'] = (auction_df['maturity_date'] - auction_df['issue_date']).dt.days
    def assign_maturity_bin(days):
        if days <= 0: return 'Other'
        if days < 30: return '< 1 Month'
        if days < 91: return '1-3 Months'
        if days < 365: return '3-12 Months'
        if days < 365 * 3: return '1-3 Years'
        if days < 365 * 10: return '3-10 Years'
        return '10+ Years'
    auction_df['maturity_bin'] = auction_df['duration_days'].apply(assign_maturity_bin)
    
    auction_df.to_pickle(US_AUCTION_CACHE_FILE)
    print(f"✅ US data cache updated and saved to {US_AUCTION_CACHE_FILE}")

def update_euro_cache():
    print("\n--- Starting EURO Data Update ---")
    for code in EURO_COUNTRIES.keys():
        monthly_summary = get_and_process_euro_data(code)
        if monthly_summary is not None:
            cache_file = f'euro_data_{code}.pkl'
            monthly_summary.to_pickle(cache_file)
            print(f"✅ Euro data cache for {code} updated and saved to {cache_file}")

# ==============================================================================
# --- MAIN EXECUTION BLOCK ---
# ==============================================================================
if __name__ == "__main__":
    # This part decides which data to update based on command line arguments
    # This allows the scheduler to call the same script for daily or monthly tasks
    if len(sys.argv) > 1 and sys.argv[1] == 'daily':
        update_us_cache()
    elif len(sys.argv) > 1 and sys.argv[1] == 'monthly':
        update_euro_cache()
    else:
        # If run with no arguments, update everything
        print("Updating all data sources...")
        update_us_cache()
        update_euro_cache()