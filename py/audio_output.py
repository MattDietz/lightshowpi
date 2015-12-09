import logging
import os
import subprocess

import alsaaudio as aa

import configuration_manager as cm


def get_audio_output_handler(num_channels, sample_rate, song_title,
                             chunk_size):
    cfg = cm.CONFIG
    use_fm = cfg.getboolean('audio_processing', 'fm')
    klass = PCMOutput
    if use_fm:
        fm_flavor = cfg.get("audio_processing", "fm_flavor").lower()
        if fm_flavor == "pifm":
            klass = PiFmOutput
        elif fm_flavor == "pifmrds":
            klass = PiFmRdsOutput
    return klass(num_channels, sample_rate, song_title, chunk_size)


class AudioOutput(object):
    def __init__(self, num_channels, sample_rate, song_title, chunk_size):
        self._num_channels = str(num_channels)
        self._sample_rate = str(sample_rate)
        self._song_title = str(song_title)
        self._chunk_size = chunk_size
        self._launched = False
        self._launch()

    def _launch(self):
        if self._launched:
            return
        self._launched = True

    def cleanup(self):
        self._launched = False

    def write(self, data):
        pass


class PCMOutput(AudioOutput):
    def _launch(self):
        output = aa.PCM(aa.PCM_PLAYBACK, aa.PCM_NORMAL)
        output.setchannels(self._num_channels)
        output.setrate(self._sample_rate)
        output.setformat(aa.PCM_FORMAT_S16_LE)
        output.setperiodsize(self._chunk_size)
        self._output = output

    def write(self, data):
        self._output.write(data)


class PiFmOutput(AudioOutput):
    def _launch(self):
        if self._launched:
            return
        self._launched = True
        self._r_pipe, self._w_pipe = os.pipe()
        args = self._launch_args()
        devnull = open(os.devnull, 'w')
        self._fm_process = subprocess.Popen(args, stdin=self._r_pipe,
                                            stdout=devnull)

    def cleanup(self):
        if not self._launched:
            return
        try:
            self._fm_process.kill()
            self._fm_process.wait()
        except Exception:
            logging.info("FM process died on its own")
        self._launched = False

    def _launch_args(self):
        frequency = cfg.get("audio_processing", "frequency")
        fm_binary = cfg.get("audio_processing", "fm_bin_path")
        play_stereo = "stereo" if play_stereo else "mono"
        return ["sudo", fm_binary, "-", frequency, "44100", play_stereo]

    def write(self, data):
        os.write(self._w_pipe, data)


class PiFmRdsOutput(PiFmOutput):
    def _launch_args(self):
        cfg = cm.CONFIG
        ps_text = cfg.get("audio_processing", "fm_ps_text")
        pi_text = cfg.get("audio_processing", "fm_pi_text")
        frequency = cfg.get("audio_processing", "frequency")
        fm_binary = cfg.get("audio_processing", "fm_bin_path")
        fm_binary = fm_binary.replace("$SYNCHRONIZED_LIGHTS_HOME", cm.HOME_DIR)
        logging.info("Sending output as fm transmission on %s" % frequency)

        return ["sudo", fm_binary, "-audio", "-",
                "-freq", frequency, "-raw", "-samplerate",
                self._sample_rate, "-numchannels", self._num_channels,
                "-ps", ps_text, "-rt", self._song_title, "-pi", pi_text]

