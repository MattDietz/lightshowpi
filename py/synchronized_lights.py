#!/usr/bin/env python
#
# Licensed under the BSD license.  See full license in LICENSE file.
# http://www.lightshowpi.com/
#
# Author: Todd Giles (todd@lightshowpi.com)
# Author: Chris Usey (chris.usey@gmail.com)
# Author: Ryan Jennings
# Author: Paul Dunn (dunnsept@gmail.com)
# Author: Tom Enos (tomslick.ca@gmail.com)

"""Play any audio file and synchronize lights to the music

When executed, this script will play an audio file, as well as turn on
and off N channels of lights to the music (by default the first 8 GPIO
channels on the Rasberry Pi), based upon music it is playing. Many
types of audio files are supported, but it has
only been tested with wav and mp3 at the time of this writing.

The timing of the lights turning on and off is based upon the frequency
response of the music being played.  A short segment of the music is
analyzed via FFT to get the frequency response across each defined
channel in the audio range.  Each light channel is then faded in and
out based upon the amplitude of the frequency response in the
corresponding audio channel.  Fading is accomplished with a software
PWM output.  Each channel can also be configured to simply turn on and
off as the frequency response in the corresponding channel crosses a
threshold.

FFT calculation can be CPU intensive and in some cases can adversely
affect playback of songs (especially if attempting to decode the song
as well, as is the case for an mp3).  For this reason, the FFT
cacluations are cached after the first time a new song is played.
The values are cached in a gzip'd text file in the same location as the
song itself.  Subsequent requests to play the same song will use the
cached information and not recompute the FFT, thus reducing CPU
utilization dramatically and allowing for clear music playback of all
audio file types.

Recent optimizations have improved this dramatically and most users are
no longer reporting adverse playback of songs even on the first
playback.

Sample usage:
To play an entire list -
sudo python synchronized_lights.py --playlist=/home/pi/music/.playlist

To play a specific song -
sudo python synchronized_lights.py --file=/home/pi/music/jingle_bells.mp3

Third party dependencies:

alsaaudio: for audio input/output
    http://pyalsaaudio.sourceforge.net/

numpy: for FFT calcuation
    http://www.numpy.org/
"""

import argparse
import atexit
import audioop
import contextlib
import csv
import fcntl
import logging
import multiprocessing.pool
import os
import random
import subprocess
import sys
import threading
import time

import alsaaudio as aa
import numpy as np

import audio_decoder
import audio_output
import fft
import configuration_manager as cm
import hardware_controller as hc
import prepostshow
import running_stats


# TODO(mdietz): as many of these should have defaults as possible
# Configurations - TODO(todd): Move more of this into configuration manager
_CONFIG = cm.CONFIG
_MODE = cm.lightshow()['mode']
_MIN_FREQUENCY = _CONFIG.getfloat('audio_processing', 'min_frequency')
_MAX_FREQUENCY = _CONFIG.getfloat('audio_processing', 'max_frequency')
_RANDOMIZE_PLAYLIST = _CONFIG.getboolean('lightshow', 'randomize_playlist')

try:
    _CUSTOM_CHANNEL_MAPPING = [
        int(channel)
        for channel in _CONFIG.get('audio_processing',
                                   'custom_channel_mapping').split(',')]
except ValueError:
    _CUSTOM_CHANNEL_MAPPING = 0

try:
    _CUSTOM_CHANNEL_FREQUENCIES = [
        int(channel) for channel in
        _CONFIG.get('audio_processing',
                    'custom_channel_frequencies').split(',')]
except ValueError:
    _CUSTOM_CHANNEL_FREQUENCIES = 0

_PLAYLIST_PATH = cm.lightshow()['playlist_path'].replace(
    '$SYNCHRONIZED_LIGHTS_HOME', cm.HOME_DIR)

# TODO(mdietz): Changing this would necessitate rebuilding the cache. Not sure
#               the code knows that
CHUNK_SIZE = _CONFIG.getint("audio_processing", "chunk_size")


