# CPU-only contract/evaluation jobs; GPU training gets a separate, tested image later.
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/workspace/python
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock.txt
COPY python ./python
COPY contracts ./contracts
COPY examples ./examples
COPY configs ./configs
ENTRYPOINT ["python", "-m", "ai_treader_llm.cli"]
