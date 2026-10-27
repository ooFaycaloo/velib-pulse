FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY velib_pulse ./velib_pulse
COPY sql ./sql
CMD ["python", "-m", "velib_pulse.producer", "--source", "live", "--sink", "kafka"]
