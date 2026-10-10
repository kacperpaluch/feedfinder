FROM python:3.13-alpine
WORKDIR /app
COPY app.py .
USER nobody
EXPOSE 8000
CMD ["python", "-u", "app.py"]
