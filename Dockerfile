FROM python:2.7
ENV PYTHONUNBUFFERED 1
RUN wget -O /usr/local/bin/dumb-init https://github.com/Yelp/dumb-init/releases/download/v1.2.0/dumb-init_1.2.0_amd64 && chmod +x /usr/local/bin/dumb-init
RUN mkdir /code
WORKDIR /code
ADD requirements.txt /code/
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y libsndfile-dev libav-tools
RUN pip install scikits.audiolab==0.11.0
RUN mkdir audioprocessing && cd audioprocessing \
	&& wget https://raw.githubusercontent.com/MTG/freesound/master/utils/audioprocessing/processing.py \
	&& wget https://raw.githubusercontent.com/MTG/freesound/master/utils/audioprocessing/color_schemes.py \
	&& wget https://raw.githubusercontent.com/MTG/freesound/master/utils/audioprocessing/__init__.py \
	&& cd .. && wget https://raw.githubusercontent.com/MTG/freesound-python/master/freesound.py
ADD code/ /code/
ENTRYPOINT ["python"]
CMD ["app.py"]