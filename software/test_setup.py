"""Test script to verify all dependencies are installed correctly."""

print("Testing dependencies...\n")

try:
    import streamlit
    print(f"✓ Streamlit {streamlit.__version__} installed")
except ImportError as e:
    print(f"✗ Streamlit not installed: {e}")
    print("  Run: python -m pip install streamlit")

try:
    import plotly
    print(f"✓ Plotly {plotly.__version__} installed")
except ImportError as e:
    print(f"✗ Plotly not installed: {e}")
    print("  Run: python -m pip install plotly")

try:
    import pandas
    print(f"✓ Pandas {pandas.__version__} installed")
except ImportError as e:
    print(f"✗ Pandas not installed: {e}")

try:
    from scrape_boxtrades import scrape_boxtrades
    df = scrape_boxtrades()
    print(f"✓ Scraping function works: {len(df)} rows extracted")
except Exception as e:
    print(f"✗ Scraping function error: {e}")

print("\nIf all checks pass, run: python -m streamlit run app.py")



