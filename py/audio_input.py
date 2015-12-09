import logging

import audio_decoder
import configuration_manager as cm


def get_audio_input_handler(song_filename, chunk_size):
    cfg = cm.CONFIG
    if cm.lightshow()['mode'] == 'audio-in':
        return LineInput()
    else:
        return StreamInput(song_filename, chunk_size)


class LineInput(object):
    def __init__(self):
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
        mean = np.array([12.0 for _ in xrange(hc.GPIOLEN)], dtype='float64')
        std = np.array([1.5 for _ in xrange(hc.GPIOLEN)], dtype='float64')
        count = 2

        running_stats = running_stats.Stats(hc.GPIOLEN)

        # preload running_stats to avoid errors, and give us a show that looks
        # good right from the start
        running_stats.preload(mean, std, count)

    def next_chunk(self):
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
            return matrix, mean, std


class StreamInput(object):
    def __init__(self, song_filename, chunk_size):
        music_file = audio_decoder.open(song_filename)
        self._chunk_size = chunk_size

        # TODO(mdietz): We can get this from the cache, too
        self.sample_rate = music_file.getframerate()
        self.num_channels = music_file.getnchannels()
        self.sample_width = music_file.getsampwidth()

        # Just a vanity metric
        chunk_period = float(self._chunk_size) / float(self.sample_rate)

        logging.info("Playing: %s" % song_filename)
        logging.info("Sample Rate: %d" % self.sample_rate)
        logging.info("Number of Channels: %d" % self.num_channels)
        logging.info("Chunk size: %d" % self._chunk_size)
        logging.info("Chunk period: %f" % chunk_period)
        self._stream = music_file

    def next_chunk(self):
        return self._stream.readframes(self._chunk_size)
