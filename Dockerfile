# Collection + enrichment image. Runs the daily pipeline once and exits; schedule
# it with cron / a cloud scheduler and mount a volume for election_sentiment.db.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TOKENIZERS_PARALLELISM=false

COPY requirements.txt requirements-pipeline.txt ./
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements-pipeline.txt

COPY . .

# Pre-download the two sentiment models so the first run does not depend on network.
RUN python -c "from transformers import AutoTokenizer, AutoModelForSequenceClassification as M; \
    [ (AutoTokenizer.from_pretrained(n), M.from_pretrained(n)) for n in \
      ['cardiffnlp/twitter-roberta-base-sentiment-latest', 'Davlan/naija-twitter-sentiment-afriberta-large'] ]"

ENTRYPOINT ["python", "run_pipeline.py"]
