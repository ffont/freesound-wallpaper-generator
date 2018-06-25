# Freesound Wallpaper Generator

This is an awesome app for creating wallpapers using [Freesound](https://freesound.org)'s tools for generating waveform and spectrogram images.

The [code that generates](https://raw.githubusercontent.com/MTG/freesound/master/utils/audioprocessing/processing.py) the waveform and spectrogram images in Freesound was written a number of years ago by [Bram de Jong](https://www.linkedin.com/in/bdejong/). You can use that code as a command line tool as well, see [instructions here](https://github.com/MTG/freesound/wiki/Using-wav2png-to-generate-waveform-and-spectrogram-images). The original idea for the *Freesound Wallpaper Generator* app is from [Sebastian Mealla](https://www.linkedin.com/in/smealla/).

## Dev & deploy instructions

### Build

```docker build -t freesound-wp-generator .```

### Run

The following environment variables **must** be set before running:
 * `FS_CLIENT_ID`: Freesound API client ID (needs to have OAuth password grant enabled).
 * `FS_UNAME`: Username for Freesound user that will *download* the sounds.
 * `FS_PASSWORD`: Password for the Freesound user that will *download* the sounds.

The following environment variables are optional:
 * `HOST`, `PORT`: Host and port for the web app (defaults to  `0.0.0.0` and `5000`).
 * `BASE_URL`: Base URL to build app URLs (defaults to `http://localhost:5000/`)
 * `DEBUG`: Flask debug setting flag (defaults to `True`).
 * `DATA_DIR`: Directory where to save generated data files (defaults to `/code/data/` inside docker image)


```docker run -d -p 5000:5000 freesound-wp-generator``` (runs as daemon)

### Build & run

For development purposes use this one-line build & run command which reads env vars from .env file and does not run in daemon.

```docker build -t freesound-wp-generator . && docker run -p 5000:5000 --env-file .env freesound-wp-generator```

## TODO

* add interface for choosing params in website
* add counter of total wallpapers made
* limit sounds by duration and handle not found sounds, bad fs connection cases
* cleanup disk from time to time
* choose background image from a number of randomly pre-computed wallpapers
