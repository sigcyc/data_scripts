# Form 13f

I want to create a dataset using https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets

Here is the requirement.
1. I should be able to run script incrementally. That is, I can call claude and say: save 13f data for year 2025
2. For each quarter filing, save a data YYYYMMDD.parquet where YYYYMMDD is the quarter end position cutoff date (like 20250331.parquet)
3. IIRC, it has some ticker id but no ticker symbol, I want to add a ticker symbol (e.g. TSLA) to it.
4. Merge different files together. IIRC, there is a file like ASSET_MANAGEMNET2
