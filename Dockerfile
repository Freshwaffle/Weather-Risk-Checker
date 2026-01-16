FROM zauberzeug/nicegui:latest

COPY . /app/
WORKDIR /app


RUN pip install --no-cache-dir -r requirements.txt || true

EXPOSE 7860

CMD ["python3", "weather_checker.py"]  
# commit to trigger HF build
