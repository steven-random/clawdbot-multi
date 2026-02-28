FROM node:20-slim
RUN apt-get update && apt-get install -y python3 python3-pip bash && rm -rf /var/lib/apt/lists/*
RUN npm install -g @openai/codex
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --break-system-packages -r requirements.txt
COPY . .
CMD ["python3", "agent.py"]
