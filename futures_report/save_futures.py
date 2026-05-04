import requests
import zipfile
import os
import shutil

# Configuration
BASE_URL = "https://www.cftc.gov/files/dea/history/"
START_YEAR = 2020
END_YEAR = 2025
DATA_DIR = "cftc_data"

def download_and_extract_data():
    """
    Downloads and extracts CFTC data for a given year range, saving each year's data to a separate file.
    """
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    for year in range(START_YEAR, END_YEAR + 1):
        yy = str(year)[-2:]
        url = f"{BASE_URL}fut_fin_txt_{year}.zip"
        zip_path = os.path.join(DATA_DIR, f"fut_fin_txt_{year}.zip")
        extracted_txt_path = os.path.join(DATA_DIR, "FinFutYY.txt")
        output_file_path = os.path.join(DATA_DIR, f"cftc_data_{year}.txt")

        try:
            # Download the file
            print(f"Downloading {url}...")
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"Downloaded to {zip_path}")

            # Extract the file
            print(f"Extracting {zip_path}...")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(DATA_DIR)
            print(f"Extracted to {DATA_DIR}")

            # Save the extracted file with a new name
            if os.path.exists(extracted_txt_path):
                shutil.move(extracted_txt_path, output_file_path)
                print(f"Saved data to {output_file_path}")
            else:
                print(f"Error: FinFutYY.txt not found in the zip archive for {year}.")

        except requests.exceptions.RequestException as e:
            print(f"Error downloading {url}: {e}")
        except zipfile.BadZipFile:
            print(f"Error: {zip_path} is not a valid zip file or is corrupted.")
        finally:
            # Clean up the downloaded zip file
            if os.path.exists(zip_path):
                os.remove(zip_path)
            # Clean up extracted file if it still exists (in case of error)
            if os.path.exists(extracted_txt_path):
                os.remove(extracted_txt_path)

if __name__ == "__main__":
    download_and_extract_data()

