FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_sm
COPY . .
ENV DATABASE_URL=sqlite:///./qi_stat_studio.db
# Pre-requisite: run 'cd web && npm run build' before docker build
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
