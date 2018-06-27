import os
import uuid
import freesound
import requests
import subprocess
import json
import thread
from flask import Flask, request, send_from_directory, render_template, copy_current_request_context
from flask_socketio import SocketIO, emit
from audioprocessing.processing import create_wave_images
from store import DictStoreBackend as StoreBackend
from collections import defaultdict

HOST = os.getenv('HOST', '0.0.0.0')
PORT = os.getenv('PORT', 5000)
DEBUG = os.getenv('DEBUG', '1') == '1'  # Set it to '1' for DEBUG mode True, otherwise will be False
APPLICATION_ROOT = os.getenv('APPLICATION_ROOT', '')
BASE_URL = os.getenv('BASE_URL', 'http://localhost:5000/')
DATA_DIR = os.getenv('DATA_DIR', '/app/code/data/')
dir_path = os.path.dirname(os.path.realpath(__file__))
STATIC_DIR = os.path.join(dir_path, 'static')
COLOR_SCHEMES_ENABLED = os.getenv('COLOR_SCHEMES_ENABLED', 'Freesound2').split(',')
MAX_SOUND_DURATION = 60

try:
    FS_CLIENT_ID = os.environ['FS_CLIENT_ID']
    FS_UNAME = os.environ['FS_UNAME']
    FS_PASSWORD = os.environ['FS_PASSWORD']
except KeyError:
    raise Exception("Environment variables FS_CLIENT_ID, FS_UNAME and/or FS_PASSWORD not properly set.")

app = Flask(__name__)
socketio_path = '/socket.io'
if APPLICATION_ROOT:
    socketio_path =  '/' + APPLICATION_ROOT + socketio_path

socketio = SocketIO(app, path=socketio_path)
freesound_client = None
store = StoreBackend()


# UTILS

def log(message):
    print message

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
        log('Freesound configured successfully!')
    except requests.exceptions.ConnectionError:
        log('Could not connect to Freesound...')
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
        try:
            # get sound data
            sound = freesound_client.get_sound(int(sound_id))
            if sound.duration > MAX_SOUND_DURATION:
                raise Exception("Sound {0} is too long, choose a sound shorter than {1}s".format(sound_id, MAX_SOUND_DURATION))

            store_filename = '{sound_id}.{sound_type}'.format(sound_id=sound.id, sound_type=sound.type)

            # download sound
            if not os.path.exists(os.path.join(DATA_DIR, store_filename)):
                log('Downloading {0}'.format(store_filename))
                sound.retrieve(DATA_DIR, name=store_filename)

            # convert sound to PCM
            if sound.type != 'wav':
                converted_filename = '{sound_id}.{sound_type}'.format(sound_id=sound.id, sound_type='wav')
                if not os.path.exists(os.path.join(DATA_DIR, converted_filename)):
                    log('Converting to WAV {0}'.format(store_filename))
                    convert_to_wav(os.path.join(DATA_DIR, store_filename), os.path.join(DATA_DIR, converted_filename))
            else:
                converted_filename = store_filename
            
            converted_file_sound_path = os.path.join(DATA_DIR, converted_filename)
            return sound, converted_file_sound_path

        except freesound.FreesoundException as e:
            if e.code == 404:
                raise Exception("Can't find sound with ID {0}".format(sound_id))
            log('ERROR: {0}'.format(e))
            raise Exception("Can't prepare sound (Freesound exception)")
    else:
        raise Exception("Can't prepare sound (could not connect to Freesound)")

def make_progress_callback_function(ws_session_id, color_scheme):

    @copy_current_request_context  # Needed to emit websockets messages within the thread
    def progress_callback_function(percentage):

        # Compute percentage and prepare data to send to client
        ws_session_data = store.get(ws_session_id)
        ws_session_data['wallpapers'][color_scheme]['percentage'] = percentage
        ws_session_data['total_percentage'] = float(sum([ws_session_data['wallpapers'][scheme].get('percentage', 0) for scheme in ws_session_data['color_schemes']]))/len(ws_session_data['color_schemes'])
        log('Generating wallpapers for {0}-{1}: {2}%'.format(ws_session_id, color_scheme, ws_session_data['total_percentage'])) 
        if percentage == 100:
            ws_session_data['wallpapers'][color_scheme]['urls'] = {
                'url_spectrogram': BASE_URL + APPLICATION_ROOT + '/img/' + ws_session_data['wallpapers'][color_scheme]['filenames']['spectrogram_filename'],
                'url_waveform': BASE_URL + APPLICATION_ROOT + '/img/' + ws_session_data['wallpapers'][color_scheme]['filenames']['waveform_filename']
            }
        
        # Save total wallpaper counter
        if int(ws_session_data['total_percentage']) == 100:
            persistent_data = json.load(open('/app/code/persistent_data.json'))  # Load persistent data
            persistent_data['n_wallpapers'] += len(ws_session_data['color_schemes']) * 2
            json.dump(persistent_data, open('/app/code/persistent_data.json', 'w'))  # Save persistent data
            ws_session_data['n_total_wallpapers'] = persistent_data['n_wallpapers']

        # Store session data and emit progress report message
        store.set(ws_session_id, ws_session_data)
        ws_session_data.update({
            'message': 'Creating wallpapers {0}x{1}... ({2}%)'.format(ws_session_data['width'], ws_session_data['height'], int(ws_session_data['total_percentage'])),
            'errors': False,
        })
        emit('progress_report', ws_session_data, json=True, room=ws_session_id)

    return progress_callback_function


