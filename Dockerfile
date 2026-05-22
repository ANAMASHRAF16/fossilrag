# Shared Docker image for all three Lambda functions.
# Uses AWS Lambda Python 3.11 base image — same runtime as production.
# sentence-transformers + FAISS are pre-installed so cold starts are fast.

FROM public.ecr.aws/lambda/python:3.11

WORKDIR /var/task

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the sentence-transformers model so it's baked into the image
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application code
COPY src/ ./src/
COPY lambda/ ./lambda/

# Default handler — override in docker-compose or Lambda config
CMD ["lambda.api_handler.handler"]
