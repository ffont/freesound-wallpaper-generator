import os
import uuid
import freesound
import requests
import subprocess
from flask import Flask, request, send_from_directory, render_template
from flask_socketio import SocketIO, emit
from audioprocessing.processing import create_wave_images
from store import DictStoreBackend as StoreBackend

app = Flask(__name__)
socketio = SocketIO(app)

HOST = os.getenv('HOST', '0.0.0.0')
PORT = os.getenv('PORT', 5000)
DEBUG = os.getenv('DEBUG', '1') == '1'  # Set it to '1' for DEBUG mode True, otherwise will be False
BASE_URL = os.getenv('BASE_URL', 'http://localhost:5000/')
DATA_DIR = os.getenv('DATA_DIR', '/code/data/')

try:
    FS_CLIENT_ID = os.environ['FS_CLIENT_ID']
    FS_UNAME = os.environ['FS_UNAME']
    FS_PASSWORD = os.environ['FS_PASSWORD']
except KeyError:
    raise Exception("Environment variables FS_CLIENT_ID, FS_UNAME and/or FS_PASSWORD not properly set.")

freesound_client = None
store = StoreBackend()


# UTILS

def configure_freesound():
    # Get user access token and configure client
    client = None
    try:
        resp = requests.post(
            'https://freesound.org/apiv2/oauth2/access_token/',
            data={
                'client_id': FS_CLIENT_ID,
                'grant_type': 'password',
                'username': FS_UNAME,
                'password': FS_PASSWORD,
            }
        )
        access_token = resp.json()['access_token']
        client = freesound.FreesoundClient()
        client.set_token(access_token, auth_type='oauth')
        print 'Freesound configured successfully!'
    except requests.exceptions.ConnectionError:
        print 'Could not connect to Freesound, running in FAKE mode...'
    return client

def convert_to_wav(input_filename, output_filename, samplerate=44100, nbits=16, nchannels=1):
    nbits_labels = {8: 'pcm_u8', 16: 'pcm_s16le', 24: 'pcm_s24le', 32: 'pcm_s32le'}
    cmd = ["ffmpeg", "-y", "-i", input_filename, "-ac", str(nchannels), "-acodec", nbits_labels[nbits],
           "-ar", str(samplerate), output_filename]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout, stderr) = process.communicate()
    if process.returncode != 0 or not os.path.exists(output_filename):
        raise Exception("Failed converting to wav data:\n" + " ".join(cmd) + "\n" + stderr + "\n" + stdout)

def get_freesound_sound(sound_id):
    """download Freesound sound and return path of file downloaded and converted to PCM"""

    if freesound_client is not None:
        # get sound data
        sound = freesound_client.get_sound(int(sound_id))
        store_filename = '{sound_id}.{sound_type}'.format(sound_id=sound.id, sound_type=sound.type)

        # download sound
        if not os.path.exists(os.path.join(DATA_DIR, store_filename)):
            print 'Downloading {0}'.format(store_filename)
            sound.retrieve(DATA_DIR, name=store_filename)

        # convert sound
        if sound.type != 'wav':
            converted_filename = '{sound_id}.{sound_type}'.format(sound_id=sound.id, sound_type='wav')
            if not os.path.exists(os.path.join(DATA_DIR, converted_filename)):
                print 'Converting to WAV {0}'.format(store_filename)
                convert_to_wav(os.path.join(DATA_DIR, store_filename), os.path.join(DATA_DIR, converted_filename))
        else:
            converted_filename = store_filename
    else:
        # If can't connect to Freesound, return test file
        converted_filename = 'test.wav'

    return os.path.join(DATA_DIR, converted_filename)

def make_progress_callback_function(ws_session_id):

    def progress_callback_function(percentage):
        ws_session_data = store.get(ws_session_id)
        ws_session_data.update({'percentage': percentage})
        if percentage == 100:
            ws_session_data.update({
                'url_spectrogram': BASE_URL + 'img/' + ws_session_data['spectrogram_filename'],
                'url_waveform': BASE_URL + 'img/' + ws_session_data['waveform_filename']
                })
        store.set(ws_session_id, ws_session_data)
        emit('progress_report', ws_session_data, json=True, room=ws_session_id)

    return progress_callback_function


# WEBSCOKETS

@socketio.on('connected')
def handle_connect_event(data):
    ws_session_id = request.sid  # Web sockets session ID (used to identify individual clients)
    print(data['message'])
    emit('connected_response', {'message': 'Server ready! ({0})'.format(ws_session_id)}, json=True)

@socketio.on('create_wallpaper')
def handle_create_wallpaper_event(data):
    sound_id = int(data.get('sound_id', 1234))
    width = int(data.get('width', 100))
    height = int(data.get('height', 100))
    fft_size = int(data.get('fft_size', 2048))
    color_scheme = data.get('color_scheme', 'Freesound2')

    print('Creating wallpaper for input params:', sound_id, width, height, fft_size)
    ws_session_id = request.sid
    sound_path = get_freesound_sound(sound_id)
    out_base_filename = str(uuid.uuid4()).split('-')[0]
    waveform_filename = 'w_%s.png' % out_base_filename
    spectrogram_filename = 's_%s.jpg' % out_base_filename
    waveform_img_path = os.path.join(DATA_DIR, waveform_filename)
    spectrogram_img_path = os.path.join(DATA_DIR, spectrogram_filename)

    store.set(ws_session_id, {
            'status': 'Started',
            'ws_session_id': ws_session_id,
            'sound_id': sound_id,
            'percentage': 0,
            'waveform_filename': waveform_filename,
            'spectrogram_filename': spectrogram_filename
        })

    create_wave_images(sound_path, 
        waveform_img_path, spectrogram_img_path, width, height, fft_size=fft_size, 
        progress_callback=make_progress_callback_function(ws_session_id), 
        color_scheme=color_scheme)


# VIEWS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/img/<path:filename>/')
def serve_image(filename):
    return send_from_directory(DATA_DIR, filename)


# RUN FLASK


if __name__ == '__main__':
    freesound_client = configure_freesound()
    socketio.run(app, debug=DEBUG, host=HOST, port=PORT)
