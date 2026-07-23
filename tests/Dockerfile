FROM python:3.14-slim

WORKDIR /workspace

COPY tests/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /workspace

CMD ["pytest", "-q", "tests"]
