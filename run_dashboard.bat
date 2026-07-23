@echo off
REM Launch the live sentiment dashboard from the repository directory.
cd /d "C:\Users\eGoodluck\Documents\Papers\Sentiment Analysis of 2023 Election\nigeria_election_sentiment"

"C:\Users\eGoodluck\AppData\Local\Python\bin\python.exe" -m streamlit run dashboard.py
