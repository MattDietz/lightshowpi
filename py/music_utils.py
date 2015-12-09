import argparse
import multiprocessing
import os
import os.path
import re
import sys
import wave

import json
from mutagen import easyid3
import yaml

import audio_decoder
import configuration_manager as cm


MUSIC_EXTENSIONS = ["mp3", "ogg", "flac", "wav"]
CONFIG = cm.CONFIG


def check_cache_exists(path, song_filename):
    cache_filename = os.path.join(path, ".%s" % song_filename)
    config_filename = "%s.cfg" % cache_filename
    fft_filename = "%s.sync" % cache_filename
    return os.path.isfile(config_filename), os.path.isfile(fft_filename)


def fetch_id3_meta(song_filename):
    try:
        id3 = easyid3.EasyID3(song_filename)
        return {"title": id3["title"][0],
                "artist": id3["artist"][0]}
    except Exception:
        return {"title": None, "artist": None}


def get_song_meta(song_filename, chunk_size):
    music_file = audio_decoder.open(song_filename)
    sample_rate = music_file.getframerate()
    num_channels = music_file.getnchannels()
    sample_width = music_file.getsampwidth()
    frame = music_file.readframes(1)

    filename = os.path.basename(song_filename)
    dirname = os.path.dirname(song_filename)
    config_cache, fft_cache = check_cache_exists(dirname, filename)

    # TODO(mdietz): Try to get an id3 tag so we can get album and title
    meta = {
        "filename": filename,
        "path": dirname,
        "sample_rate": sample_rate,
        "num_channels": num_channels,
        "sample_width": sample_width,
        "frame_width": sample_width * num_channels,
        "config_cache": config_cache,
        "fft_cache": fft_cache,
        "chunk_size": chunk_size
    }
    meta.update(fetch_id3_meta(song_filename))

    music_file.close()
    return meta


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


def diff_playlists(new_meta, output_path):
    if not os.path.exists(output_path):
        return new_meta

    with open(output_path, 'r') as output:
        try:
            old_meta = json.load(output)
        except Exception, e:
            print "Existing playlist empty or corrupted"
            return new_meta

    # TODO(mdietz): Filenames are unreliable at best. Probably
    #               should do MD5 or SHA
    new_songs = {s["filename"]: s for s in new_meta}
    old_songs = {s["filename"]: s for s in old_meta}
    for path, meta in old_songs.iteritems():
        if path in new_songs:
            new_songs.pop(path)
    updated_meta = []
    updated_meta.extend(old_meta)
    updated_meta.extend(new_songs.values())
    if not new_songs:
        print "Nothing to do"
    else:
        print "New songs found: ", [v["title"]
                                    for k, v in new_songs.iteritems()]
    return updated_meta


def write_playlist(song_meta, output_path):
    with open(output_path, 'w') as output:
        doc = []
        for meta in song_meta:
            doc.append(meta)
        output.write(json.dumps(doc, indent=1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=str,
                        help="Path to scan for supported audio")
    parser.add_argument("-r", dest="recursive", type=bool, default=False,
                        help="Recursively search from the supplied path.")
    parser.add_argument("--output", type=str,
                        help="Writes a playlist to the path specified if "
                             "provided")
    parser.add_argument("--append", type=str,
                        help="Updates a playlist at the specified location, "
                             "only adding new songs not present in the "
                             "existing list")
    default_chunk_size = CONFIG.getint("audio_processing", "chunk_size")
    parser.add_argument("--chunk_size", type=int,
                        help="Size of each chunk to read from the path. "
                             "Directly controls the light update rate",
                             default=default_chunk_size)
    args = parser.parse_args()
    music_path = args.path
    recursive = args.recursive
    if args.output and args.append:
        print "Can't specify output and append modes at the same time!"
        sys.exit(1)

    songs = walk_path(music_path, recursive)
    song_meta = [get_song_meta(song, args.chunk_size) for song in songs]
    if args.append:
        print "Appending..."
        song_meta = diff_playlists(song_meta, args.append)
        if song_meta:
            write_playlist(song_meta, args.append)
    elif args.output:
        print "Writing/overwriting..."
        write_playlist(song_meta, args.output)
    else:
        display_song_meta(song_meta)
