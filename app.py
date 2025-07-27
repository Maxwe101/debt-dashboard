import os
import pandas as pd
from flask import Flask, render_template_string, request
import plotly.graph_objects as go
import plotly.io as pio
from datetime import datetime

# ==============================================================================
# --- CONFIGURATION (UNCHANGED) ---
# ==============================================================================
EURO_COUNTRIES = {'DE': 'Germany', 'IT': 'Italy', 'FR': 'France'}
EURO_PLOT_ORDER = ['Up to 1Y', '1Y-2Y', '2Y-5Y', '5Y-10Y', '10Y+']
EURO_PLOTLY_COLORS = {'Up to 1Y': '#3288bd', '1Y-2Y': '#abdda4', '2Y-5Y': '#fdae61', '5Y-10Y': '#f46d43', '10Y+': '#d53e4f'}
US_AUCTION_CACHE_FILE = 'auctions.pkl'
US_PLOT_ORDER = ['< 1 Month','1-3 Months','3-12 Months','1-3 Years','3-10 Years','10+ Years','Other']
US_PLOTLY_COLORS = {'< 1 Month':'#d53e4f', '1-3 Months':'#f46d43', '3-12 Months':'#fdae61', '1-3 Years':'#abdda4', '3-10 Years':'#3288bd', '10+ Years':'#5e4fa2', 'Other':'#cccccc'}

# ==============================================================================
# --- PLOTTING LOGIC ---
# ==============================================================================
def create_euro_plotly_charts(df, country_name):
    # This function remains unchanged from the previous version
    if df is None or df.empty: return "<p>No data to display.</p>", "<p>No data to display.</p>"
    monthly_total = df.sum(axis=1)
    df_positive = df[monthly_total > 0].copy()
    if df_positive.empty: return "<p>No positive issuance data to plot.</p>", "<p>No positive issuance data to plot.</p>"
    shapes = [dict(type="line", xref="x", yref="paper", x0=date, y0=0, x1=date, y1=1, line=dict(color="grey", width=1, dash="dash"), opacity=0.5) for date in df_positive.index]
    monthly_total_positive = df_positive.sum(axis=1)
    df_pct = df_positive.div(monthly_total_positive, axis=0) * 100
    fig_pct = go.Figure()
    for cat in EURO_PLOT_ORDER:
        if cat in df_pct.columns and df_pct[cat].sum() > 0:
            fig_pct.add_trace(go.Scatter(x=df_pct.index, y=df_pct[cat], name=cat, mode='lines', stackgroup='one', line=dict(color=EURO_PLOTLY_COLORS.get(cat)), hovertemplate=f'<b>{cat}</b><br>%{{x|%Y-%m-%d}}<br>%{{y:.2f}}%<extra></extra>'))
    fig_pct.update_layout(title_text=f'<b>{country_name} Debt Issuance Mix (by Month)</b>', yaxis_title="Issuance Mix (%)", legend_title_text='Tenor', height=700, margin=dict(b=40), shapes=shapes)
    df_billions = df_positive / 1000
    fig_nominal = go.Figure()
    for cat in EURO_PLOT_ORDER:
        if cat in df_billions.columns and df_billions[cat].sum() > 0:
            hovertemplate_string = '<b>' + cat + '</b><br>%{x|%Y-%m-%d}<br>€%{y:,.2f} Billion<extra></extra>'
            fig_nominal.add_trace(go.Scatter(x=df_billions.index, y=df_billions[cat], name=cat, mode='lines', stackgroup='one', line=dict(color=EURO_PLOTLY_COLORS.get(cat)), hovertemplate=hovertemplate_string))
    fig_nominal.update_layout(title_text=f'<b>{country_name} Nominal Debt Issuance by Tenor (by Month)</b>', yaxis_title="Issuance Amount (€ Billions)", legend_title_text='Tenor', height=700, margin=dict(b=40), shapes=shapes)
    for fig in [fig_pct, fig_nominal]:
        fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='LightGrey', griddash='dash')
        fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='LightGrey', griddash='dash')
    return pio.to_html(fig_pct, full_html=False), pio.to_html(fig_nominal, full_html=False)

