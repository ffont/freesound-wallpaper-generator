# Freesound Wallpaper Generator

This is an awesome app for creating wallpapers using [Freesound](https://freesound.org)'s tools for generating waveform and spectrogram images.

The [code that generates](https://raw.githubusercontent.com/MTG/freesound/master/utils/audioprocessing/processing.py) the waveform and spectrogram images in Freesound was written a number of years ago by [Bram de Jong](https://www.linkedin.com/in/bdejong/). You can use that code as a command line tool as well, see [instructions here](https://github.com/MTG/freesound/wiki/Using-wav2png-to-generate-waveform-and-spectrogram-images). The original idea for the *Freesound Wallpaper Generator* app is from [Sebastian Mealla](https://www.linkedin.com/in/smealla/).

## Dev & deploy instructions

### Build & run

The following environment variables **must** be set before running using a `.env` file:
 * `FS_CLIENT_ID`: Freesound API client ID (needs to have OAuth password grant enabled).
 * `FS_UNAME`: Username for Freesound user that will *download* the sounds.
 * `FS_PASSWORD`: Password for the Freesound user that will *download* the sounds.

The following environment variables are optional:
 * `HOST`, `PORT`: Host and port for the web app (defaults to  `0.0.0.0` and `5000`).
 * `BASE_URL`: Base URL to build app URLs (defaults to `http://localhost:5000/`)
 * `DEBUG`: Flask debug setting flag (defaults to `True`).
 * `DATA_DIR`: Directory where to save generated data files (defaults to `/code/data/` inside docker image)


Create a file in this directory with no contents named `persistent_data.json`:

```touch persistent_data.json```


To run the app use:

```docker-compose up```


## TODO

* limit sounds by duration and handle not found sounds, bad fs connection cases
* cleanup disk from time to time
* choose background image from a number of randomly pre-computed wallpapers
* show generated wallpapers in a sliding div
