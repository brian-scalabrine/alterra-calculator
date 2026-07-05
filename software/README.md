# Boxtrades Yield Curve Visualizer (Alterra)

A Streamlit web application that visualizes box spread yield data from boxtrades.com and powers the Alterra lending calculator.

## Features

- Loan Structure calculator with cashflow schedule
- Term Structure yield curve chart
- Automatic daily refresh after 3:00 PM Eastern (once per visitor session when due)
- Optional password protection for shared deployments
- Manual force refresh from the sidebar

## Local development

1. Install dependencies:

```bash
cd software
pip install -r requirements.txt
```

2. (Optional) Enable password protection locally:

```bash
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
```

Edit `.streamlit/secrets.toml` and set `app_password`.

3. Run the app:

```bash
python -m streamlit run app.py
```

The app opens at `http://localhost:8501`.

## Deploy to Streamlit Community Cloud

### 1. Push this project to GitHub

If Git is not installed, download [Git for Windows](https://git-scm.com/download/win), then:

```bash
cd "C:\Users\rober\OneDrive\Desktop\Lending Website"
git init
git add software/
git commit -m "Add Alterra Streamlit calculator with daily refresh and auth"
```

Create a new repository on GitHub, then:

```bash
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

### 2. Create the Streamlit app

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. Click **Create app**.
3. Select your repository.
4. Set **Main file path** to: `software/app.py`
5. Set **App URL** (optional custom subdomain).
6. Click **Advanced settings** and set **Python version** to 3.11+ if needed.

### 3. Add secrets

In the Streamlit Cloud app settings, open **Secrets** and paste:

```toml
app_password = "your-strong-password-here"

# Optional schedule overrides (defaults shown)
# refresh_timezone = "America/New_York"
# refresh_hour = 15
# refresh_minute = 0
```

Save and redeploy. Visitors will see a password screen before the calculator.

### 4. Share the link

Streamlit gives you a public URL like:

`https://your-app-name.streamlit.app`

## How daily refresh works

There is no background cron on Streamlit Cloud. Instead:

1. The app stores `last_refreshed_at` in `yield_data_cache.json`.
2. On each new session, it compares that timestamp to the most recent **3:00 PM Eastern** cutoff.
3. If data has not been refreshed since that cutoff, it scrapes boxtrades.com **once**.
4. Otherwise it serves cached data with no scrape.

The sidebar **Force refresh now** button always fetches fresh data immediately.

## Files

- `app.py` — Streamlit application
- `data_refresh.py` — Daily refresh schedule and cache helpers
- `scrape_boxtrades.py` — Scrapes yield data from boxtrades.com
- `update_maturity_dates.py` — Removes expired maturities from cache
- `.streamlit/config.toml` — Streamlit theme and server settings
- `.streamlit/secrets.toml.example` — Template for local/cloud secrets

## Data source

Data is scraped from [boxtrades.com](https://www.boxtrades.com).
