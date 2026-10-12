FROM python:3.12-alpine
RUN apk add --no-cache docker-cli tini
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .
EXPOSE 8444
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["python", "server.py"]