def end_early():
    """atexit function"""
    hc.clean_up()


atexit.register(end_early)


def update_lights(matrix, mean, std):
    """Update the state of all the lights

    Update the state of all the lights based upon the current
    frequency response matrix

    :param matrix: row of data from cache matrix
    :type matrix: list

    :param mean: standard mean of fft values
    :type mean: list

    :param std: standard deviation of fft values
    :type std: list
    """
    for pin in xrange(0, hc.GPIOLEN):
        # Calculate output pwm, where off is at some portion of the std below
        # the mean and full on is at some portion of the std above the mean.
        brightness = matrix[pin] - mean[pin] + 0.5 * std[pin]
        brightness /= 1.25 * std[pin]
        if brightness > 1.0:
            brightness = 1.0

        if brightness < 0:
            brightness = 0

        if not hc.is_pin_pwm[pin]:
            # If pin is on / off mode we'll turn on at 1/2 brightness
            if brightness > 0.5:
                hc.turn_on_light(pin, True)
            else:
                hc.turn_off_light(pin, True)
        else:
            hc.turn_on_light(pin, True, brightness)


def audio_in():
    """Control the lightshow from audio coming in from a USB audio card"""
    sample_rate = cm.lightshow()['audio_in_sample_rate']
    input_channels = cm.lightshow()['audio_in_channels']

    # Open the input stream from default input device
    audio_in_card = cm.lightshow()['audio_in_card']
    stream = aa.PCM(aa.PCM_CAPTURE, aa.PCM_NORMAL, audio_in_card)
    stream.setchannels(input_channels)
    stream.setformat(aa.PCM_FORMAT_S16_LE)  # Expose in config if needed
    stream.setrate(sample_rate)
    stream.setperiodsize(CHUNK_SIZE)

    logging.debug("Running in audio-in mode - will run until Ctrl+C "
                  "is pressed")
    print "Running in audio-in mode, use Ctrl+C to stop"

    # Start with these as our initial guesses - will calculate a rolling
    # mean / std as we get input data.
    mean = np.array([12.0 for _ in range(hc.GPIOLEN)], dtype='float64')
    std = np.array([1.5 for _ in range(hc.GPIOLEN)], dtype='float64')
    count = 2

    running_stats = running_stats.Stats(hc.GPIOLEN)

    # preload running_stats to avoid errors, and give us a show that looks
    # good right from the start
    running_stats.preload(mean, std, count)

    try:
        hc.initialize()
        fft_calc = fft.FFT(CHUNK_SIZE,
                           sample_rate,
                           hc.GPIOLEN,
                           _MIN_FREQUENCY,
                           _MAX_FREQUENCY,
                           _CUSTOM_CHANNEL_MAPPING,
                           _CUSTOM_CHANNEL_FREQUENCIES,
                           input_channels)

        # Listen on the audio input device until CTRL-C is pressed
        while True:
            length, data = stream.read()
            if length > 0:
                # if the maximum of the absolute value of all samples in
                # data is below a threshold we will disreguard it
                audio_max = audioop.max(data, 2)
                if audio_max < 250:
                    # we will fill the matrix with zeros and turn the
                    # lights off
                    matrix = np.zeros(hc.GPIOLEN, dtype="float64")
                    logging.debug("below threshold: '" + str(
                        audio_max) + "', turning the lights off")
                else:
                    matrix = fft_calc.calculate_levels(data)
                    running_stats.push(matrix)
                    mean = running_stats.mean()
                    std = running_stats.std()

                update_lights(matrix, mean, std)

    except KeyboardInterrupt:
        pass

    finally:
        print "\nStopping"
        hc.clean_up()


