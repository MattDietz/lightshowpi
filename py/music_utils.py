import argparse
import os
import os.path
import re
import sys
import wave

import decoder

MUSIC_EXTENSIONS = ["mp3", "ogg", "flac", "wav"]


def check_cache_exists(path, song_filename):
    cache_filename = os.path.join(path, ".%s" % song_filename)
    config_filename = "%s.cfg" % cache_filename
    fft_filename = "%s.sync" % cache_filename
    return os.path.isfile(config_filename), os.path.isfile(fft_filename)


def get_song_meta(song_filename):
    if song_filename.endswith('.wav'):
        music_file = wave.open(song_filename, 'r')
    else:
        music_file = decoder.open(song_filename)
    sample_rate = music_file.getframerate()
    num_channels = music_file.getnchannels()
    sample_width = music_file.getsampwidth()
    song_length = str(music_file.getnframes() / sample_rate)
    frame = music_file.readframes(1)
    print len(frame)

    filename = os.path.basename(song_filename)
    dirname = os.path.dirname(song_filename)
    config_cache, fft_cache = check_cache_exists(dirname, filename)

    meta = {
        "full_path": dirname,
        "sample_rate": sample_rate,
        "num_channels": num_channels,
        "sample_width": sample_width,
        "frame_width": sample_width * num_channels
        "config_cache": config_cache,
        "fft_cache": fft_cache,
        "song_length": song_length
    }

    music_file.close()
    return filename, meta


def walk_path(music_path, recursive=False):
    songs = []
    extensions = '|'.join(MUSIC_EXTENSIONS)
    re_str = "^.*\.(%s)$" % extensions
    extension_re = re.compile(re_str)
    for root, dirs, files in os.walk(music_path):
        abs_root = os.path.abspath(root)
        for f in files:
            f = f.lower()
            if extension_re.match(f):
                songs.append(os.path.join(abs_root, f))
        if not recursive:
            break

    return songs

def display_song_meta(song_meta):
    for song_name, song_meta in song_meta:
        print song_name
        for key, value in song_meta.iteritems():
            print "\t%s -> %s" % (key, value)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=str,
                        help="Path to scan for supported audio")
    parser.add_argument("-r", dest="recursive", type=bool, default=False,
                        help="Recursively search from the supplied path.")
    args = parser.parse_args()
    music_path = args.path
    recursive = args.recursive
    songs = walk_path(music_path, recursive)
    display_song_meta([get_song_meta(song) for song in songs])