# ==============================================================================
# --- FLASK WEB APPLICATION ---
# ==============================================================================
app = Flask(__name__)
HTML_TEMPLATE = """
<!doctype html><html><head><title>Debt Issuance Dashboard</title>
<style>
    body{font-family:sans-serif;margin:2em;background-color:#f4f4f9;color:#333;} h1{color:#003399;}
    .controls, .us-controls{display:flex;align-items:center;gap:15px;margin-bottom:1em;padding:1em;border:1px solid #ccc;border-radius:8px;background-color:#fff;}
    .chart, .table-container{margin-top:2em;border:1px solid #ccc;border-radius:8px;background-color:#fff;padding:1em;}
    .table-container table{width:60%;border-collapse:collapse;margin-top:1em;}
    .table-container th, .table-container td{border:1px solid #ddd;padding:8px;text-align:left;}
    .table-container th{background-color:#e9ecef;}
</style>
</head><body><h1>{{ title }}</h1>
<div class="controls">
    <form method="get" style="margin:0;">
        <label for="country"><b>Select Country:</b></label>
        <select id="country" name="country" onchange="this.form.submit()">
            <option value="US" {% if selected_country == 'US' %}selected{% endif %}>USA</option>
            <option value="DE" {% if selected_country == 'DE' %}selected{% endif %}>Germany</option>
            <option value="IT" {% if selected_country == 'IT' %}selected{% endif %}>Italy</option>
            <option value="FR" {% if selected_country == 'FR' %}selected{% endif %}>France</option>
        </select>
    </form>
</div>
{% if selected_country == 'US' %}
<div class="us-controls">
<form method="get" style="margin:0;">
    <input type="hidden" name="country" value="US">
    <span><b>Date Range:</b></span>
    <label for="start">Start:</label><input type="date" id="start" name="start_date" value="{{ start_date }}">
    <label for="end">End:</label><input type="date" id="end" name="end_date" value="{{ end_date }}">
    <button type="submit">Update</button>
</form></div>
{% endif %}
<div class="chart">{{ chart_html|safe }}</div>
<div class="chart">{{ nominal_chart_html|safe }}</div>
{% if selected_country == 'US' %}
<div class="table-container">{{ future_table_html|safe }}</div>
{% endif %}
</body></html>
"""

# --- Load US data from cache ONCE when the app starts ---
try:
    US_DASHBOARD_DATA = pd.read_pickle(US_AUCTION_CACHE_FILE)
    print(f"✅ Successfully loaded US data from cache file: {US_AUCTION_CACHE_FILE}")
except FileNotFoundError:
    print(f"⚠️ WARNING: US cache file not found. US charts will be empty until the update script is run.")
    US_DASHBOARD_DATA = pd.DataFrame()