# TODO(todd): Refactor more of this to make it more readable / modular.
def get_song(play_now, song_to_play):
    """
    Determine the next file to play

    :param play_now: application state
    :type play_now: int

    :param song_to_play: index of song to play in playlist
    :type song_to_play: int
    """
    song_filename = args.file
    if args.playlist is not None and args.file is None:
        most_votes = [None, None, []]

        with open(args.playlist, 'rb') as playlist_fp:
            fcntl.lockf(playlist_fp, fcntl.LOCK_SH)
            playlist = csv.reader(playlist_fp, delimiter='\t')
            songs = []

            for song in playlist:
                if len(song) < 2 or len(song) > 4:
                    logging.error('Invalid playlist.  Each line should be in '
                                  'the form: <song name><tab><path to song>')
                    sys.exit()
                elif len(song) == 2:
                    song.append(set())
                else:
                    song[2] = set(song[2].split(','))
                    if len(song) == 3 and len(song[2]) >= len(most_votes[2]):
                        most_votes = song
                songs.append(song)

            fcntl.lockf(playlist_fp, fcntl.LOCK_UN)

        if most_votes[0] is not None:
            logging.info("Most Votes: " + str(most_votes))
            current_song = most_votes

            # Update playlist with latest votes
            with open(args.playlist, 'wb') as playlist_fp:
                fcntl.lockf(playlist_fp, fcntl.LOCK_EX)
                writer = csv.writer(playlist_fp, delimiter='\t')

                for song in songs:
                    if current_song == song and len(song) == 3:
                        song.append("playing!")

                    if len(song[2]) > 0:
                        song[2] = ",".join(song[2])
                    else:
                        del song[2]

                writer.writerows(songs)
                fcntl.lockf(playlist_fp, fcntl.LOCK_UN)

        else:
            # Get a "play now" requested song
            if 0 < play_now <= len(songs):
                current_song = songs[play_now - 1]
            # Get random song
            elif _RANDOMIZE_PLAYLIST:
                # Use python's random.randrange() to get a random song
                current_song = songs[random.randrange(0, len(songs))]

            # Play next song in the lineup
            else:
                if not (song_to_play <= len(songs) - 1):
                    song_to_play = 0

                current_song = songs[song_to_play]

                if (song_to_play + 1) <= len(songs) - 1:
                    next_song = (song_to_play + 1)
                else:
                    next_song = 0

                cm.update_state('song_to_play', str(next_song))

        # Get filename to play and store the current song playing in state cfg
        song_filename = current_song[1]
        cm.update_state('current_song', str(songs.index(current_song)))

    song_title = song[0]
    song_filename = song_filename.replace("$SYNCHRONIZED_LIGHTS_HOME",
                                          cm.HOME_DIR)
    return song_title, song_filename


# TODO(mdietz): This pre-caching is fine but we should still be able to do a
#               live mode with a mic or the audio-in port. I'll need to fork
#               PiFmRds and have it take raw input
# TODO(mdietz): Looking like the music handle should be a class
#               so we don't have to yield 3 things
@contextlib.contextmanager
def stream_music(song_filename, play_now):
    # Set up audio
    music_file = audio_decoder.open(song_filename)

    # TODO(mdietz): We can get this from the cache, too
    sample_rate = music_file.getframerate()
    num_channels = music_file.getnchannels()
    sample_width = music_file.getsampwidth()

    # Just a vanity metric
    chunk_period = float(CHUNK_SIZE) / float(sample_rate)

    logging.info("Playing: %s" % song_filename)
    logging.info("Sample Rate: %d" % sample_rate)
    logging.info("Number of Channels: %d" % num_channels)
    logging.info("Chunk period: %f" % chunk_period)

    def next_chunk():
        while True:
            data = music_file.readframes(CHUNK_SIZE)
            if not data:
                break
            yield data

    # TODO(mdietz): not really a fan of this interface
    yield num_channels, sample_rate, next_chunk
    music_file.close()