# WEBSCOKETS

@socketio.on('connected')
def handle_connect_event(data):
    ws_session_id = request.sid  # Web sockets session ID (used to identify individual clients)
    log(data['message'])
    emit('connected_response', {'message': 'Server ready! ({0})'.format(ws_session_id)}, json=True)

@socketio.on('create_wallpaper')
def handle_create_wallpaper_event(data):
    # TODO: catch key error for websockets connection problems?
    ws_session_id = request.sid

    try:
        sound_id = int(data.get('sound_id', 1234))
        width = int(data.get('width', 100))
        height = int(data.get('height', 100))
        fft_size = int(data.get('fft_size', 2048))        
    except ValueError, TypeError:
        emit('progress_report', {'message': 'Invalid input parameters', 'errors': True}, json=True, room=ws_session_id)
        return

    emit('progress_report', {'message': 'Preparing sound...', 'errors': False}, json=True, room=ws_session_id)
    try:
        sound, converted_file_sound_path = get_freesound_sound(sound_id)
    except Exception as e:
        log('ERROR: {0}'.format(e))
        emit('progress_report', {'message': e.message, 'errors': True}, 
            json=True, room=ws_session_id)
        return

    out_base_filename = str(uuid.uuid4()).split('-')[0]
    ws_session_data = {
        'ws_session_id': ws_session_id,
        'sound_id': sound_id,
        'sound_preview_ogg': sound.previews.preview_hq_ogg,
        'sound_preview_mp3': sound.previews.preview_hq_mp3,
        'sound_username': sound.username,
        'sound_name': sound.name,
        'sound_url': sound.url,
        'width': width,
        'height': height,
        'total_percentage': 0,
        'color_schemes': COLOR_SCHEMES_ENABLED,
        'wallpapers': defaultdict(dict),
    }

    for color_scheme in COLOR_SCHEMES_ENABLED:
        waveform_filename = '%i_w_%s_%s.png' % (sound_id, out_base_filename, color_scheme)
        spectrogram_filename = '%i_s_%s_%s.jpg' % (sound_id, out_base_filename, color_scheme) 
        waveform_img_path = os.path.join(DATA_DIR, waveform_filename)
        spectrogram_img_path = os.path.join(DATA_DIR, spectrogram_filename)
        ws_session_data['wallpapers'][color_scheme]['filenames'] = {
            'spectrogram_filename': spectrogram_filename,
            'waveform_filename': waveform_filename,
        }
        store.set(ws_session_id, ws_session_data)

        # Trigger creation of images in a thread
        thread.start_new_thread(create_wave_images, 
            (converted_file_sound_path, waveform_img_path, spectrogram_img_path, width, height),
            dict(fft_size=fft_size, progress_callback=make_progress_callback_function(ws_session_id, color_scheme), progress_callback_steps=50, color_scheme=color_scheme))
        

# VIEWS

@app.route('/' + APPLICATION_ROOT, strict_slashes=False)
def index():
    persistent_data = json.load(open('/app/code/persistent_data.json'))
    n_total_wallpapers = persistent_data['n_wallpapers']
    sound_id = request.args.get('sound_id', '')
    return render_template('index.html', application_root=APPLICATION_ROOT, 
        base_url=BASE_URL, n_total_wallpapers=n_total_wallpapers, sound_id=sound_id)

@app.route('/' + APPLICATION_ROOT + '/img/<path:filename>/', strict_slashes=False)
def serve_image(filename):
    return send_from_directory(DATA_DIR, filename)

# Serve static files in APPLICATION_ROOT URL path
@app.route('/' + APPLICATION_ROOT + '/static/<path:filename>/', strict_slashes=False) 
def custom_static(filename):
    return send_from_directory(STATIC_DIR, filename)


# RUN FLASK

if __name__ == '__main__':

    # Check if persistent_data file exists, otherwise initialize it
    try:
        json.load(open('/app/code/persistent_data.json'))
    except ValueError:
        persistent_data = {'n_wallpapers': 0}
        json.dump(persistent_data, open('/app/code/persistent_data.json', 'w'))

    freesound_client = configure_freesound()
    socketio.run(app, debug=DEBUG, host=HOST, port=PORT)
