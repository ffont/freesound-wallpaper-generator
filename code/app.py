import os
import uuid
import freesound
import requests
import subprocess
import json
import thread
import random
from flask import Flask, request, send_from_directory, render_template, copy_current_request_context
from flask_socketio import SocketIO, emit
from audioprocessing.processing import create_wave_images
from store import DictStoreBackend as StoreBackend
from collections import defaultdict
from PIL import Image

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
COOL_SOUND_IDS = [1234, 433127, 32405, 76907, 262480, 291164, 13800, 53922, 106595, 321938];
THUMBNAIL_HEIGHT = 500;
            

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

def create_thumbnail(input_filename, out_width, out_height):
    log('Generating thumbnail for {0}'.format(input_filename))
    input_filename_no_ext, ext = input_filename.rsplit('.', 1)
    output_filename = '{0}_t.{1}'.format(input_filename_no_ext, ext)
    img = Image.open(input_filename)
    img.thumbnail((out_width, out_height))
    img.save(output_filename)
    return output_filename

def get_random_freesound_id():
    """generate a random Freesound ID with a search query"""
    if freesound_client is not None:
        try:
            query_results = freesound_client.text_search(query="", filter="duration:[1.0 TO 60.0]", fields="id")
            num_per_page = len(query_results.results)
            total_count = query_results.count
            random_idx = random.randint(0, total_count)
            corresponding_page_nr = int(random_idx / num_per_page)
            new_query_results = freesound_client.text_search(query="", filter="duration:[1.0 TO 60.0]", page=corresponding_page_nr, fields="id")
            sound = new_query_results[random_idx - (corresponding_page_nr * num_per_page)]
            return sound.id
        except requests.exceptions.ConnectionError:
            return random.choice(COOL_SOUND_IDS)
        except freesound.FreesoundException:
            # Can't connect to Freesound
            return random.choice(COOL_SOUND_IDS)
    else:
        return random.choice(COOL_SOUND_IDS)


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
            if e.code == 401:
                # Authentication problems, configure Freesound again and tell user to try again
                global freesound_client
                freesound_client = configure_freesound()
                raise Exception("Ups some errors occurred, please try again...")
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
                'spec': BASE_URL + APPLICATION_ROOT + '/img/' + ws_session_data['wallpapers'][color_scheme]['filenames']['spec'],
                'wave': BASE_URL + APPLICATION_ROOT + '/img/' + ws_session_data['wallpapers'][color_scheme]['filenames']['wave']
            }
        
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

    @copy_current_request_context  # Needed to emit websockets messages within the thread
    def create_wallpaper_and_thumbnail(ws_session_id, converted_file_sound_path, waveform_img_path, spectrogram_img_path, 
                                       width, height, thumbnail_width, thumbnail_height,
                                       fft_size=None, progress_callback=None, progress_callback_steps=None, 
                                       color_scheme=None):

        # NOTE: this function is defined inside 'handle_create_wallpaper_event' so that '@copy_current_request_context'
        # can be used
        
        create_wave_images(converted_file_sound_path, waveform_img_path, spectrogram_img_path, width, height,
            fft_size=fft_size, progress_callback=progress_callback, progress_callback_steps=progress_callback_steps,
            color_scheme=color_scheme)

        thumbnail_waveform_path = create_thumbnail(waveform_img_path, thumbnail_width, thumbnail_height)
        thumbnail_spectrogram_path = create_thumbnail(spectrogram_img_path, thumbnail_width, thumbnail_height)

        ws_session_data = store.get(ws_session_id)
        ws_session_data['wallpapers'][color_scheme]['thumbnail_urls'] = {
            'spec': BASE_URL + APPLICATION_ROOT + '/img/' + thumbnail_spectrogram_path.split('/')[-1],
            'wave': BASE_URL + APPLICATION_ROOT + '/img/' + thumbnail_waveform_path.split('/')[-1]
        }
        store.set(ws_session_id, ws_session_data)

        # Check if all have finished. If that is the case, send progress report with all done set to True
        ws_session_data = store.get(ws_session_id)  # Reload session data (to avoid concurrency problems)
        all_done = True
        for color_scheme in ws_session_data['wallpapers']:
            if 'thumbnail_urls' not in ws_session_data['wallpapers'][color_scheme]:
                all_done = False
                break

        if all_done:
            ws_session_data['all_done'] = True

            # Save total wallpaper counter
            persistent_data = json.load(open('/app/code/persistent_data.json'))  # Load persistent data
            persistent_data['n_wallpapers'] += len(ws_session_data['color_schemes']) * 2
            json.dump(persistent_data, open('/app/code/persistent_data.json', 'w'))  # Save persistent data
            ws_session_data['n_total_wallpapers'] = persistent_data['n_wallpapers']

            store.set(ws_session_id, ws_session_data)

            # Emit final progress report message
            emit('progress_report', ws_session_data, json=True, room=ws_session_id)

    # TODO: catch key error for websockets connection problems?
    ws_session_id = request.sid

    try:
        sound_id = int(data.get('sound_id', 1234))
        width = int(data.get('width', 100))
        height = int(data.get('height', 100))
        fft_size = int(data.get('fft_size', 2048))        
    except ValueError:
        emit('progress_report', {'message': 'Invalid input parameters', 'errors': True}, json=True, room=ws_session_id)
        return
    except TypeError:
        emit('progress_report', {'message': 'Invalid input parameters', 'errors': True}, json=True, room=ws_session_id)
        return

    # Make sure width and height makes sense
    max_width_height = 6000
    if width < 10:
        width = 10
    if height < 10:
        height = 10
    if width > max_width_height:
        width = max_width_height
    if height > max_width_height:
        height = max_width_height
    

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
        'thumbnail_height': THUMBNAIL_HEIGHT,
        'thumbnail_width': THUMBNAIL_HEIGHT * 1.0 * width / height,
        'total_percentage': 0,
        'color_schemes': COLOR_SCHEMES_ENABLED,
        'wallpapers': defaultdict(dict),
        'all_done': False,
    }

    for color_scheme in COLOR_SCHEMES_ENABLED:
        waveform_filename = '%i_w_%s_%s.png' % (sound_id, out_base_filename, color_scheme)
        spectrogram_filename = '%i_s_%s_%s.jpg' % (sound_id, out_base_filename, color_scheme) 
        waveform_img_path = os.path.join(DATA_DIR, waveform_filename)
        spectrogram_img_path = os.path.join(DATA_DIR, spectrogram_filename)
        ws_session_data['wallpapers'][color_scheme]['filenames'] = {
            'spec': spectrogram_filename,
            'wave': waveform_filename,
        }
        ws_session_data['wallpapers'][color_scheme]['paths'] = {
            'spec': spectrogram_img_path,
            'wave': waveform_img_path,
        }
        store.set(ws_session_id, ws_session_data)

        # Trigger creation of images in a thread
        thread.start_new_thread(create_wallpaper_and_thumbnail, 
            (ws_session_id, converted_file_sound_path, waveform_img_path, spectrogram_img_path, width, height, ws_session_data['thumbnail_width'], ws_session_data['thumbnail_height']),
            dict(fft_size=fft_size, progress_callback=make_progress_callback_function(ws_session_id, color_scheme), progress_callback_steps=50, color_scheme=color_scheme))
        

# VIEWS

@app.route('/' + APPLICATION_ROOT, strict_slashes=False)
def index():
    # Get n_total_wallpapers from persistent data
    persistent_data = json.load(open('/app/code/persistent_data.json'))
    n_total_wallpapers = persistent_data['n_wallpapers']

    # Get sound ID from query param or choose random one
    sound_id = request.args.get('sound_id', '')
    if not sound_id:
        sound_id = get_random_freesound_id()

    # Select random wallpaper for background
    filename = random.choice([file for file in os.listdir(os.path.join(STATIC_DIR, 'img', 'examples')) if str(file) != '.DS_Store'])
    background_img_url = '/' + APPLICATION_ROOT + '/static/img/examples/' + filename

    return render_template('index.html', application_root=APPLICATION_ROOT, 
        base_url=BASE_URL, n_total_wallpapers=n_total_wallpapers, sound_id=sound_id,
        background_img_url=background_img_url)

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