@app.route('/', methods=['GET'])
def dashboard():
    selected_country_code = request.args.get('country', 'US')
    chart_html, nominal_chart_html, future_table_html = "", "", ""
    start_date, end_date = "", ""
    title = "Debt Issuance Dashboard"

    if selected_country_code == 'US':
        title = "U.S. Treasury Debt Issuance Dashboard"
        if US_DASHBOARD_DATA.empty:
             chart_html = nominal_chart_html = "<p>US data cache is empty. Please run the update script.</p>"
        else:
            today_dt = datetime.now()
            today_pd = pd.to_datetime('today').normalize()
            default_start = US_DASHBOARD_DATA['issue_date'].min().strftime('%Y-%m-%d')
            start_date = request.args.get('start_date', default_start)
            end_date = request.args.get('end_date', today_dt.strftime('%Y-%m-%d'))
            future_table_html = "<h2>Forthcoming Auctions</h2>"
            df_future = US_DASHBOARD_DATA[US_DASHBOARD_DATA['auction_date'] > today_pd].copy()
            if not df_future.empty:
                df_future_display = df_future[['auction_date', 'security_term', 'offering_amt']].sort_values('auction_date').reset_index(drop=True)
                df_future_display['offering_amt'] = (df_future_display['offering_amt'] / 1e9).map('${:,.2f}B'.format)
                df_future_display['auction_date'] = df_future_display['auction_date'].dt.strftime('%Y-%m-%d')
                df_future_display.rename(columns={'auction_date': 'Auction Date', 'security_term': 'Security', 'offering_amt': 'Offering Amount'}, inplace=True)
                future_table_html += df_future_display.to_html(classes='table', index=False)
            else:
                future_table_html += "<p>No future auctions currently announced.</p>"
            mask = (US_DASHBOARD_DATA['issue_date'] >= start_date) & (US_DASHBOARD_DATA['issue_date'] <= end_date)
            df_filtered = US_DASHBOARD_DATA.loc[mask].copy()
            if df_filtered.empty:
                chart_html = nominal_chart_html = "<p>No data for selected date range.</p>"
            else:
                df_filtered.set_index('issue_date', inplace=True)
                quarterly_issuance = df_filtered.resample('Q')['total_accepted'].sum()
                quarterly_mix_nominal = df_filtered.groupby([pd.Grouper(freq='Q'), 'maturity_bin'])['total_accepted'].sum().unstack(fill_value=0)
                quarterly_mix_pct = quarterly_mix_nominal.divide(quarterly_issuance, axis=0).fillna(0) * 100
                shapes = [dict(type="line", xref="x", yref="paper", x0=q_date, y0=0, x1=q_date, y1=1, line=dict(color="grey", width=1, dash="dash"), opacity=0.5) for q_date in quarterly_mix_pct.index]
                fig_pct = go.Figure()
                for cat in US_PLOT_ORDER:
                    if cat in quarterly_mix_pct.columns and quarterly_mix_pct[cat].sum() > 0:
                        fig_pct.add_trace(go.Scatter(x=quarterly_mix_pct.index, y=quarterly_mix_pct[cat], name=cat, mode='lines', stackgroup='one', line=dict(color=US_PLOTLY_COLORS.get(cat)), hovertemplate = f'<b>{cat} Share: </b>%{{y:.2f}}%<extra></extra>'))
                fig_pct.update_layout(title_text='<b>U.S. Treasury Debt Issuance Mix (by Quarter)</b>', legend_title_text='Maturity Bin', yaxis_title="Issuance Mix (%)", height=700, margin=dict(b=40), shapes=shapes, xaxis_range=[start_date, today_dt])
                fig_nominal = go.Figure()
                for cat in US_PLOT_ORDER:
                     if cat in quarterly_mix_nominal.columns and quarterly_mix_nominal[cat].sum() > 0:
                        fig_nominal.add_trace(go.Scatter(x=quarterly_mix_nominal.index, y=quarterly_mix_nominal[cat] / 1e9, name=cat, mode='lines', stackgroup='one', line=dict(color=US_PLOTLY_COLORS.get(cat)), hovertemplate = '<b>' + cat + '</b><br>%{x|%Y-%m-%d}<br>$%{y:.2f} Billion<extra></extra>'))
                fig_nominal.update_layout(title_text='<b>Nominal Debt Issuance by Maturity (by Quarter)</b>', legend_title_text='Maturity Bin', yaxis_title="Issuance Amount ($ Billions)", height=700, margin=dict(b=40), shapes=shapes, xaxis_range=[start_date, today_dt])
                for fig in [fig_pct, fig_nominal]:
                    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='LightGrey', griddash='dash')
                    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='LightGrey', griddash='dash')
                chart_html = pio.to_html(fig_pct, full_html=False)
                nominal_chart_html = pio.to_html(fig_nominal, full_html=False)
    
    elif selected_country_code in EURO_COUNTRIES:
        title = f"{EURO_COUNTRIES[selected_country_code]} Debt Issuance Dashboard"
        try:
            euro_cache_file = f'euro_data_{selected_country_code}.pkl'
            monthly_summary_df = pd.read_pickle(euro_cache_file)
            print(f"✅ Successfully loaded EURO data from cache file: {euro_cache_file}")
            chart_html, nominal_chart_html = create_euro_plotly_charts(monthly_summary_df, EURO_COUNTRIES[selected_country_code])
        except FileNotFoundError:
            print(f"⚠️ WARNING: EURO cache file for {selected_country_code} not found. Charts will be empty until the update script is run.")
            chart_html = nominal_chart_html = f"<p>Euro data cache for {EURO_COUNTRIES[selected_country_code]} is empty. Please run the update script.</p>"

    return render_template_string(HTML_TEMPLATE, title=title, chart_html=chart_html, nominal_chart_html=nominal_chart_html, future_table_html=future_table_html, selected_country=selected_country_code, start_date=start_date, end_date=end_date)

if __name__ == "__main__":
    # Note: For Render, we need to specify the host and port.
    # Render provides the PORT environment variable.
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)