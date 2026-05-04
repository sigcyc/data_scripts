import os

# Configuration
DATA_DIR = "cftc_data"
OUTPUT_FILE = "e-mini-sp500-futures.txt"
SEARCH_TERM = "E-MINI S&P 500"

def extract_e_mini_data():
    """
    Extracts E-MINI S&P 500 data from the yearly files.
    """
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)

    header_written = False
    files_to_process = sorted([f for f in os.listdir(DATA_DIR) if f.startswith("cftc_data_") and f.endswith(".txt")])

    with open(OUTPUT_FILE, "a") as f_out:
        for filename in files_to_process:
            file_path = os.path.join(DATA_DIR, filename)
            print(f"Processing {file_path}...")
            with open(file_path, "r") as f_in:
                try:
                    # Write header from the first file
                    if not header_written:
                        header = next(f_in)
                        f_out.write(header)
                        header_written = True
                    else:
                        next(f_in) # Skip header in subsequent files

                    for line in f_in:
                        if SEARCH_TERM in line and "MICRO" not in line:
                            f_out.write(line)
                except StopIteration:
                    print(f"Warning: {filename} is empty or has only a header.")
                except Exception as e:
                    print(f"An error occurred while processing {filename}: {e}")

    print(f"Extraction complete. Data saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    extract_e_mini_data()

