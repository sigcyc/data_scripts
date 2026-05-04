Here is a plan to download and extract the E-Mini SPY 500 futures data:

1.  **Set up the environment:**
    *   Import necessary libraries: `requests` for downloading, `zipfile` for extraction, and `os` for file management.

2.  **Define constants:**
    *   `BASE_URL`: The base URL for the CFTC historical data.
    *   `START_YEAR`: The starting year for data download (2020).
    *   `END_YEAR`: The ending year for data download (2025).
    *   `OUTPUT_FILE`: The name of the file to save the extracted data (`e-mini-sp500-futures.txt`).
    *   `SEARCH_TERM`: The search term to identify the E-Mini S&P 500 data ("E-MINI S&P 500 STOCK INDEX").

3.  **Create a directory for the data:**
    *   Create a directory named `cftc_data` to store downloaded and extracted files.

4.  **Loop through the years:**
    *   Iterate from `START_YEAR` to `END_YEAR`.
    *   For each year, construct the full URL for the zip file.
    *   Define the local paths for the downloaded zip file and the extracted text file.

5.  **Download the data:**
    *   Send an HTTP GET request to the URL.
    *   Save the content of the response to a local zip file.

6.  **Extract the data:**
    *   Open the downloaded zip file.
    *   Extract the contents to the `cftc_data` directory.

7.  **Process the extracted file:**
    *   Open the extracted text file (usually `deahist.txt`).
    *   Read the file line by line.
    *   If a line contains the `SEARCH_TERM`, append it to the `OUTPUT_FILE`.

8.  **Clean up:**
    *   Remove the downloaded zip file and the extracted text file for each year after processing.

This plan will be implemented in the `test_avante/save_futures.py` script.
