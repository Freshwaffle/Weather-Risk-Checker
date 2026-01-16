FROM zauberzeug/nicegui:latest

COPY . /app/
WORKDIR /app

# Install any extra deps (requirements.txt is optional here since base image has nicegui)
RUN pip install --no-cache-dir -r requirements.txt || true

EXPOSE 7860

CMD ["python3", "weather_checker.py"]  
