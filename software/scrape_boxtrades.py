"""
Script to scrape boxtrades.com and extract maturity date / effective yield pairs.
Returns the data as a pandas DataFrame.
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
from datetime import datetime

from update_maturity_dates import remove_expired_maturities


def scrape_boxtrades(verbose=False):
    """
    Scrapes boxtrades.com and extracts maturity date / effective yield pairs.
    Returns a pandas DataFrame with the extracted data.
    
    Args:
        verbose: If True, print status messages. Default False for cleaner output when used as a library.
    """
    url = 'https://www.boxtrades.com'
    
    # Set headers to mimic a browser request
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        # Fetch the webpage
        if verbose:
            print(f"Fetching data from {url}...", flush=True)
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Parse the HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find the JSON data script tag (Next.js stores data here)
        script_tag = soup.find('script', id='__NEXT_DATA__')
        
        if not script_tag:
            if verbose:
                print("Warning: Could not find __NEXT_DATA__ script tag.", flush=True)
            return pd.DataFrame(columns=['Maturity Date', 'Effective Yield'])
        
        # Parse the JSON data
        try:
            data = json.loads(script_tag.string)
        except json.JSONDecodeError as e:
            if verbose:
                print(f"Error parsing JSON data: {e}", flush=True)
            return pd.DataFrame(columns=['Maturity Date', 'Effective Yield'])
        
        # Extract synthYields array
        synth_yields = data.get('props', {}).get('pageProps', {}).get('synthYields', [])
        
        if not synth_yields:
            if verbose:
                print("Warning: No synthYields data found in the JSON.", flush=True)
            return pd.DataFrame(columns=['Maturity Date', 'Effective Yield'])
        
        # Extract maturity dates and yields
        effective_yields = []
        
        for item in synth_yields:
            # Extract yield
            yield_value = item.get('yield')
            if yield_value is not None:
                effective_yields.append(float(yield_value))
        
        # Create DataFrame
        if effective_yields:
            # Convert dates to datetime objects and extract yields
            maturity_dates_dt = []
            yields = []
            
            for item in synth_yields:
                expiry_timestamp = item.get('expiry')
                yield_value = item.get('yield')
                
                if expiry_timestamp and yield_value is not None:
                    expiry_date = datetime.fromtimestamp(expiry_timestamp / 1000)
                    maturity_dates_dt.append(expiry_date)
                    yields.append(float(yield_value))
            
            if maturity_dates_dt and yields:
                df = pd.DataFrame({
                    'Maturity Date': maturity_dates_dt,
                    'Effective Yield': yields
                })
                df = remove_expired_maturities(df)
                
                if verbose:
                    print(f"\nSuccessfully extracted {len(df)} maturity date / yield pairs", flush=True)
                return df
        
        if verbose:
            print("\nWarning: Could not extract data from synthYields.", flush=True)
        return pd.DataFrame(columns=['Maturity Date', 'Effective Yield'])
    
    except requests.exceptions.RequestException as e:
        if verbose:
            print(f"Error fetching the webpage: {e}", flush=True)
        return pd.DataFrame(columns=['Maturity Date', 'Effective Yield'])
    except Exception as e:
        if verbose:
            print(f"Error processing the data: {e}", flush=True)
            import traceback
            traceback.print_exc()
        return pd.DataFrame(columns=['Maturity Date', 'Effective Yield'])


if __name__ == '__main__':
    import sys
    
    try:
        # Scrape the data
        df = scrape_boxtrades(verbose=True)
        
        # Display the DataFrame
        output_lines = []
        output_lines.append("\n" + "="*50)
        output_lines.append("Extracted Data:")
        output_lines.append("="*50)
        if not df.empty:
            output_lines.append(df.to_string())
        else:
            output_lines.append("No data extracted. DataFrame is empty.")
        output_lines.append("\n" + "="*50)
        
        # Print all output
        output_text = "\n".join(output_lines)
        print(output_text, flush=True)
        
    except Exception as e:
        error_msg = f"Error in main execution: {e}"
        print(error_msg, file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)