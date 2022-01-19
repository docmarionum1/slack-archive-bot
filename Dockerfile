FROM python:3.9-alpine

WORKDIR /usr/src/app

COPY . /usr/src/app

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python3", "archivebot.py"]