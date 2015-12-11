import fcntl
import json
import logging
import os
import random

import configuration_manager as cm


class Playlist(object):
    def __init__(self, path, num_songs):
        """
        Determine the next file to play

        :param play_now: application state
        :type play_now: int

        :param song_to_play: index of song to play in playlist
        :type song_to_play: int
        """
        self._num_songs = num_songs
        with open(path, 'r') as playlist_fp:
            fcntl.lockf(playlist_fp, fcntl.LOCK_SH)
            songs = []
            pl = json.load(playlist_fp)
            for song in pl:
                path = os.path.join(song["path"], song["filename"])
                path = path.replace("$SYNCHRONIZED_LIGHTS_HOME",
                                    cm.HOME_DIR)
                song_meta = {
                    "title": song["title"],
                    "path": path,
                    "chunk_size": song["chunk_size"]}
                songs.append(song_meta)

            fcntl.lockf(playlist_fp, fcntl.LOCK_UN)
        self._songs = songs
        random.shuffle(self._songs)

    def get_song(self):
        for idx, song in enumerate(self._songs):
            if idx == self._num_songs:
                raise StopIteration()

            yield song["title"], song["path"], song["chunk_size"]
