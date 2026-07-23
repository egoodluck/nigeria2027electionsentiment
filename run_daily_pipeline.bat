@echo off
REM Run the daily Nigeria election sentiment pipeline from the repository directory.
cd /d "C:\Users\eGoodluck\Documents\Papers\Sentiment Analysis of 2023 Election\nigeria_election_sentiment"

REM Load environment variables from .env if present.
if exist ".env" (
    for /f "usebackq tokens=1* delims==" %%A in (".env") do (
        if not "%%A"=="#" (
            set "%%A=%%B"
        )
    )
)

"C:\Users\eGoodluck\AppData\Local\Python\bin\python.exe" run_pipeline.py