def load_cached_fft(fft_calc, cache_filename):
     # Read in cached fft
    try:
        # load cache from file using numpy loadtxt
        cache_matrix = np.loadtxt(cache_filename)

        # compare configuration of cache file to current configuration
        cache_found = fft_calc.compare_config(cache_filename)
        if not cache_found:
            # create empty array for the cache_matrix
            cache_matrix = np.empty(shape=[0, hc.GPIOLEN])
            raise IOError()

        # get std from matrix / located at index 0
        std = np.array(cache_matrix[0])

        # get mean from matrix / located at index 1
        mean = np.array(cache_matrix[1])

        # delete mean and std from the array
        cache_matrix = np.delete(cache_matrix, 0, axis=0)
        cache_matrix = np.delete(cache_matrix, 0, axis=0)

        logging.debug("std: " + str(std) + ", mean: " + str(mean))
    except IOError:
        cache_found = fft_calc.compare_config(cache_filename)
        logging.warn("Cached sync data song_filename not found: '"
                     + cache_filename
                     + "'.  One will be generated.")

    return mean, std, cache_matrix


def cache_song(song_filename):
    music_file = audio_decoder.open(song_filename)
    sample_rate = music_file.getframerate()
    num_channels = music_file.getnchannels()
    logging.info("Sample rate: %s" % sample_rate)
    logging.info("Channels: %s" % num_channels)
    logging.info("Frame size: %s" % music_file.getsampwidth())

    fft_calc = fft.FFT(CHUNK_SIZE,
                       sample_rate,
                       hc.GPIOLEN,
                       _MIN_FREQUENCY,
                       _MAX_FREQUENCY,
                       _CUSTOM_CHANNEL_MAPPING,
                       _CUSTOM_CHANNEL_FREQUENCIES)

    # Init cache matrix
    cache_matrix = np.empty(shape=[0, hc.GPIOLEN])
    cache_filename = os.path.dirname(song_filename) + "/." + os.path.basename(
        song_filename) + ".sync"
    cache_found = fft_calc.compare_config(cache_filename)

    if cache_found:
        mean, std, cache_matrix = load_cached_fft(fft_calc, cache_filename)
    else:
        # The values 12 and 1.5 are good estimates for first time playing back
        # (i.e. before we have the actual mean and standard deviations
        # calculated for each channel).
        mean = [12.0 for _ in xrange(hc.GPIOLEN)]
        std = [1.5 for _ in xrange(hc.GPIOLEN)]
        total = 0
        while True:
            data = music_file.readframes(CHUNK_SIZE)
            if not data:
                break
            total += len(data)

            matrix = fft_calc.calculate_levels(data)
            # Add the matrix to the end of the cache
            cache_matrix = np.vstack([cache_matrix, matrix])

        for i in range(0, hc.GPIOLEN):
            std[i] = np.std([item for item in cache_matrix[:, i]
                             if item > 0])
            mean[i] = np.mean([item for item in cache_matrix[:, i]
                               if item > 0])

        # Add mean and std to the top of the cache
        cache_matrix = np.vstack([mean, cache_matrix])
        cache_matrix = np.vstack([std, cache_matrix])

        # Save the cache using numpy savetxt
        np.savetxt(cache_filename, cache_matrix)

        # Save fft config
        fft_calc.save_config()

        logging.info("Cached sync data written to '." + cache_filename
                     + "' [" + str(len(cache_matrix)) + " rows]")

        logging.info("Cached config data written to '." +
                     fft_calc.config_filename)
    music_file.close()
    return mean, std, cache_matrix


def get_next_song_path(play_now):
    song_to_play = int(cm.get_state('song_to_play', "0"))
    song_title, song_filename = get_song(play_now, song_to_play)
    song_filename = os.path.abspath(song_filename)
    return song_title, song_filename


