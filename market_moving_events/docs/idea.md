# Market moving events

I want to write a daily script using the interface of save_data skill to do the following

1. Find the market moving events known ahead of time (i.e. not a breaking news)
2. The events must include CPI, PPI, SPY/QQQ/MSCI index announcement / add time, US larbor date
3. Include other big market moving events if exists
4. Create a dataset where each row has a time for the event, sym to be the event
5. The script should be run for a future days for expected events (so not just based on past news)
6. When the events happened in the past, summarize the events in a "summarize" column
7. Add a column "event_date_type" which is "actual" vs "exepcted"
