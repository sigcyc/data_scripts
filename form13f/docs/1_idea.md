Idea:

I want to design a dataframe gui app. It relies on my cyc package

1. It would have multiple tab. Every tab is sym, time_start, time_end, date (which are the same in cyc.df.s).  Each tab would be split into multiple window.
2. There should be a sidebar with (sym, time_start, time_end, date), when we click on the item, it will switch to that tab.
3. For each window, there would be three boxes df_type as in df_types.yaml. left_axis, right_axis as in cyc.data_frame_moneky_patch.p. 
4. When selecting df_type, I can either type or select from a scoll down menu. For left_axis, I can type 1,2,3 for example.
5. On the backend, it should read the dataframe using Df.load_data. And then plot the graph in the window.
6. When I change sym, time_start, time_end, all the windows should reflect it 
7. It should support cli launch. e.g. "df_view AMZN 9:30 10 20260104 stock_data_min1". And then it will automatically go to the tab AMZN 9:30 10 20260104. And split a new window for df stock_data_min1