# TODO(mdietz): the project assumes that this is simply a python bin
#               that is called by a bash script. I think we should
#               re-work that to be a long running thing, all in Python
def play_song():
    """Play the next song from the play list (or --file argument)."""
    play_now = int(cm.get_state('play_now', "0"))

    # Make sure one of --playlist or --file was specified
    if args.file is None and args.playlist is None:
        print "One of --playlist or --file must be specified"
        sys.exit()

    # Initialize Lights
    hc.initialize()

    song_title, song_filename = get_next_song_path(play_now)

    # Fork and warm the cache. Technically race prone but meh
    pool = multiprocessing.pool.Pool(processes=1)
    cache_proc = pool.apply_async(cache_song, [song_filename])

    # Handle the pre/post show
    if not play_now:
        result = prepostshow.PrePostShow('preshow', hc).execute()

        if result == prepostshow.PrePostShow.play_now_interrupt:
            play_now = int(cm.get_state('play_now', "0"))

    # TODO(mdietz): What the hell is this play_now variable really for?
    # Ensure play_now is reset before beginning playback
    if play_now:
        cm.update_state('play_now', "0")
        play_now = 0

    # Wait for the cache
    cache_proc.wait()
    mean, std, cache_matrix = cache_proc.get()

    # NOTE(mdietz): Adapt this to a standard radio, not an SDR. The SDR
    #               has a clear extra amount of delay
    light_show_delay = _CONFIG.getfloat("lightshow", "light_delay")
    logging.info("Delaying light show by %f seconds" % light_show_delay)

    with stream_music(song_filename, play_now) as (num_channels, sample_rate,
                                                   next_chunk):
        audio_out_stream = audio_output.get_audio_output_handler(num_channels,
                                                                 sample_rate,
                                                                 song_title)
        try:
            # Process audio
            row = 0
            start_time = time.time()
            for data in next_chunk():
                if play_now:
                    break

                audio_out_stream.write(data)
                # TODO(mdietz): This actually pretty much works, but it would
                #               be nice to figure out what the actual delay
                #               time is, and also make it a config value
                # TODO(mdietz): I may be able to time the popen to first stdout
                #               from the fm proc for a dynamic delay
                if time.time() - start_time < light_show_delay:
                    continue

                matrix = cache_matrix[row]
                update_lights(matrix, mean, std)

                # Read next chunk of data from music

                # Load new application state in case we've been interrupted
                # TODO(mdietz): not the way to do this. Read from a db,
                #               accept a signal or some other OOB proc
                cm.load_state()
                play_now = int(cm.get_state('play_now', "0"))
                row += 1

            # Cleanup the fm process if there is one
        except Exception:
            logger.exception("Error in playback")
        finally:
            audio_out_stream.cleanup()

    # check for postshow
    prepostshow.PrePostShow('postshow', hc).execute()

    # We're done, turn it all off and clean up things ;)
    hc.clean_up()


if __name__ == "__main__":
    # Arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', default='INFO',
                        help='Set the logging level. levels:INFO, DEBUG,'
                             'WARNING, ERROR, CRITICAL')

    filegroup = parser.add_mutually_exclusive_group()
    filegroup.add_argument('--playlist', default=_PLAYLIST_PATH,
                           help='Playlist to choose song from.')
    filegroup.add_argument('--file', help='path to the song to play '
                                          '(required if no playlist is '
                                          'designated)')
    args = parser.parse_args()

    logging.basicConfig(filename=cm.LOG_DIR + '/music_and_lights.play.dbg',
                        format='[%(asctime)s] %(levelname)s '
                               '{%(pathname)s:%(lineno)d} - %(message)s',
                        level=logging.INFO)

    # logging levels
    levels = {'DEBUG': logging.DEBUG,
              'INFO': logging.INFO,
              'WARNING': logging.WARNING,
              'ERROR': logging.ERROR,
              'CRITICAL': logging.CRITICAL}

    level = levels.get(parser.parse_args().log.upper())
    logging.getLogger().setLevel(level)

    if cm.lightshow()['mode'] == 'audio-in':
        audio_in()
    else:
        play_song()
