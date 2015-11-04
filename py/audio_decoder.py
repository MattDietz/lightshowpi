import aifc
import os
import struct
import subprocess
import wave


LAME_BIN   = "lame"
FAAD_BIN   = "faad"
FLAC_BIN   = "flac"
FFMPEG_BIN = "ffmpeg"
OGGDEC_BIN = "oggdec"


class PCMProxy(object):
    def __init__(self, input_proc, filename):
        self._input_proc = input_proc
        self._filename = filename
        self._read_header()

    def __del__(self):
        self.close()

    def close(self):
        self._input_proc.stdout.close()

    def _read_header(self):
        self._nframes = 0
        self._soundpos = 0
        input_stream = self._input_proc.stdout
        # Read in all data
        header = input_stream.read(44)

        # Verify that the correct identifiers are present
        if (header[0:4] != "RIFF") or (header[12:16] != "fmt "):
            raise Exception("file does not start with RIFF id or fmt chunk"
                            "missing")

        self._chunksize = struct.unpack('<L', header[4:8])[0]
        self._format = header[8:12]
        self._nchannels = struct.unpack('<H', header[22:24])[0]
        self._framerate = struct.unpack('<L', header[24:28])[0]
        self._bitspersample = struct.unpack('<H', header[34:36])[0]
        self._sampwidth = (self._bitspersample + 7) // 8
        self._framesize = self._nchannels * self._sampwidth

    def readframes(self, nframes):
        r = self._input_proc.stdout.read(nframes * self._framesize)
        if not r and self._soundpos + nframes <= self._nframes:
            r = (nframes * self._framesize) * "\x00"
        if r:
            self._soundpos += nframes
        return r

    def getnchannels(self):
        return self._nchannels

    def getframerate(self):
        return self._framerate

    def getsampwidth(self):
        return self._sampwidth


def open(file_name):
    name = os.path.abspath(file_name)
    if not os.path.exists(file_name):
        raise IOError("No such file or directory: '%s'" % file_name)
    _, file_ext = os.path.splitext(name)
    file_ext = file_ext[1:]

    proc_args = []
    audio_file = None

    if file_ext in ("mp4", "m4a", "m4b", "aac"):
        proc_args = [FAAD_BIN, "-q", "-f", "2", "-w", name]
    elif file_ext == "ogg":
        proc_args = [OGG_BIN, "-q", "-o", "-", name]
    elif file_ext in ("wav", "wave"):
        audio_file = wave.open(name, "r")
    elif file_ext in ("aiff", "aif"):
        audio_file = aifc.open(name, "r")
    elif file_ext in ("mp1", "mp2", "mp3"):
        proc_args = [LAME_BIN, "--quiet", "--decode", name, "-"]
    elif file_ext in ("flac", "oga"):
        proc_args = [FLAC_BIN, "--silent", "--stdout", "-d", name]
    elif file_ext == "wma":
        proc_args = [FFMPEG_BIN, "-i", name, "-f", "wav", "-"]

    if proc_args:
        proc = subprocess.Popen(proc_args, stdout=subprocess.PIPE)
        audio_file = PCMProxy(proc, name)

    return audio_file
