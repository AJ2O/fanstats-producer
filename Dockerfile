FROM python:3.9

WORKDIR /usr/src/app

COPY ./src/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# provide environment variables securely
ENV DATA_FILE=nba.yaml
ENV STORAGE_BUCKET=bucket_in_S3
ENV TWITTER_BEARER_TOKEN=twitter_bearer_token
ENV CONFIG_SETUP=True

COPY ./src .
CMD [ "python", "./main.py" ]
